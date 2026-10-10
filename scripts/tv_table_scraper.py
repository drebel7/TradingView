#!/usr/bin/env python3
"""
tv_table_scraper.py
===================
Scrapes a Pine Script indicator's table (e.g. "early trend strong breakout")
for every symbol in a TradingView watchlist file, and writes the results to CSV.

How it works
------------
It talks directly to TradingView Desktop over the Chrome DevTools Protocol
(CDP) WebSocket on port 9222 (the same transport the tradingview-desktop MCP
server uses). For each symbol it:
  1. calls  _exposed_chartWidgetCollection.setSymbol(<symbol>)
  2. waits until the chart symbol matches AND the indicator table is stable
  3. reads the Pine `table.new` cells from the study's graphics primitives
     (every column; multi-column tables like the ETSB 8-column perf table are
     captured in full)
  4. appends one CSV row per signal, with the perf string split into
     succ/total/success_pct/avg_gain and the extended metrics
     (win_pct, n, avg_r, pf, max_dd, score, sum_win_r, sum_loss_r) plus the
     raw row

If TradingView Desktop is not reachable over CDP, the script launches it with
--remote-debugging-port (restarting it first if it is running without CDP), then
waits for the chart page. Use --no-tv-autolaunch to disable, --tv-path to point
at a specific TradingView.exe (some Store/MSIX installs), --tv-kill-existing /
--no-tv-kill-existing to control restarting.

Output is appended incrementally, so an interrupted run keeps its data.
A progress file lets the run resume with --start / is written every symbol.

Usage
-----
  python tv_table_scraper.py \
      --watchlist watchlist/GPW_NC.txt \
      --outdir analysis \
      --tag GPW_NC_ETSB \
      --indicator "early trend strong breakout" \
      [--resolution D] [--min-rows 5] \
      [--limit 10] [--start 0] [--timeout 25] [--settle 0.6] \
      [--tv-port 9222] [--tv-path PATH] [--no-tv-autolaunch]

The watchlist format: comma separated items; group separators start with "###".
"""

import argparse
import asyncio
import csv
import glob
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import time
import urllib.request
from datetime import datetime
from pathlib import Path

try:
    from websockets.asyncio.client import connect
except Exception:  # pragma: no cover - fallback for older websockets
    from websockets import connect  # type: ignore

DEFAULT_CDP_PORT = 9222


# ----------------------------------------------------------------------------
# TradingView Desktop launch (CDP)
# ----------------------------------------------------------------------------
def cdp_available(port, timeout=1.5):
    """True if a Chrome DevTools Protocol endpoint answers on this port."""
    try:
        with urllib.request.urlopen(
            f"http://127.0.0.1:{port}/json/version", timeout=timeout
        ) as r:
            r.read(1)
        return True
    except Exception:
        return False


def is_tv_running():
    """True if a TradingView Desktop process is running."""
    system = platform.system()
    try:
        if system == "Windows":
            out = subprocess.run(
                ["tasklist", "/FI", "IMAGENAME eq TradingView.exe", "/NH"],
                capture_output=True, text=True, timeout=10,
            ).stdout
            return "TradingView.exe" in out
        out = subprocess.run(
            ["pgrep", "-f", "TradingView"], capture_output=True, text=True, timeout=10
        )
        return out.returncode == 0
    except Exception:
        return False


def kill_tv():
    """Force-quit any running TradingView Desktop instance."""
    system = platform.system()
    try:
        if system == "Windows":
            subprocess.run(["taskkill", "/IM", "TradingView.exe", "/F"],
                           capture_output=True, text=True, timeout=15)
        else:
            subprocess.run(["pkill", "-f", "TradingView"],
                           capture_output=True, text=True, timeout=15)
    except Exception as e:
        print(f"[warn] could not stop TradingView: {e}")


