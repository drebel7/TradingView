---
name: tv-table-scraper
description: Scrape a TradingView Pine indicator's on-chart table (e.g. "early trend strong breakout" performance/signals table) for every symbol in a watchlist file, and export to CSV for later aggregation. Use when the user wants batch stats/success-rate tables from TradingView Desktop for a list of tickers, or asks to summarize signal performance across a watchlist.
---

# TradingView Table Scraper

Batch-scrape a Pine Script indicator's `table.new` (the on-chart table, usually
top-right) for every symbol in a watchlist, and write a tidy CSV.

## When to use

- "Dla każdej spółki z pliku watchlist/... odczytaj tabelę wskaźnika ... i zapisz"
- Any request to gather an indicator's performance/signals table across many tickers.
- Producing a dataset to later compute cumulative / average success rate per signal.

## Prerequisites

- TradingView Desktop with CDP enabled on port **9222**. The script now takes
  care of this automatically: if CDP is not reachable it launches TradingView
  with `--remote-debugging-port`, and if TradingView is already running *without*
  CDP it restarts it. Nothing to start by hand.
- The target indicator already **added and visible** on the active chart.
- Python 3 with the `websockets` package (v16 uses
  `websockets.asyncio.client.connect`).

### Auto-launch (TradingView / CDP)

On startup the script ensures CDP is available, then waits for the chart page
and for the chart to finish loading before scraping. Behaviour:

| Situation | What the script does |
| --- | --- |
| CDP already open on the port | proceeds immediately |
| TradingView not running | finds the executable and launches it with CDP |
| TradingView running **without** CDP | force-quits and relaunches it with CDP |
| Store/MSIX install | resolves the path via `Get-AppxPackage` automatically |

Related flags: `--tv-port` (default 9222), `--tv-path` (explicit
`TradingView.exe`), `--tv-kill-existing` / `--no-tv-kill-existing` (default: on),
`--tv-launch-wait` (default 30 s), `--no-tv-autolaunch` (disable entirely).

## The script

`scripts/tv_table_scraper.py` — connects directly to the TradingView chart page
over CDP (same transport the `tradingview-desktop` MCP server uses) and, per symbol:

1. `window._exposed_chartWidgetCollection.setSymbol("<SYMBOL>")`
2. waits until `model().mainSeries().symbol()` matches AND the table is stable
   (two identical consecutive reads, and at least `--min-rows` rows)
3. reads Pine table cells from
   `study.graphics()._primitivesCollection.dwgtablecells.get('tableCells')._primitivesDataById`
   (each cell has `row`, `col`, `t`), groups by row/col
4. appends one CSV row per signal (incremental, crash-safe)

### Run

```powershell
python scripts\tv_table_scraper.py `
  --watchlist watchlist\GPW_NC.txt `
  --outdir analysis `
  --tag GPW_NC_ETSB `
  --indicator "early trend strong breakout" `
  --resolution D `
  --timeout 20 --settle 0.6
```

Useful flags:

| Flag | Meaning |
| --- | --- |
| `--resolution` | chart interval set once before scraping (`D`, `W`, `M`, `60`, `1`…). Omit to keep the chart's current interval. |
| `--min-rows` | minimum table rows required to accept a symbol (default `5`). Lower it for indicators with short tables. |
| `--limit N` | process only the first N symbols (smoke test). |
| `--start N` | resume from symbol index N. |
| `--timeout` | per-symbol seconds before giving up (`NO_DATA`). |
| `--settle` | poll interval in seconds. |
| `--tv-port` | CDP debugging port (default `9222`). |
| `--tv-path` | explicit path to `TradingView.exe` (rarely needed). |
| `--tv-kill-existing` / `--no-tv-kill-existing` | restart a running-but-CDP-less TradingView (default: on). |
| `--no-tv-autolaunch` | do not launch TradingView; require it to already be in CDP mode. |
| `--tv-launch-wait` | seconds to wait for CDP after launching (default 30). |

### Run on another list / another indicator

Only `--watchlist`, `--indicator`, `--tag` (and optionally `--resolution`) change:

```powershell
python scripts\tv_table_scraper.py `
  --watchlist watchlist\WIG20.txt `
  --outdir analysis `
  --tag WIG20_MYIND `
  --indicator "my indicator table name" `
  --resolution D `
  --min-rows 5 `
  --timeout 20 --settle 0.6
```

The indicator must already be added and visible on the chart; `--indicator`
is matched against the study name by prefix.

### Watchlist format

Comma-separated tokens, e.g. `###NEWCONNECT,GPW:AQU,GPW:BAC,...`. Group
separators start with `###` (e.g. `###NEWCONNECT`, `###GPW-BANKI`); the token
after a separator belongs to that group. Symbols look like `GPW:AQU`.

> Only comma-separated lists are parsed. A file with one symbol per line is
> **not** supported yet — convert it to comma-separated first (e.g.
> `(Get-Content list.txt) -join ','`).

## Output CSV

`analysis/<tag>_<YYYYMMDD>.csv`:

```
group,symbol,sig,succ,total,success_pct,avg_gain,score,raw
NEWCONNECT,GPW:AQU,et3sb,3,6,50.0,-2.5,0,50% (3/6) -2.5% 0
NEWCONNECT,GPW:AQU,et4sb,0,0,,,0,-
```

- `raw` mirrors the table cell: `x% (a/b) y% z`; `-` = signal never occurred
  (then `succ=0,total=0,success_pct=,avg_gain=,score=0`).
- A symbol that could not be read gets a `NO_DATA` row (reason in `raw`).

A progress checkpoint is written to `analysis/.<tag>_progress.json`.

## Aggregating later

Per signal (`sig`), across all symbols:

- cumulative success rate = `sum(succ) / sum(total)` over rows with `total > 0`
- average gain (weighted) = `sum(avg_gain * total) / sum(total)`
- score = `sum(score)` (or mean)
- occurrences = `sum(total)`, symbols covered = distinct `symbol` with `total>0`

## Notes / gotchas

- The script **must not** run concurrently with `tradingview-desktop` MCP chart
  tools (both drive the same chart). Let the scrape finish first.
- If TradingView is restarted to enable CDP, it restores the last layout
  automatically - make sure that layout still has the target indicator on it.
- It refuses to append to a CSV that it did not create (header-marker guard).
- If a symbol never loads, the per-symbol `--timeout` kicks in and a `NO_DATA`
  row is recorded; increase `--timeout` for slow feeds.
- The stability gate requires at least `--min-rows` rows; if an indicator's
  table is shorter, lower `--min-rows` (otherwise every symbol times out).
- The scraper reads only the first two table columns (`col 0` name, `col 1`
  value); multi-column tables are truncated to those two.
- Reusing for another indicator: change `--indicator` (matched by name prefix),
  `--tag`, and `--resolution`. Any indicator using `table.new` works.
