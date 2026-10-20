---
name: gpw-watchlist-sync
description: Sync a GPW watchlist file with the GPW main-market company list from https://www.gpw.pl/spolki — report which tickers are missing and append them at the end. Use when the user asks to update/refresh a GPW watchlist, find missing GPW symbols, or add newly listed main-market companies to a watchlist (e.g. watchlist/.PL.txt, GPW_WIG.txt).
---

# GPW Watchlist Sync

Keep a GPW watchlist in sync with the official **Główny Rynek GPW** (main market)
company list and append any missing tickers at the end of the file.

## When to use

- "Zaktualizuj watchlistę GPW / uzupełnij brakujące spółki z głównego parkietu"
- "Których symboli brakuje na liście watchlist/... ?"
- After new debuts on the main market, to refresh a watchlist file.

## The script

`scripts/gpw_watchlist_sync.py` (repository root, not this skill folder):

1. fetches the full main-market list from `https://www.gpw.pl/spolki?limit=1000`
2. extracts tickers from each company link (`spolka?isin=...`, text `NAME (TICKER)`)
3. reads the watchlist and collects existing `GPW:XXX` tokens
4. appends the missing tickers, sorted, as `,GPW:XXX` **at the very end** of the
   file (they land in the last existing group, usually `###OTHER`)
5. is **idempotent** — a second run reports "nic do dodania"

Python 3 stdlib only (no dependencies).

### Run

```bash
# preview only (nothing written)
python3 scripts/gpw_watchlist_sync.py --watchlist watchlist/.PL.txt --dry-run

# apply
python3 scripts/gpw_watchlist_sync.py --watchlist watchlist/.PL.txt
```

| Flag | Meaning |
| --- | --- |
| `--watchlist` | path to the watchlist file (default `watchlist/.PL.txt`) |
| `--url` | override the source URL (default the `?limit=1000` list) |
| `--dry-run` | print what would be added, do not modify the file |

No backup is written (the repo is under git); use `--dry-run` first if unsure.

## Why `?limit=1000`

`https://www.gpw.pl/spolki` renders only the first 20 rows server-side; the rest
load via AJAX (`POST ajaxindex.php`). Passing `?limit=1000` makes the server
render the **whole** list in one HTML response (~402 companies), which is far
simpler and more reliable than replaying the AJAX pager.

## Output / behaviour

- Prints `GPW Główny Rynek: <N> | watchlist: <M> tickerow GPW`.
- Lists the missing tickers with company names, then appends them.
- Sanity check: aborts if fewer than 300 tickers are parsed (guards against a GPW
  page-layout change) or if the fetch fails after retries.
- Retries the download up to 4 times on transient network errors (timeouts,
  truncated `IncompleteRead` responses).
- Preserves the file's single-line comma format (no trailing newline added).

## Watchlist format

Comma-separated single line; group separators start with `###`
(e.g. `###NEWCONNECT,GPW:AQU,...,###GPW-BANKI,GPW:ALR,...`). Symbols are
`GPW:TICKER`. The script only ever appends `,GPW:TICKER` tokens at the end.

## Gotchas

- The GPW list contains **all** main-market companies, including suspended /
  in-liquidation ones (e.g. `PBG`, `ENG`) — TradingView may not have a chart for
  every one.
- The watchlist may also contain NewConnect tickers (e.g. the `###NEWCONNECT`
  group). These are **not** on the main-market list and are never touched; the
  script only adds, never removes.
- If GPW changes the page markup, the run aborts with a clear error instead of
  silently writing wrong data — update `ROW_RE` / `TICKER_RE` then.
