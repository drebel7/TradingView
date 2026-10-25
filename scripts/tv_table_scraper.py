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
     (every column; multi-column tables are captured in full)
  4. appends one CSV row per signal, with the metrics
     (win_pct, n, avg_r, pf, max_dd, score, sum_win_r, sum_loss_r) plus the
     raw row. A legacy leading perf column ("x% (a/b) y%"), if present, is
     detected from the header and skipped so the metrics stay aligned, but is
     no longer exported.

On startup (unless --no-solo-visibility) it also hides every study on the chart
except the scraped indicator, so Pine tables from other indicators do not
overlap the one being read. The scraped indicator must already be added.

Right after that it also prepares the indicator's inputs (unless
--no-set-input-defaults): every script input is reset to its script default
(best effort), and the table-related booleans are forced so the performance
table is complete and shows all signals - "show table" ON, "show only good
sigs." OFF and "use extended quality gate" OFF. The study is then given time to
recompute before the first symbol is scraped.

If TradingView Desktop is not reachable over CDP, the script launches it with
--remote-debugging-port (restarting it first if it is running without CDP), then
waits for the chart page. This is cross-platform: the executable is located
automatically on Windows (incl. Store/MSIX), macOS and Linux (native, snap or
flatpak). Use --no-tv-autolaunch to disable, --tv-path to point at a specific
executable, --tv-kill-existing / --no-tv-kill-existing to control restarting.

Output is appended incrementally, so an interrupted run keeps its data.
A progress file lets the run resume with --start / is written every symbol.

Usage
-----
  python tv_table_scraper.py \
      --watchlist watchlist/.PL.txt \
      --outdir analysis \
      --tag PL_ETSB \
      --indicator "early trend strong breakout" \
      [--resolution D] [--min-rows 5] \
      [--limit 10] [--start 0] [--timeout 25] [--settle 0.6] \
      [--retries 2] [--no-set-input-defaults] \
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
import shutil
import signal
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

# TradingView Desktop executable names on POSIX (native installs).
TV_EXE_NAMES_POSIX = ("tradingview", "TradingView")
# macOS app-bundle executable, anchored on the path so an unrelated command
# line that merely contains "TradingView" can never match.
MAC_TV_PATTERN = r"TradingView\.app/Contents/MacOS/TradingView"


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


def _linux_tv_pids():
    """Return the PIDs whose *executable* is TradingView Desktop (Linux /proc).

    Matching the resolved executable rather than the whole command line means a
    process that merely mentions "TradingView" in its arguments - e.g. this very
    script when it is invoked with an absolute path such as
    .../TradingView/scripts/tv_table_scraper.py - is never selected (and can
    therefore never be killed).
    """
    pids = []
    self_pid = os.getpid()
    try:
        entries = os.listdir("/proc")
    except OSError:
        return pids
    for entry in entries:
        if not entry.isdigit():
            continue
        pid = int(entry)
        if pid == self_pid:
            continue
        try:
            with open(f"/proc/{pid}/cmdline", "rb") as fh:
                argv0 = fh.read().split(b"\0", 1)[0].decode("utf-8", "replace")
        except OSError:
            continue
        if not argv0:
            continue
        base = os.path.basename(argv0)
        # Electron helper processes (renderer/GPU/zygote) report
        # "/proc/self/exe" as argv[0]; resolve the real binary so they match too.
        if base.lower() in ("exe", "self.exe"):
            try:
                base = os.path.basename(os.readlink(f"/proc/{pid}/exe"))
            except OSError:
                continue
        if base in TV_EXE_NAMES_POSIX:
            pids.append(pid)
    return pids


def is_tv_running():
    """True if a TradingView Desktop process is running (any platform).

    Never matches merely because "TradingView" appears in some command line -
    only the actual TradingView executable counts (see _linux_tv_pids).
    """
    system = platform.system()
    try:
        if system == "Windows":
            out = subprocess.run(
                ["tasklist", "/FI", "IMAGENAME eq TradingView.exe", "/NH"],
                capture_output=True, text=True, timeout=10,
            ).stdout
            return "TradingView.exe" in out
        if system == "Linux":
            return bool(_linux_tv_pids())
        # macOS / other POSIX: anchor on the app-bundle executable so unrelated
        # command lines cannot match.
        out = subprocess.run(
            ["pgrep", "-f", MAC_TV_PATTERN],
            capture_output=True, text=True, timeout=10,
        )
        return out.returncode == 0
    except Exception:
        return False