def _windows_store_tv_path():
    """Resolve the Microsoft Store/MSIX install path via Get-AppxPackage.

    The WindowsApps directory is not listable, so glob cannot find it, but the
    exact path is returned by Get-AppxPackage and is executable.
    """
    ps = ("Get-AppxPackage *TradingView* | "
          "Select-Object -ExpandProperty InstallLocation")
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps],
            capture_output=True, text=True, timeout=25,
        ).stdout
    except Exception:
        return None
    for line in out.splitlines():
        loc = line.strip()
        if not loc:
            continue
        exe = os.path.join(loc, "TradingView.exe")
        if os.path.isfile(exe):
            return exe
    return None


def find_tv_executable():
    """Best-effort locate the TradingView Desktop executable."""
    system = platform.system()
    candidates = []
    if system == "Windows":
        local = os.environ.get("LOCALAPPDATA", "")
        pf = os.environ.get("ProgramFiles", r"C:\Program Files")
        pf86 = os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")
        candidates += [
            os.path.join(local, "Microsoft", "WindowsApps", "TradingView.exe"),
            os.path.join(local, "Programs", "TradingView", "TradingView.exe"),
            os.path.join(local, "TradingView", "TradingView.exe"),
            os.path.join(pf, "TradingView", "TradingView.exe"),
            os.path.join(pf86, "TradingView", "TradingView.exe"),
        ]
        # Microsoft Store / MSIX install (glob fails: dir not listable)
        candidates += glob.glob(
            r"C:\Program Files\WindowsApps\TradingView.Desktop_*_x64__*\TradingView.exe"
        )
        store = _windows_store_tv_path()
        if store:
            candidates.append(store)
    elif system == "Darwin":
        candidates += [
            "/Applications/TradingView.app/Contents/MacOS/TradingView",
            os.path.expanduser("~/Applications/TradingView.app/Contents/MacOS/TradingView"),
        ]
    else:
        candidates += [
            "/opt/TradingView/tradingview",
            "/usr/bin/tradingview",
            shutil.which("tradingview") or "",
        ]
    for c in candidates:
        if c and os.path.isfile(c):
            return c
    return None


def launch_tv(exe, port):
    """Launch TradingView Desktop with the CDP debugging port enabled."""
    system = platform.system()
    try:
        if system == "Windows":
            # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP: survives this script.
            flags = 0x00000008 | 0x00000200
            subprocess.Popen(
                [exe, f"--remote-debugging-port={port}"],
                creationflags=flags, close_fds=True,
            )
        elif system == "Darwin":
            subprocess.Popen(
                ["open", "-a", "TradingView", "--args", f"--remote-debugging-port={port}"]
            )
        else:
            subprocess.Popen(
                [exe, f"--remote-debugging-port={port}"], start_new_session=True
            )
    except Exception as e:
        raise RuntimeError(
            f"Failed to launch TradingView ({exe}): {e}. "
            f"If it is a Store/MSIX install, pass --tv-path with the full path."
        )


def ensure_tv_cdp(port, exe_path=None, kill_existing=True, launch_wait=30.0):
    """Make sure TradingView Desktop is running with CDP on `port`."""
    if cdp_available(port):
        print(f"[i] TradingView CDP already available on port {port}")
        return True

    print(f"[i] CDP port {port} not reachable - checking TradingView Desktop...")
    if is_tv_running():
        if not kill_existing:
            raise RuntimeError(
                f"TradingView is running but CDP port {port} is closed. Quit "
                f"TradingView first, or run with --tv-kill-existing."
            )
        print("[i] TradingView is running WITHOUT CDP - restarting it with CDP...")
        kill_tv()
        time.sleep(3)

    exe = exe_path or find_tv_executable()
    if not exe:
        raise RuntimeError(
            "TradingView Desktop executable not found. Pass "
            '--tv-path "C:\\path\\to\\TradingView.exe".'
        )
    print(f"[i] launching: {exe} --remote-debugging-port={port}")
    launch_tv(exe, port)

    deadline = time.monotonic() + launch_wait
    while time.monotonic() < deadline:
        if cdp_available(port):
            print(f"[i] TradingView CDP is up on port {port}")
            return True
        time.sleep(1)
    raise RuntimeError(
        f"TradingView was launched but CDP port {port} did not open within "
        f"{launch_wait:.0f}s. For a Store/MSIX install, pass --tv-path."
    )


