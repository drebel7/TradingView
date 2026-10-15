# TradingView Pine Script v6 - drebel

Repository of my indicators, libraries and tools for TradingView in **Pine Script v6**.

The latest version is available on GitHub at: https://github.com/drebel7/TradingView (branch `main`).

**Pine Script v6 documentation:** [codenamedevan/pinescriptv6](https://github.com/codenamedevan/pinescriptv6)

## Project structure

TradingView/
├── README.md
├── .gitignore
│
├── src/                          ← Main content
│   ├── indicators/               ← Ready indicators (+ README.md)
│   ├── libraries/                ← Libraries (+ README.md)
│   │   ├── DRELib/               ← Main library (v31+)
│   │   ├── DRECandles/           ← Candle patterns
│   │   └── DREPerf/              ← Performance analysis
│   ├── strategies/               ← Strategies (in preparation)
│   └── zzOthers/                 ← Scripts by other authors
│
├── watchlist/                    ← Ticker lists
└── docs/                         ← Documentation (optional)

Detailed descriptions are in the `README.md` files of the respective subdirectories.

## Baza analiz (`db/`)

Wyniki analiz z `analysis/` (surowe pomiary, warianty sygnałów z parametrami,
kod skryptów, dane spółek z DRE Info) są w bazie SQLite `db/analysis.db`.

```bash
python3 scripts/db_init.py             # schemat -> db/analysis.db
python3 scripts/db_import_scripts.py   # skrypty, sygnały, warianty, parametry
python3 scripts/db_import_analysis.py  # analysis/*.csv -> runy + pomiary
python3 scripts/db_query.py compare --signal CapLow   # gotowe zapytania
python3 scripts/db_browser.py --open   # przeglądarka bazy w przeglądarce
```

Szczegóły: [`db/README.md`](db/README.md).

## Libraries (`src/libraries/`)

- **DRELib** — main and most important library (version 31+)
- **DRECandles** — functions for candle analysis and patterns
- **DREPerf** — tools for statistics and success rate

Import example:
`import drebel/DRELib/31 as drelib`

## Indicators (`src/indicators/`)

Main indicator:
**ETSB_earlyTrendStrongBreakout.pine** — Early Trend Strong Breakout + ETH variant (hammer)

Full list of indicators in [`src/indicators/README.md`](src/indicators/README.md).

## How to use

1. Copy the folders from `src/libraries/` as **libraries** on TradingView.
2. Import the libraries in your scripts.
3. Add ready indicators from `src/indicators/`.

## Important

- All files are **v6**
- Extension `.pine`
- Primary timeframe: **1D**

---

**Last updated:** 2026-05-10