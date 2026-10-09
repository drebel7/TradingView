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
  4. appends one CSV row per signal

Output is appended incrementally, so an interrupted run keeps its data.
A progress file lets the run resume with --start / is written every symbol.

Usage
-----
  python tv_table_scraper.py \
      --watchlist watchlist/GPW_NC.txt \
      --outdir analysis \
      --tag GPW_NC_ETSB \
      --indicator "early trend strong breakout" \
      [--limit 10] [--start 0] [--timeout 25] [--settle 2]

The watchlist format: comma separated items; group separators start with "###".
"""

import argparse
import asyncio
import csv
import json
import re
import sys
import time
import urllib.request
from datetime import datetime
from pathlib import Path

try:
    from websockets.asyncio.client import connect
except Exception:  # pragma: no cover - fallback for older websockets
    from websockets import connect  # type: ignore

CDP_HTTP = "http://127.0.0.1:9222/json"


# ----------------------------------------------------------------------------
# CDP helpers
# ----------------------------------------------------------------------------
def find_chart_ws_url():
    """Return the CDP WebSocket debugger URL of the TradingView chart page."""
    with urllib.request.urlopen(CDP_HTTP, timeout=10) as resp:
        targets = json.loads(resp.read().decode("utf-8"))
    for t in targets:
        if t.get("type") == "page" and "tradingview.com/chart/" in (t.get("url") or ""):
            return t["webSocketDebuggerUrl"]
    # fallback: any tradingview.com page
    for t in targets:
        if t.get("type") == "page" and "tradingview.com" in (t.get("url") or ""):
            return t["webSocketDebuggerUrl"]
    raise RuntimeError("TradingView chart page not found on CDP port 9222")


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
        rows = Object.keys(rm).sort(function(a,b){return a-b;}).map(function(r){var cc=rm[r];return [cc[0]||'',cc[1]||''];}); 
      }
    }catch(e){}
    return JSON.stringify({symbol:sym, statusType:statusType, ready:true, rows:rows});
  }catch(e){ return JSON.stringify({symbol:null, ready:false, err:String(e)}); }
})()
"""


def js_set_symbol(symbol):
    return "window._exposed_chartWidgetCollection.setSymbol(%s)" % json.dumps(symbol)


# ----------------------------------------------------------------------------
# Parsing
# ----------------------------------------------------------------------------
PERF_RE = re.compile(
    r"^\s*([\d.]+)%\s*\((\d+)\s*/\s*(\d+)\)\s+([+-]?[\d.]+)%\s+(-?\d+)\s*$"
)


def parse_perf(text):
    """Parse 'x% (a/b) y% z' -> dict, or None for '-' / unparseable."""
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
        "score": int(m.group(5)),
    }


# ----------------------------------------------------------------------------
# Watchlist
# ----------------------------------------------------------------------------
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
async def scrape_symbol(cdp, symbol, indicator, timeout, settle_interval):
    """Switch to symbol and return parsed table rows (list of [sig, perf])."""
    # switch symbol
    try:
        await cdp.evaluate(js_set_symbol(symbol))
    except Exception as e:
        return None, f"setSymbol error: {e}"

    deadline = time.monotonic() + timeout
    prev_key = None
    stable = 0
    last_state = None

    while time.monotonic() < deadline:
        try:
            raw = await cdp.evaluate(JS_READ_STATE.replace("__INDICATOR__", indicator))
            state = json.loads(raw)
        except Exception as e:
            await asyncio.sleep(0.4)
            continue

        last_state = state
        if state.get("symbol") == symbol and state.get("ready"):
            rows = state.get("rows") or []
            if len(rows) >= 20:
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


HEADER_MARKER = "# TradingView table scraper results"


def write_csv_header(path, indicator, watchlist):
    if path.exists() and path.stat().st_size > 0:
        # Refuse to append to a file that was not produced by this scraper.
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            first = f.readline().strip()
        if first != HEADER_MARKER:
            raise SystemExit(
                f"ERROR: {path} exists but is not a scraper output file "
                f"(first line: {first!r}). Remove or rename it and retry."
            )
        return
    with open(path, "w", newline="", encoding="utf-8") as f:
        f.write("# TradingView table scraper results\n")
        f.write(f"# indicator: {indicator}\n")
        f.write(f"# watchlist: {watchlist}\n")
        f.write(f"# generated: {datetime.now().isoformat(timespec='seconds')}\n")
        f.write("# columns: group,symbol,sig,succ,total,success_pct,avg_gain,score,raw\n")
        f.write("# 'raw' = '-' means the signal did not occur for that symbol\n")
        w = csv.writer(f)
        w.writerow(["group", "symbol", "sig", "succ", "total",
                    "success_pct", "avg_gain", "score", "raw"])


def append_rows(path, group, symbol, rows):
    with open(path, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        for sig, perf in rows:
            sig = (sig or "").strip()
            if sig in ("", "sig"):
                continue  # skip empty / header rows
            p = parse_perf(perf)
            if p is None:
                w.writerow([group, symbol, sig, 0, 0, "", "", 0, (perf or "-")])
            else:
                w.writerow([group, symbol, sig, p["succ"], p["total"],
                            p["success_pct"], p["avg_gain"], p["score"], perf])


async def main_async(args):
    ws_url = find_chart_ws_url()
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
        for idx in range(start, end):
            group, symbol = symbols[idx]
            label = f"[{idx+1}/{total}] {symbol} ({group})"
            sys.stdout.write(label + " ... ")
            sys.stdout.flush()

            t0 = time.monotonic()
            rows, err = await scrape_symbol(
                cdp, symbol, args.indicator, args.timeout, args.settle
            )
            dt = time.monotonic() - t0

            if rows is None:
                fail += 1
                print(f"FAIL ({err}) [{dt:.1f}s]")
                # record a NO_DATA marker row so gaps are visible
                with open(out_csv, "a", newline="", encoding="utf-8") as f:
                    csv.writer(f).writerow([group, symbol, "NO_DATA", "", "", "", "", "", str(err)])
            else:
                n_sig = sum(1 for s, _ in rows if (s or "").strip() not in ("", "sig"))
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
    ap = argparse.ArgumentParser(description="TradingView table scraper via CDP")
    ap.add_argument("--watchlist", required=True)
    ap.add_argument("--outdir", default="analysis")
    ap.add_argument("--tag", default="ETSB")
    ap.add_argument("--indicator", default="early trend strong breakout")
    ap.add_argument("--limit", type=int, default=0, help="0 = all")
    ap.add_argument("--start", type=int, default=0, help="start index (resume)")
    ap.add_argument("--timeout", type=float, default=25.0, help="per-symbol timeout (s)")
    ap.add_argument("--settle", type=float, default=0.6, help="poll interval (s)")
    args = ap.parse_args()
    asyncio.run(main_async(args))


if __name__ == "__main__":
    main()
