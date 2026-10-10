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

1. **hides every study except the scraped one** (see `--solo-visibility`), so
   Pine tables from other indicators do not overlap the one being read
2. `window._exposed_chartWidgetCollection.setSymbol("<SYMBOL>")`
3. waits until `model().mainSeries().symbol()` matches AND the table is stable
   (two identical consecutive reads, and at least `--min-rows` rows)
4. reads Pine table cells from
   `study.graphics()._primitivesCollection.dwgtablecells.get('tableCells')._primitivesDataById`
   (each cell has `row`, `col`, `t`), groups by row/col and keeps **all** columns
5. appends one CSV row per signal: col 1 (the perf string `x% (a/b) y%`) is split
   into `succ/total/success_pct/avg_gain`, and the extended metric columns
   (win%, N, avgR, PF, maxDD, score, winR, lossR) go to their own fields
   (incremental, crash-safe)

> The scraped indicator must already be added to the chart **and visible** (step 1
> leaves it visible), with its performance table enabled. If the study is hidden
> the table primitives are not drawn and every symbol times out with `rows: []`.

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
| `--solo-visibility` / `--no-solo-visibility` | on startup hide every study except the scraped one (default: on) so overlapping Pine tables do not interfere. Use `--no-solo-visibility` to leave the chart's study visibility untouched. |
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

`analysis/<tag>_<YYYYMMDD>.csv` (schema v2 — multi-column tables):

```
group,symbol,sig,succ,total,success_pct,avg_gain,win_pct,n,avg_r,pf,max_dd,score,sum_win_r,sum_loss_r,raw
NEWCONNECT,GPW:AQU,et3sb,26,51,51.0,1.2,45.1,51,0.45,1.88,6.55,1.6,12.3,-4.5,et3sb | 51% (26/51) 1.2% | 45.1 | 51 | 0.45 | 1.88 | 6.55 | 1.6 | 12.3 | -4.5
NEWCONNECT,GPW:AQU,et4sb,,,,,,,,,,,,,et4sb | - | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0
```

- Column 1 of the table is the legacy perf string `x% (a/b) y%` → `succ`, `total`,
  `success_pct`, `avg_gain` (a legacy trailing score, `x% (a/b) y% z`, is still
  accepted and used only if the extended `score` column is absent).
- Columns 2–9 map to `win_pct`, `n`, `avg_r`, `pf`, `max_dd`, `score`,
  `sum_win_r`, `sum_loss_r` (gross winning/losing R).
- `pf` in the table is shown as the infinity sign when the signal has **no losing
  trades**; that cell is written blank in the CSV (so it is not confused with a
  real ratio — a literal `100` would mean "100:1", not "no losses").
- `raw` mirrors the whole table row joined with ` | `. `-` in the perf cell =
  signal never occurred; then every metric is left blank.
- On a plain 2-column table the extended fields stay blank and only the
  perf-derived fields are filled (the scraper still works for any indicator).
- A symbol that could not be read gets a `NO_DATA` row (reason in `raw`).

A progress checkpoint is written to `analysis/.<tag>_progress.json`.

> Schema v2 changes the header marker, so an older (v1) CSV with the same name is
> refused by the append guard — remove/rename it or use a fresh `--tag`/date.

## Aggregating later

`scripts/summarize_signals.py` does this for you:

```powershell
python scripts\summarize_signals.py `
  --out analysis\SIGNAL_SUMMARY.csv `
  analysis\GPW_NC_ETSB_20261010.csv analysis\US_BIG_ETSB_20261010.csv
```

Per signal (`sig`), across all symbols it computes:

- cumulative success rate = `sum(succ) / sum(total)` over rows with `total > 0`
- average gain (weighted) = `sum(avg_gain * total) / sum(total)`
- cumulative win rate = `sum(win_pct * n) / sum(n)` over rows with `n > 0`
- average R (weighted) = `sum(avg_r * n) / sum(n)`
- **pooled profit factor** = `sum(sum_win_r) / |sum(sum_loss_r)|` (blank = no
  losing trades). Falls back to an n-weighted mean of the per-symbol `pf` column
  for older CSVs that lack `sum_win_r`/`sum_loss_r`.
- max drawdown = n-weighted mean of `max_dd`
- score = mean and sum of the per-symbol `score`
- **score_pos_pct** = % of occurring symbols whose per-symbol `score` > 0
  (repeatability - how often the signal is a net-positive edge on a symbol)
- **median_avg_r** = median of per-symbol `avg_r` (outlier-robust, contrasts with
  the pooled weighted `avg_r`)
- **median_pf** = median of per-symbol profit factor (from gross win/loss R,
  losing-trade symbols only; outlier-robust, contrasts with the pooled `pf`)
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
- All table columns are captured. Col 1 (perf) becomes
  `succ/total/success_pct/avg_gain`; cols 2–7 become
  `win_pct/n/avg_r/pf/max_dd/score` when present. Any other indicator using
  `table.new` still works — a 2-column table just leaves the extended fields blank.
- Reusing for another indicator: change `--indicator` (matched by name prefix),
  `--tag`, and `--resolution`. Any indicator using `table.new` works.
- TradingView may canonicalize the exchange: e.g. `NASDAQ:NVDA` resolves to
  `BATS:NVDA` (Cboe One). The script therefore matches the chart symbol by
  **ticker** (part after `:`), not by the full `EXCHANGE:TICKER` string.