# ----------------------------------------------------------------------------
# CDP helpers
# ----------------------------------------------------------------------------
def find_chart_ws_url(port):
    """Return the CDP WebSocket debugger URL of the TradingView chart page."""
    with urllib.request.urlopen(f"http://127.0.0.1:{port}/json", timeout=10) as resp:
        targets = json.loads(resp.read().decode("utf-8"))
    for t in targets:
        if t.get("type") == "page" and "tradingview.com/chart/" in (t.get("url") or ""):
            return t["webSocketDebuggerUrl"]
    # fallback: any tradingview.com page
    for t in targets:
        if t.get("type") == "page" and "tradingview.com" in (t.get("url") or ""):
            return t["webSocketDebuggerUrl"]
    raise RuntimeError(f"TradingView chart page not found on CDP port {port}")


def wait_for_chart_ws_url(port, timeout=60.0):
    """Wait until a TradingView chart page is available over CDP."""
    deadline = time.monotonic() + timeout
    last_err = None
    while time.monotonic() < deadline:
        try:
            return find_chart_ws_url(port)
        except Exception as e:
            last_err = e
            time.sleep(1)
    raise RuntimeError(
        f"No TradingView chart page found within {timeout:.0f}s: {last_err}"
    )


class CDP:
    """Minimal CDP client (Runtime.evaluate only)."""

    def __init__(self, ws):
        self.ws = ws
        self._id = 0

    async def evaluate(self, expression, await_promise=False):
        self._id += 1
        mid = self._id
        msg = {
            "id": mid,
            "method": "Runtime.evaluate",
            "params": {
                "expression": expression,
                "returnByValue": True,
                "awaitPromise": await_promise,
            },
        }
        await self.ws.send(json.dumps(msg))
        while True:
            raw = await self.ws.recv()
            resp = json.loads(raw)
            if resp.get("id") == mid:
                if "error" in resp:
                    raise RuntimeError(f"CDP error: {resp['error']}")
                res = resp.get("result", {})
                if "exceptionDetails" in res:
                    raise RuntimeError(f"JS exception: {res['exceptionDetails']}")
                return res.get("result", {}).get("value")
            # ignore unrelated events


# ----------------------------------------------------------------------------
# JS snippets
# ----------------------------------------------------------------------------
JS_READ_STATE = r"""
(function(){
  try{
    var c = window._exposed_chartWidgetCollection;
    var w = c.activeChartWidget; if(w && w._value!==undefined) w=w._value;
    var m = w.model();
    var sym = m.mainSeries().symbol();
    var target = "__INDICATOR__";
    var ds = m.dataSources();
    var study=null;
    for(var i=0;i<ds.length;i++){
      try{ var nm=(ds[i].name&&ds[i].name())||''; if(nm.indexOf(target)===0){study=ds[i];break;} }catch(e){}
    }
    if(!study) return JSON.stringify({symbol:sym, ready:false, err:'no study'});
    var st = study.status && study.status();
    var statusType = st && st.type;
    var rows=[];
    try{
      var pc = study.graphics()._primitivesCollection;
      var tc = pc.dwgtablecells.get('tableCells');
      if(tc){
        var cells=[];
        tc._primitivesDataById.forEach(function(v){ cells.push({r:+v.row,c:+v.col,t:v.t}); });
        cells.sort(function(a,b){return a.r-b.r||a.c-b.c;});
        var rm={};
        cells.forEach(function(cl){ (rm[cl.r]=rm[cl.r]||{})[cl.c]=cl.t; });
        rows = Object.keys(rm).sort(function(a,b){return a-b;}).map(function(r){
          var cc=rm[r]; var maxc=-1;
          for(var k in cc){ if(cc.hasOwnProperty(k)){ var kk=+k; if(kk>maxc) maxc=kk; } }
          var arr=[]; for(var j=0;j<=maxc;j++){ arr.push(cc[j]!==undefined?cc[j]:''); }
          return arr;
        });
      }
    }catch(e){}
    return JSON.stringify({symbol:sym, statusType:statusType, ready:true, rows:rows});
  }catch(e){ return JSON.stringify({symbol:null, ready:false, err:String(e)}); }
})()
"""


