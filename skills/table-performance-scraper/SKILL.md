# Table Performance Scraper Skill

## Purpose
Scrape performance tables from TradingView Pine Script indicators and export to CSV for aggregation across watchlists.

## When to Use
- Indicator displays a table in top-right corner with signal names and performance metrics
- Need to batch-process multiple symbols
- Table format: column1=sig_name, column2=perf_data (e.g., "67.5% (45/67) 2.3 7.2")

## Required MCP Tools
- `chart_set_symbol` - switch between symbols
- `data_get_pine_tables` - read indicator table output
- `quote_get` - verify price loaded

## Table Data Format
Each row contains:
- Column 1: Signal name (e.g., "et3sb", "rmv1", etc.)
- Column 2: Performance string in format: `x% (a/b) y% z`
  - x% = success rate (successes/total * 100)
  - a = success count
  - b = total count
  - y% = average return
  - z = composite score
- If signal didn't fire: `-` (dash)

## CSV Output Format
```csv
symbol,group,signal,perf_str,succ_pct,succ_count,total_count,avg_return,score
GPW:AQU,NEWCONNECT,et3sb,"67.5% (45/67) 2.3 7.2",67.5,45,67,2.3,7.2
GPW:AQU,NEWCONNECT,et4sb,"-",0,0,0,0,0
```

## Processing Rules
1. Parse watchlist file: split by comma, filter out `###` lines
2. For each symbol:
   a. Set symbol on chart
   b. Wait 3-5 seconds for price refresh
   c. Verify quote loaded (quote_get returns valid price)
   d. Read table with `data_get_pine_tables` using `study_filter="<indicator_name>"`
   e. Parse table rows
   f. Append to CSV
3. Add progress checkpoint every N symbols (configurable, default 50)
4. Skip symbols that fail price verification after 2 retries

## Configuration Variables
- `WATCHLIST_FILE` - path to watchlist text file
- `INDICATOR_NAME` - exact indicator name for study_filter
- `OUTPUT_DIR` - directory for CSV output
- `CHECKPOINT_INTERVAL` - number of symbols between checkpoints
- `SYMBOLS_PER_BATCH` - symbols to process before context flush
- `RETRY_COUNT` - number of retries for failed symbols
- `RETRY_DELAY` - delay between retries in seconds

## Skill Workflow
1. Read and parse watchlist file
2. Extract symbols (ignore `###` group lines)
3. For each symbol:
   - chart_set_symbol(symbol)
   - Wait for price load
   - data_get_pine_tables(study_filter=INDICATOR_NAME)
   - Parse table output
   - Write to CSV
4. Save checkpoint file with last processed symbol
5. On resume, read checkpoint and continue from last symbol

## Error Handling
- Symbol not found: skip and log
- Price not loading: retry 2 times with 3s delay
- Table read fails: retry 1 time
- File write error: log and continue
