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

- TradingView Desktop running with CDP enabled on port **9222**
  (`tradingview-desktop_tv_launch` or launch with `--remote-debugging-port=9222`).
- The target indicator already **added and visible** on the active chart.
- Python 3 with the `websockets` package (v16 uses
  `websockets.asyncio.client.connect`).

## The script

`scripts/tv_table_scraper.py` — connects directly to the TradingView chart page
over CDP (same transport the `tradingview-desktop` MCP server uses) and, per symbol:

1. `window._exposed_chartWidgetCollection.setSymbol("<SYMBOL>")`
2. waits until `model().mainSeries().symbol()` matches AND the table is stable
   (two identical consecutive reads)
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
  --timeout 20 --settle 0.6
```

Useful flags: `--limit N` (first N, for a smoke test), `--start N` (resume),
`--timeout` (per-symbol seconds), `--settle` (poll interval).

### Watchlist format

Comma-separated tokens. Group separators start with `###` (e.g.
`###NEWCONNECT`, `###GPW-BANKI`); the token after a separator belongs to that
group. Symbols look like `GPW:AQU`.

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
- It refuses to append to a CSV that it did not create (header-marker guard).
- If a symbol never loads, the per-symbol `--timeout` kicks in and a `NO_DATA`
  row is recorded; increase `--timeout` for slow feeds.
- Reusing for another indicator: change `--indicator` (matched by name prefix)
  and `--tag`. Any indicator using `table.new` works.