JS_READY = r"""
(function(){
  try{
    var c=window._exposed_chartWidgetCollection;
    if(!c) return JSON.stringify({ready:false});
    var w=c.activeChartWidget; if(w&&w._value!==undefined) w=w._value;
    var hasModel = !!(w && w.hasModel && w.hasModel());
    var loading = c._flags ? !!c._flags.loadingChart : false;
    var sym = hasModel ? w.model().mainSeries().symbol() : null;
    return JSON.stringify({ready: hasModel && !loading && !!sym, symbol: sym, loading: loading});
  }catch(e){ return JSON.stringify({ready:false, err:String(e)}); }
})()
"""


def js_set_symbol(symbol):
    return "window._exposed_chartWidgetCollection.setSymbol(%s)" % json.dumps(symbol)


def js_set_resolution(resolution):
    return "window._exposed_chartWidgetCollection.setResolution(%s)" % json.dumps(resolution)


JS_GET_INTERVAL = (
    "(function(){var w=window._exposed_chartWidgetCollection.activeChartWidget;"
    "if(w&&w._value!==undefined)w=w._value;return w.model().mainSeries().interval();})()"
)


def _norm_res(r):
    r = str(r).strip().upper()
    if r in ("D", "W", "M"):
        return r
    if r in ("1D", "1W", "1M"):
        return r[1:]
    return r


async def set_resolution(cdp, resolution, timeout=20.0):
    """Set chart resolution and wait until it applies. Returns True on success."""
    try:
        await cdp.evaluate(js_set_resolution(resolution))
    except Exception as e:
        print(f"[warn] setResolution('{resolution}') failed: {e}")
        return False
    target = _norm_res(resolution)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            cur = await cdp.evaluate(JS_GET_INTERVAL)
        except Exception:
            cur = None
        if cur is not None and _norm_res(cur) == target:
            return True
        await asyncio.sleep(0.4)
    print(f"[warn] resolution '{resolution}' not confirmed within {timeout}s (continuing)")
    return False


# ----------------------------------------------------------------------------
# Parsing
# ----------------------------------------------------------------------------
# Column 1 ("perf") of the ETSB table: "x% (a/b) y%".
# Legacy tables appended a single-number score ("x% (a/b) y% z") - the trailing
# score is still accepted (optional group) for backward compatibility.
PERF_RE = re.compile(
    r"^\s*([\d.]+)%\s*\((\d+)\s*/\s*(\d+)\)\s+([+-]?[\d.]+)%(?:\s+(-?\d+))?\s*$"
)

# Extended metric columns of the ETSB table (positions after "perf"):
#   2 win%   3 N   4 avgR   5 PF   6 maxDD   7 score   8 gross win R   9 gross loss R
EXT_METRIC_COLUMNS = [
    ("win_pct", 2),
    ("n", 3),
    ("avg_r", 4),
    ("pf", 5),
    ("max_dd", 6),
    ("score", 7),
    ("sum_win_r", 8),
    ("sum_loss_r", 9),
]

# Full CSV schema.
CSV_COLUMNS = [
    "group", "symbol", "sig", "succ", "total", "success_pct", "avg_gain",
    "win_pct", "n", "avg_r", "pf", "max_dd", "score", "sum_win_r", "sum_loss_r",
    "raw",
]