def kill_tv(graceful_wait=4.0):
    """Force-quit any running TradingView Desktop instance.

    On Linux only processes whose executable *is* TradingView are killed, never
    this script or anything that merely mentions the name in its arguments.
    """
    system = platform.system()
    try:
        if system == "Windows":
            subprocess.run(["taskkill", "/IM", "TradingView.exe", "/F"],
                           capture_output=True, text=True, timeout=15)
            return
        if system == "Linux":
            self_pid = os.getpid()
            for pid in _linux_tv_pids():
                if pid == self_pid:
                    continue
                try:
                    os.kill(pid, signal.SIGTERM)
                except OSError:
                    pass
            deadline = time.monotonic() + graceful_wait
            while time.monotonic() < deadline:
                if not _linux_tv_pids():
                    return
                time.sleep(0.2)
            for pid in _linux_tv_pids():
                if pid == self_pid:
                    continue
                try:
                    os.kill(pid, signal.SIGKILL)
                except OSError:
                    pass
            return
        subprocess.run(["pkill", "-f", MAC_TV_PATTERN],
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
    """Best-effort locate the TradingView Desktop executable (native installs)."""
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
        # Linux and other POSIX: PATH first, then the common install locations.
        for name in TV_EXE_NAMES_POSIX:
            found = shutil.which(name)
            if found:
                candidates.append(found)
        candidates += [
            "/opt/TradingView/tradingview",
            "/usr/bin/tradingview",
            "/usr/local/bin/tradingview",
            "/snap/bin/tradingview",
            os.path.expanduser("~/.local/bin/tradingview"),
        ]
    for c in candidates:
        if c and os.path.isfile(c):
            return c
    return None


def find_tv_launcher(exe_path=None):
    """Return (argv_prefix, kind) able to start TradingView Desktop.

    The caller appends --remote-debugging-port=<port> to argv_prefix. `kind` is
    one of: windows, mac, linux, flatpak, snap. Returns (None, None) when no
    launcher could be found (caller then asks the user for --tv-path).
    """
    system = platform.system()
    if system == "Darwin":
        # `open -a TradingView` works without knowing the bundle path; an
        # explicitly supplied --tv-path is launched directly instead.
        if exe_path:
            return [exe_path], "mac"
        return ["open", "-a", "TradingView", "--args"], "mac"
    exe = exe_path or find_tv_executable()
    if system == "Windows":
        return ([exe], "windows") if exe else (None, None)
    # Linux / other POSIX
    if exe:
        return [exe], "linux"
    # Sandboxed POSIX packages (no native binary on PATH).
    if shutil.which("flatpak"):
        return ["flatpak", "run", "com.tradingview.Desktop"], "flatpak"
    if shutil.which("snap"):
        return ["snap", "run", "tradingview"], "snap"
    return None, None


def launch_tv(argv_prefix, port):
    """Launch TradingView Desktop with the CDP debugging port enabled."""
    system = platform.system()
    cmd = list(argv_prefix) + [f"--remote-debugging-port={port}"]
    try:
        if system == "Windows":
            # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP: survives this script.
            flags = 0x00000008 | 0x00000200
            subprocess.Popen(cmd, creationflags=flags, close_fds=True)
        else:
            # start_new_session detaches it from this process group on POSIX, so
            # the editor keeps running (and keeps CDP) after the scrape.
            subprocess.Popen(cmd, start_new_session=True)
    except Exception as e:
        raise RuntimeError(
            f"Failed to launch TradingView ({' '.join(cmd)}): {e}. "
            f"Pass --tv-path with the full path to the executable."
        )
    return cmd


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

    argv_prefix, kind = find_tv_launcher(exe_path)
    if not argv_prefix:
        raise RuntimeError(
            "TradingView Desktop executable not found. Pass --tv-path with the "
            "full path to the TradingView binary/executable."
        )
    cmd = list(argv_prefix) + [f"--remote-debugging-port={port}"]
    print(f"[i] launching ({kind}): {' '.join(cmd)}")
    launch_tv(argv_prefix, port)

    deadline = time.monotonic() + launch_wait
    while time.monotonic() < deadline:
        if cdp_available(port):
            print(f"[i] TradingView CDP is up on port {port}")
            return True
        time.sleep(1)
    raise RuntimeError(
        f"TradingView was launched but CDP port {port} did not open within "
        f"{launch_wait:.0f}s. For a Store/MSIX/sandboxed install, pass --tv-path."
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

    async def evaluate(self, expression, await_promise=False, timeout=20.0):
        """Evaluate JS over CDP, bounded by `timeout` seconds.

        A stalled/blocked CDP websocket would otherwise block in recv() forever
        (the per-symbol timeout cannot fire while blocked inside an await), which
        hangs the whole scrape. Bounding each send/recv turns such a stall into a
        per-call timeout the scrape loop can recover from.
        """
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
        await asyncio.wait_for(self.ws.send(json.dumps(msg)), timeout=timeout)
        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError(
                    f"CDP evaluate timed out after {timeout}s (stalled websocket)")
            try:
                raw = await asyncio.wait_for(self.ws.recv(), timeout=remaining)
            except asyncio.TimeoutError:
                raise TimeoutError(
                    f"CDP evaluate timed out after {timeout}s (stalled websocket)")
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


# Detect and click the "Connect" button that appears when TradingView is running
# but the user is not logged in (e.g. logged in on another machine).
# The button is inside a dialog/modal overlay; we look for text "Connect" and
# click the nearest clickable ancestor.
JS_CLICK_CONNECT = r"""
(function(){
  try{
    var btns = document.querySelectorAll('button, [role="button"], .Button, [class*="connect"], [class*="Connect"]');
    for(var i=0;i<btns.length;i++){
      var b = btns[i];
      var text = (b.textContent || b.innerText || '').trim();
      if(text.indexOf('Connect') === 0 || text === 'connect') {
        b.click();
        return JSON.stringify({ok:true, found:true, text:text});
      }
    }
    // Also try aria-label / title
    var els = document.querySelectorAll('[aria-label*="Connect"], [title*="Connect"]');
    for(var j=0;j<els.length;j++){ els[j].click(); return JSON.stringify({ok:true, found:true, text:els[j].getAttribute('aria-label')||els[j].getAttribute('title')}); }
    return JSON.stringify({ok:true, found:false});
  }catch(e){ return JSON.stringify({ok:false, err:String(e)}); }
})()
"""


# Hide every study except the one whose name starts with __INDICATOR__, so only
# the scraped indicator's Pine table is on the chart (overlapping tables from
# other studies would otherwise break the cell read / clutter the view).
JS_SET_VISIBILITY = r"""
(function(){
  try{
    var c = window._exposed_chartWidgetCollection;
    if(!c) return JSON.stringify({ok:false, err:'no chartWidgetCollection'});
    var w = c.activeChartWidget; if(w && w._value!==undefined) w=w._value;
    var ds = w.model().dataSources();
    var target = "__INDICATOR__";
    var shown = [], hiddenN = 0, errs = 0, matched = false;
    for(var i=0;i<ds.length;i++){
      try{
        var d = ds[i];
        if(!d || typeof d.name!=='function') continue;
        var nm = d.name() || '';
        if(!nm) continue;
        var props = null; try{ props = d.properties(); }catch(e){ props = null; }
        if(!props || !props.visible || typeof props.visible.setValue!=='function') continue;
        var want = nm.indexOf(target)===0;
        props.visible.setValue(want);
        if(want){ shown.push(nm); matched = true; } else { hiddenN++; }
      }catch(e){ errs++; }
    }
    return JSON.stringify({ok:true, matched:matched, shown:shown, hidden:hiddenN, errs:errs});
  }catch(e){ return JSON.stringify({ok:false, err:String(e)}); }
})()
"""


# Inputs that must be forced on the scraped indicator so its performance table
# is complete and every signal row is present:
#   "show table"                    -> ON   (the table must be visible)
#   "show only good sigs."          -> OFF  (keep all signals, not just the good ones)
#   "use extended quality gate"     -> OFF  (do not filter signals out)
# Keys are normalized input titles: lowercase, collapsed spaces, no trailing dot.
INPUT_OVERRIDES = {
    "show table": True,
    "show only good sigs": False,
    "use extended quality gate": False,
}


# Set the scraped study's inputs in one pass: optionally reset every script
# input to its script default (best effort), then apply the forced overrides
# above (matched by normalized title). Only inputs whose id starts with "in_"
# are touched, so pineId/pineVersion/pineFeatures and the encoded source are
# left alone. Values are applied through the study's properties API
# (study._properties.childs().inputs.child(id).setValue), which is what the
# TradingView settings dialog uses, so the study recomputes automatically.
JS_SET_INPUTS = r"""
(function(){
  try{
    var c = window._exposed_chartWidgetCollection;
    if(!c) return JSON.stringify({ok:false, err:'no chartWidgetCollection'});
    var w = c.activeChartWidget; if(w && w._value!==undefined) w=w._value;
    var ds = w.model().dataSources();
    var target = "__INDICATOR__";
    var study=null;
    for(var i=0;i<ds.length;i++){
      try{ var nm=(ds[i].name&&ds[i].name())||''; if(nm.indexOf(target)===0){study=ds[i];break;} }catch(e){}
    }
    if(!study) return JSON.stringify({ok:false, err:'target study not found'});
    var mi = study.metaInfo && study.metaInfo();
    if(!mi || !mi.inputs) return JSON.stringify({ok:false, err:'no metaInfo inputs'});
    var propsRoot = study._properties && study._properties.childs && study._properties.childs().inputs;
    if(!propsRoot) return JSON.stringify({ok:false, err:'no properties.inputs'});

    var overrides = __OVERRIDES__;
    var reset = __RESET__;
    var safeTypes = {bool:1, integer:1, float:1, text:1};
    var applied = [], skipped = [], overrideN = 0;

    function norm(s){
      return String(s==null?'':s).toLowerCase().replace(/\s+/g,' ').replace(/[.\s]+$/,'').trim();
    }

    for(var j=0;j<mi.inputs.length;j++){
      var inp = mi.inputs[j];
      var id = inp.id || '';
      if(id.indexOf('in_') !== 0) continue;   // skip pineId/pineVersion/pineFeatures/ILScript
      var val, isOverride = false;
      var nname = norm(inp.name);
      if(Object.prototype.hasOwnProperty.call(overrides, nname)){
        val = overrides[nname]; isOverride = true;
      } else if(reset && inp.defval !== undefined && safeTypes[inp.type]){
        val = inp.defval;
      } else {
        continue;
      }
      var prop = null;
      try{ prop = propsRoot.child(id); }catch(e){ prop = null; }
      if(!prop || typeof prop.setValue !== 'function'){ skipped.push(id); continue; }
      try{
        prop.setValue(val);
        if(isOverride) overrideN++;
        applied.push(id);
      }catch(e){ skipped.push(id + ':' + e); }
    }
    return JSON.stringify({ok:true, study:(study.name&&study.name())||'',
                           applied:applied.length, overrides:overrideN,
                           skipped:skipped.length});
  }catch(e){ return JSON.stringify({ok:false, err:String(e)}); }
})()
"""


# Cheap signature of the target study's table (cell count), used to wait until
# the study finished recomputing after its inputs were changed.
JS_TABLE_SIG = r"""
(function(){
  try{
    var c = window._exposed_chartWidgetCollection;
    if(!c) return JSON.stringify({ready:false});
    var w = c.activeChartWidget; if(w && w._value!==undefined) w=w._value;
    var ds = w.model().dataSources();
    var target = "__INDICATOR__";
    var study=null;
    for(var i=0;i<ds.length;i++){
      try{ var nm=(ds[i].name&&ds[i].name())||''; if(nm.indexOf(target)===0){study=ds[i];break;} }catch(e){}
    }
    if(!study) return JSON.stringify({ready:false});
    var cells=0;
    try{
      var tc = study.graphics()._primitivesCollection.dwgtablecells.get('tableCells');
      if(tc) cells = tc._primitivesDataById.size;
    }catch(e){}
    return JSON.stringify({ready:true, cells:cells});
  }catch(e){ return JSON.stringify({ready:false, err:String(e)}); }
})()
"""


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


async def show_only_indicator(cdp, indicator):
    """Hide every study on the chart except the scraped one.

    Keeps only the study whose name starts with `indicator` visible, so Pine
    tables drawn by other studies do not overlap the one being scraped.
    Returns the parsed JS result (dict), never raises.
    """
    try:
        raw = await cdp.evaluate(JS_SET_VISIBILITY.replace("__INDICATOR__", indicator))
        return json.loads(raw)
    except Exception as e:
        return {"ok": False, "err": str(e)}


async def configure_inputs(cdp, indicator, reset_defaults=True, overrides=None):
    """Set the scraped indicator's inputs before scraping.

    Resets every script input to its default (best effort) when
    `reset_defaults` is set, then applies `overrides` (matched by normalized
    input title) so the performance table is complete: "show table" on,
    "show only good sigs." and "use extended quality gate" off. Returns the
    parsed JS result (dict), never raises.
    """
    if overrides is None:
        overrides = INPUT_OVERRIDES
    expr = (JS_SET_INPUTS
            .replace("__INDICATOR__", indicator)
            .replace("__OVERRIDES__", json.dumps(overrides))
            .replace("__RESET__", "true" if reset_defaults else "false"))
    try:
        return json.loads(await cdp.evaluate(expr))
    except Exception as e:
        return {"ok": False, "err": str(e)}


async def wait_inputs_applied(cdp, indicator, timeout=20.0, settle=0.6, consecutive=2):
    """Wait until the target study's table stops changing after an input change.

    Changing an input restarts the study, so the table briefly disappears and
    is redrawn. Polling the table cell count until it is stable ensures the
    first symbol is not scraped mid-recompute.
    """
    deadline = time.monotonic() + timeout
    prev = None
    stable = 0
    while time.monotonic() < deadline:
        try:
            sig = await cdp.evaluate(JS_TABLE_SIG.replace("__INDICATOR__", indicator))
        except Exception:
            sig = None
        if sig is not None and sig == prev:
            stable += 1
            if stable >= consecutive:
                return True
        else:
            stable = 0
            prev = sig
        await asyncio.sleep(settle)
    return False


async def click_connect_button(cdp, max_attempts=5, interval=1.0):
    """Detect and click the "Connect" button if TradingView is not logged in.

    The button appears in a dialog overlay when the user is logged in on
    another machine. Returns True if the button was found and clicked,
    False otherwise.
    """
    for attempt in range(1, max_attempts + 1):
        try:
            raw = await cdp.evaluate(JS_CLICK_CONNECT)
            result = json.loads(raw)
            if result.get("ok") and result.get("found"):
                print(f"[i] Connect button clicked (attempt {attempt}): {result.get('text', '')}")
                # Wait a moment for the login dialog to process
                await asyncio.sleep(2)
                return True
        except Exception as e:
            print(f"[warn] connect button check attempt {attempt}: {e}")
        await asyncio.sleep(interval)
    return False


# ----------------------------------------------------------------------------
# Parsing
# ----------------------------------------------------------------------------
# Extended metric columns of the ETSB table, in order, following the signal
# name column:
#   win%   N   avgR   PF   maxDD   score   gross win R   gross loss R   avgRet%
# Legacy tables (e.g. ridingVwapOptimizer) insert a "perf" column
# ("x% (a/b) y%") right after the signal name; it is detected from the header
# and skipped so the metrics still line up. It is no longer exported.
# avg_ret_pct is the optional trailing average return per trade [%]; older
# tables that do not render it simply leave the column blank.
EXT_METRIC_NAMES = [
    "win_pct", "n", "avg_r", "pf", "max_dd", "score", "sum_win_r", "sum_loss_r",
    "avg_ret_pct",
]

# Full CSV schema.
CSV_COLUMNS = ["group", "symbol", "sig"] + EXT_METRIC_NAMES + ["raw"]


def detect_metric_base(rows):
    """Return the column index of the first extended metric for a table.

    Legacy tables carry a perf column at index 1 (its header cell starts with
    "perf"), so the metrics start at index 2; tables without it (e.g. the
    current ETSB layout) start at index 1.
    """
    for cells in rows:
        if len(cells) > 1 and str(cells[1] or "").strip().lower().startswith("perf"):
            return 2
    return 1


def parse_metric(text):
    """Parse a numeric table cell to float, or None for ''/'-'/unparseable.

    Thousands separators (commas) are ignored; decimal separator is a dot.
    """
    text = (text or "").strip()
    if text in ("", "-"):
        return None
    try:
        return float(text.replace(",", ""))
    except ValueError:
        return None


def is_header_row(cells):
    """True for a table's header row.

    Detected either by a 'sig' label in the first cell (ETSB/PT/WS) or by the
    performance header in the second cell (e.g. the optimizer's 'low: v(OVCFR)' /
    'perf 41 0.4' row), so no bogus signal row is written.
    """
    if not cells:
        return True
    sig = (cells[0] or "").strip()
    if sig in ("", "sig"):
        return True
    if len(cells) > 1 and str(cells[1] or "").strip().lower().startswith("perf"):
        return True
    return False


def row_to_record(cells, base):
    """Map a raw table row (list of cell strings) to a metric record.

    The first column is the signal name; `base` is the index of the first
    extended metric (see detect_metric_base), so a legacy perf column between
    them is skipped. The signal count (`n`) gates the row: a signal that never
    occurred has n=0, so every metric is left blank. The full row is always
    preserved in 'raw'.
    """
    cells = [("" if c is None else str(c)) for c in cells]
    rec = {c: "" for c in CSV_COLUMNS}
    rec["sig"] = (cells[0].strip() if cells else "")
    rec["raw"] = " | ".join(cells)
    n_idx = base + EXT_METRIC_NAMES.index("n")
    n_val = parse_metric(cells[n_idx] if len(cells) > n_idx else "")
    if n_val is None or n_val <= 0:
        return rec
    for i, name in enumerate(EXT_METRIC_NAMES):
        idx = base + i
        val = parse_metric(cells[idx] if len(cells) > idx else "")
        if val is None:
            continue
        rec[name] = int(val) if name == "n" else val
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


async def scrape_symbol(cdp, symbol, indicator, timeout, settle_interval, min_rows,
                        stable_on=None, accept=None):
    """Switch to symbol and return the raw table rows (list of cell lists).

    setSymbol is re-issued (every ~2s) while the chart still shows another
    symbol - this handles the race right after a fresh TradingView launch where
    the chart is still loading and would otherwise ignore the request.

    `stable_on` - opcjonalna funkcja (rows) -> wartość porównywalna, używana do
    oceny stabilności tabeli. Domyślnie porównywane są całe wiersze; dla tabel
    z danymi zmieniającymi się w czasie (np. DRE Info: HoD/LoD price) można
    porównywać tylko strukturę, np. kolumnę etykiet.

    `accept` - opcjonalny predykat (rows) -> bool. Wiersze są brane pod uwagę
    tylko, gdy zwróci True. Chroni to przed tabelą, która nie zdążyła się
    przerysować po zmianie symbolu (np. DRE Info nadal pokazuje poprzednią
    spółkę - mimo że wykres ma już nowy symbol).
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
            if len(rows) >= min_rows and (accept is None or accept(rows)):
                key = json.dumps(stable_on(rows) if stable_on else rows)
                if key == prev_key:
                    stable += 1
                else:
                    stable = 0
                    prev_key = key
                if stable >= 1:  # two consecutive identical reads
                    return rows, None
        await asyncio.sleep(settle_interval)

    return None, f"timeout (last={last_state})"


HEADER_MARKER = "# TradingView table scraper results v3"


def write_csv_header(path, indicator, watchlist):
    if path.exists() and path.stat().st_size > 0:
        # Refuse to append to a file that was not produced by this scraper
        # (schema v3 - older files with the perf-derived columns fail here).
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
        f.write("# metrics: win_pct, n, avg_r, pf, max_dd, score, sum_win_r, sum_loss_r, avg_ret_pct "
                "(blank when the signal did not occur)\n")
        f.write("# a legacy leading 'perf' column ('x% (a/b) y%'), if present, is skipped\n")
        f.write("# pf is shown as the infinity sign and left blank here when there are no losing trades\n")
        w = csv.writer(f)
        w.writerow(CSV_COLUMNS)


def append_rows(path, group, symbol, rows):
    base = detect_metric_base(rows)
    with open(path, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        for cells in rows:
            if is_header_row(cells):
                continue
            rec = row_to_record(cells, base)
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
    failed_symbols = []  # list of (idx, group, symbol) for retry

    async with connect(ws_url, max_size=None, open_timeout=15) as ws:
        cdp = CDP(ws)
        if not await wait_chart_ready(cdp, timeout=90):
            print("[warn] chart did not report ready within 90s - continuing anyway")

        # If TradingView is not logged in, there will be a "Connect" button
        # that blocks chart interaction. Detect and click it.
        await click_connect_button(cdp)

        if args.resolution:
            ok_res = await set_resolution(cdp, args.resolution)
            print(f"[i] resolution set to '{args.resolution}': {ok_res}")
        if args.solo_visibility:
            vis = await show_only_indicator(cdp, args.indicator)
            if vis.get("ok"):
                shown = ", ".join(vis.get("shown") or []) or "-"
                print(f"[i] solo visibility: showing [{shown}], hid {vis.get('hidden')} other studies")
                if not vis.get("matched"):
                    print("[warn] target indicator not found on chart - it must be added and visible")
            else:
                print(f"[warn] solo visibility failed: {vis.get('err')}")

        # Ensure the scraped indicator's inputs are set for a complete table:
        # reset to script defaults (best effort) and force the table-related
        # booleans (show table on; show only good sigs. / extended quality gate
        # off), then wait for the study to finish recomputing.
        cfg = await configure_inputs(cdp, args.indicator, args.set_input_defaults)
        if cfg.get("ok"):
            print(f"[i] inputs: applied {cfg.get('applied')} "
                  f"({cfg.get('overrides')} forced), skipped {cfg.get('skipped')}")
            if not await wait_inputs_applied(cdp, args.indicator):
                print("[warn] study did not settle after input change - continuing anyway")
        else:
            print(f"[warn] input setup failed: {cfg.get('err')}")

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
                failed_symbols.append((idx, group, symbol, err))
                print(f"FAIL ({err}) [{dt:.1f}s]")
                # record a NO_DATA marker row so gaps are visible
                with open(out_csv, "a", newline="", encoding="utf-8") as f:
                    row = ([group, symbol, "NO_DATA"]
                           + [""] * (len(CSV_COLUMNS) - 4) + [str(err)])
                    csv.writer(f).writerow(row)
            else:
                n_sig = sum(1 for c in rows if not is_header_row(c))
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

        # ── Retry pass for failed symbols ──────────────────────────────────
        if failed_symbols and args.retries > 0:
            for retry in range(1, args.retries + 1):
                if not failed_symbols:
                    break
                print(f"\n[i] retry pass {retry}/{args.retries} — {len(failed_symbols)} failures to retry")
                still_failed = []
                for idx, group, symbol, err in failed_symbols:
                    label = f"[retry:{retry}] {symbol} ({group})"
                    sys.stdout.write(label + " ... ")
                    sys.stdout.flush()

                    t0 = time.monotonic()
                    rows, err = await scrape_symbol(
                        cdp, symbol, args.indicator, args.timeout, args.settle, args.min_rows
                    )
                    dt = time.monotonic() - t0

                    if rows is None:
                        still_failed.append((idx, group, symbol, err))
                        print(f"FAIL ({err}) [{dt:.1f}s]")
                    else:
                        # Remove the NO_DATA row written earlier and write real data
                        n_sig = sum(1 for c in rows if not is_header_row(c))
                        append_rows(out_csv, group, symbol, rows)
                        ok += 1
                        fail -= 1  # no longer a failure
                        print(f"OK ({n_sig} signals) [{dt:.1f}s]")

                failed_symbols = still_failed
                if not failed_symbols:
                    print("[i] all retries successful")
                    break

            # Final checkpoint
            progress_path.write_text(json.dumps({
                "last_index": end - 1 if end > start else start,
                "last_symbol": symbols[-1][1] if symbols else "",
                "ok": ok,
                "fail": fail,
                "retries_used": args.retries if failed_symbols else min(args.retries, 1),
                "updated": datetime.now().isoformat(timespec="seconds"),
                "out_csv": str(out_csv),
            }, indent=2), encoding="utf-8")

    print(f"\n[done] processed={ok+fail} ok={ok} fail={fail}")
    if failed_symbols:
        print(f"[done] {len(failed_symbols)} symbols still failed:")
        for _, group, symbol, err in failed_symbols:
            print(f"    {group}:{symbol} — {err}")
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
    ap.add_argument("--solo-visibility", action=argparse.BooleanOptionalAction,
                    default=True,
                    help="on startup hide every study on the chart except the one "
                         "being scraped (default: on) so overlapping Pine tables "
                         "from other indicators do not interfere")
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
                    help="explicit path to the TradingView Desktop executable "
                         "(needed for some Store/MSIX or sandboxed installs)")
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
    ap.add_argument("--retries", type=int, default=1,
                    help="number of retry passes for failed symbols (default 1)")
    ap.add_argument("--set-input-defaults", action=argparse.BooleanOptionalAction,
                    default=True,
                    help="reset the scraped indicator's inputs to their script "
                         "defaults before scraping (default: on); the table-related "
                         "inputs (show table on; show only good sigs. / extended "
                         "quality gate off) are always forced afterwards")
    args = ap.parse_args()
    asyncio.run(main_async(args))


if __name__ == "__main__":
    main()