def parse_perf(text):
    """Parse 'x% (a/b) y%' (or legacy 'x% (a/b) y% z') -> dict, or None for '-'."""
    text = (text or "").strip()
    if text == "-" or text == "":
        return None
    m = PERF_RE.match(text)
    if not m:
        return None
    return {
        "success_pct": float(m.group(1)),
        "succ": int(m.group(2)),
        "total": int(m.group(3)),
        "avg_gain": float(m.group(4)),
        "legacy_score": int(m.group(5)) if m.group(5) is not None else None,
    }


def parse_metric(text):
    """Parse a numeric table cell to float, or None for ''/'-'/unparseable."""
    text = (text or "").strip()
    if text in ("", "-"):
        return None
    try:
        return float(text)
    except ValueError:
        return None


def row_to_record(cells):
    """Map a raw table row (list of cell strings) to a metric record.

    The first column is the signal name, the second is the perf string
    ('x% (a/b) y%'); any further columns are the extended metrics (win%, N,
    avgR, PF, maxDD, score). Rows for a signal that never occurred ('-') keep
    every metric blank; the full row is always preserved in 'raw'.
    """
    cells = [("" if c is None else str(c)) for c in cells]
    rec = {c: "" for c in CSV_COLUMNS}
    rec["sig"] = (cells[0].strip() if cells else "")
    rec["raw"] = " | ".join(cells)
    perf = cells[1] if len(cells) > 1 else ""
    p = parse_perf(perf)
    if not p or p["total"] <= 0:
        return rec
    rec["succ"] = p["succ"]
    rec["total"] = p["total"]
    rec["success_pct"] = p["success_pct"]
    rec["avg_gain"] = p["avg_gain"]
    for name, idx in EXT_METRIC_COLUMNS:
        val = parse_metric(cells[idx] if len(cells) > idx else "")
        if val is None:
            continue
        rec[name] = int(val) if name == "n" else val
    if rec["score"] == "" and p.get("legacy_score") is not None:
        rec["score"] = p["legacy_score"]
    return rec


# ----------------------------------------------------------------------------
# Watchlist
# ----------------------------------------------------------------------------
def _ticker(sym):
    """Ticker part of EXCHANGE:TICKER (TradingView may canonicalize the exchange,
    e.g. NASDAQ:NVDA -> BATS:NVDA, so compare on the ticker)."""
    return (sym or "").split(":")[-1].strip().upper()


def parse_watchlist(path):
    content = Path(path).read_text(encoding="utf-8", errors="replace")
    items = [x.strip() for x in content.split(",") if x.strip()]
    out = []
    group = "UNKNOWN"
    for it in items:
        if it.startswith("###"):
            group = it[3:].strip()
        else:
            out.append((group, it))
    return out


# ----------------------------------------------------------------------------
# Scrape loop
# ----------------------------------------------------------------------------
async def wait_chart_ready(cdp, timeout=90.0, consecutive=2):
    """Wait until the chart finished loading (fresh launch may still be busy)."""
    deadline = time.monotonic() + timeout
    good = 0
    while time.monotonic() < deadline:
        try:
            st = json.loads(await cdp.evaluate(JS_READY))
        except Exception:
            st = {"ready": False}
        if st.get("ready"):
            good += 1
            if good >= consecutive:
                return True
        else:
            good = 0
        await asyncio.sleep(0.5)
    return False


async def scrape_symbol(cdp, symbol, indicator, timeout, settle_interval, min_rows):
    """Switch to symbol and return the raw table rows (list of cell lists).

    setSymbol is re-issued (every ~2s) while the chart still shows another
    symbol - this handles the race right after a fresh TradingView launch where
    the chart is still loading and would otherwise ignore the request.
    """
    deadline = time.monotonic() + timeout
    prev_key = None
    stable = 0
    last_state = None
    last_set = 0.0
    target_ticker = _ticker(symbol)

    while time.monotonic() < deadline:
        now = time.monotonic()
        # (Re)issue the symbol switch only while the chart is on a wrong symbol.
        if last_state is None or _ticker(last_state.get("symbol")) != target_ticker:
            if now - last_set >= 2.0:
                try:
                    await cdp.evaluate(js_set_symbol(symbol))
                    last_set = now
                except Exception:
                    await asyncio.sleep(0.4)
                    continue

        try:
            raw = await cdp.evaluate(JS_READ_STATE.replace("__INDICATOR__", indicator))
            state = json.loads(raw)
        except Exception:
            await asyncio.sleep(0.4)
            continue

        last_state = state
        if _ticker(state.get("symbol")) == target_ticker and state.get("ready"):
            rows = state.get("rows") or []
            if len(rows) >= min_rows:
                key = json.dumps(rows)
                if key == prev_key:
                    stable += 1
                else:
                    stable = 0
                    prev_key = key
                if stable >= 1:  # two consecutive identical reads
                    return rows, None
        await asyncio.sleep(settle_interval)

    return None, f"timeout (last={last_state})"


HEADER_MARKER = "# TradingView table scraper results v2"


def write_csv_header(path, indicator, watchlist):
    if path.exists() and path.stat().st_size > 0:
        # Refuse to append to a file that was not produced by this scraper
        # (schema v2 - older files without the extended metric columns fail here).
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            first = f.readline().strip()
        if first != HEADER_MARKER:
            raise SystemExit(
                f"ERROR: {path} exists but is not a current scraper output file "
                f"(first line: {first!r}, expected {HEADER_MARKER!r}). "
                f"Remove or rename it and retry."
            )
        return
    with open(path, "w", newline="", encoding="utf-8") as f:
        f.write(HEADER_MARKER + "\n")
        f.write(f"# indicator: {indicator}\n")
        f.write(f"# watchlist: {watchlist}\n")
        f.write(f"# generated: {datetime.now().isoformat(timespec='seconds')}\n")
        f.write("# columns: " + ",".join(CSV_COLUMNS) + "\n")
        f.write("# perf = 'x% (a/b) y%' (success rate a/b and avg return y%); "
                "'-' means the signal did not occur for that symbol\n")
        f.write("# extended metrics: win_pct, n, avg_r, pf, max_dd, score, sum_win_r, sum_loss_r "
                "(blank when the signal did not occur)\n")
        f.write("# pf is shown as the infinity sign and left blank here when there are no losing trades\n")
        w = csv.writer(f)
        w.writerow(CSV_COLUMNS)


def append_rows(path, group, symbol, rows):
    with open(path, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        for cells in rows:
            rec = row_to_record(cells)
            if rec["sig"] in ("", "sig"):
                continue  # skip empty / header rows
            w.writerow([group, symbol] + [rec[c] for c in CSV_COLUMNS[2:]])


async def main_async(args):
    if args.tv_autolaunch:
        ensure_tv_cdp(args.tv_port, args.tv_path,
                      args.tv_kill_existing, args.tv_launch_wait)
    ws_url = wait_for_chart_ws_url(args.tv_port, timeout=60)
    print(f"[i] CDP chart target: {ws_url}")

    symbols = parse_watchlist(args.watchlist)
    total = len(symbols)
    print(f"[i] watchlist: {args.watchlist} -> {total} symbols")

    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    date_tag = datetime.now().strftime("%Y%m%d")
    out_csv = outdir / f"{args.tag}_{date_tag}.csv"
    progress_path = outdir / f".{args.tag}_progress.json"

    write_csv_header(out_csv, args.indicator, args.watchlist)
    print(f"[i] output CSV: {out_csv}")

    start = args.start
    end = total if args.limit <= 0 else min(total, start + args.limit)

    ok = 0
    fail = 0

    async with connect(ws_url, max_size=None, open_timeout=15) as ws:
        cdp = CDP(ws)
        if not await wait_chart_ready(cdp, timeout=90):
            print("[warn] chart did not report ready within 90s - continuing anyway")
        if args.resolution:
            ok_res = await set_resolution(cdp, args.resolution)
            print(f"[i] resolution set to '{args.resolution}': {ok_res}")
        for idx in range(start, end):
            group, symbol = symbols[idx]
            label = f"[{idx+1}/{total}] {symbol} ({group})"
            sys.stdout.write(label + " ... ")
            sys.stdout.flush()

            t0 = time.monotonic()
            rows, err = await scrape_symbol(
                cdp, symbol, args.indicator, args.timeout, args.settle, args.min_rows
            )
            dt = time.monotonic() - t0

            if rows is None:
                fail += 1
                print(f"FAIL ({err}) [{dt:.1f}s]")
                # record a NO_DATA marker row so gaps are visible
                with open(out_csv, "a", newline="", encoding="utf-8") as f:
                    row = ([group, symbol, "NO_DATA"]
                           + [""] * (len(CSV_COLUMNS) - 4) + [str(err)])
                    csv.writer(f).writerow(row)
            else:
                n_sig = sum(
                    1 for c in rows
                    if ((c[0] if c else "") or "").strip() not in ("", "sig")
                )
                append_rows(out_csv, group, symbol, rows)
                ok += 1
                print(f"OK ({n_sig} signals) [{dt:.1f}s]")

            # checkpoint
            progress_path.write_text(json.dumps({
                "last_index": idx,
                "last_symbol": symbol,
                "ok": ok,
                "fail": fail,
                "updated": datetime.now().isoformat(timespec="seconds"),
                "out_csv": str(out_csv),
            }, indent=2), encoding="utf-8")

    print(f"\n[done] processed={ok+fail} ok={ok} fail={fail}")
    print(f"[done] CSV: {out_csv}")


def main():
    # Windows consoles may use a non-UTF-8 code page (e.g. cp1250); the scraped
    # table can contain non-ASCII glyphs (the infinity sign used for profit
    # factor when there are no losing trades), which would crash print().
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    ap = argparse.ArgumentParser(description="TradingView table scraper via CDP")
    ap.add_argument("--watchlist", required=True)
    ap.add_argument("--outdir", default="analysis")
    ap.add_argument("--tag", default="ETSB")
    ap.add_argument("--indicator", default="early trend strong breakout")
    ap.add_argument("--resolution", default=None,
                    help="chart interval to set before scraping (e.g. D, W, 60); "
                         "omit to leave the chart's current interval")
    ap.add_argument("--min-rows", type=int, default=5,
                    help="minimum table rows required to accept a symbol (default 5)")
    ap.add_argument("--limit", type=int, default=0, help="0 = all")
    ap.add_argument("--start", type=int, default=0, help="start index (resume)")
    ap.add_argument("--timeout", type=float, default=25.0, help="per-symbol timeout (s)")
    ap.add_argument("--settle", type=float, default=0.6, help="poll interval (s)")
    # TradingView Desktop / CDP
    ap.add_argument("--tv-port", type=int, default=DEFAULT_CDP_PORT,
                    help="CDP debugging port (default 9222)")
    ap.add_argument("--tv-path", default=None,
                    help="explicit path to TradingView.exe (needed for some "
                         "Store/MSIX installs)")
    ap.add_argument("--tv-autolaunch", action=argparse.BooleanOptionalAction,
                    default=True,
                    help="launch TradingView Desktop with CDP if not already "
                         "reachable (default: on)")
    ap.add_argument("--tv-kill-existing", action=argparse.BooleanOptionalAction,
                    default=True,
                    help="if TradingView is running without CDP, restart it "
                         "(default: on)")
    ap.add_argument("--tv-launch-wait", type=float, default=30.0,
                    help="seconds to wait for CDP after launching (default 30)")
    args = ap.parse_args()
    asyncio.run(main_async(args))


if __name__ == "__main__":
    main()
