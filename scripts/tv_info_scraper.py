#!/usr/bin/env python3
"""
tv_info_scraper.py
==================
Scrapes the **DRE Info** indicator table (a 2-column label -> value table) for
every symbol in a TradingView watchlist and writes one CSV row per symbol.

Unlike the signal scraper (`tv_table_scraper.py`, which reads a signal x metric
table), this one reads a label/value card:

    MCap                    6.376M
    ADR [%]                 4.2
    ATR                     3.15
    Avg. turnover [M]       12.4
    HoD price               58.9
    Close vs MAs prctl.     82/71/55/40
    Sharpe ratio            1.8
    EPS up 1y 2y            3/4 5/8
    sector                  Financials
    industry                Banks
    bench. index            WIG (++)
    nBroken extremes        14 (+)
    years on exch.          12

Rows "LoD price", "LoD dist. [%]", "Dtt vol. [%] (proj.)" and "Dtt time [%]"
are intentionally NOT exported to the CSV/database (they stay in the `raw`
audit column).

Labels are matched by normalized prefix, so hidden rows simply stay blank.
The full label|value dump is stored in the `raw` column as an audit trail, so
nothing is lost if the indicator changes.

Reuses the CDP/launch/watchlist machinery from `tv_table_scraper.py`
(same TradingView Desktop over the DevTools Protocol on port 9222).

Before scraping it resets the indicator inputs to script defaults and forces a
complete card: all display flags ON, `Calculations Length` and
`Risk free annual rate` fixed, so every symbol is measured with the same
configuration.

Output: `<outdir>/<TAG>_<YYYYMMDD>.csv` (default TAG from the watchlist name,
e.g. `.GPW_NC.txt` -> `GPW_NC_INFO_20261014.csv`), written incrementally, with
a `.<TAG>_progress.json` resume file. Import to the database with
`python3 scripts/db_import_company.py`.

Usage
-----
  python3 scripts/tv_info_scraper.py \
      --watchlist watchlist/.GPW_NC.txt \
      --outdir analysis \
      [--tag GPW_NC_INFO] [--indicator "DRE Info"] \
      [--resolution D] [--min-rows 4] [--limit 10] [--start 0] \
      [--timeout 25] [--settle 0.6] [--retries 2] \
      [--no-set-input-defaults] [--tv-port 9222] [--no-tv-autolaunch]
"""

import argparse
import asyncio
import csv
import json
import re
import sys
import time
from datetime import datetime
from functools import partial
from pathlib import Path

import tv_table_scraper as tts

DEFAULT_INDICATOR = "DRE Info"
DEFAULT_CDP_PORT = tts.DEFAULT_CDP_PORT

HEADER_MARKER = "# TradingView DRE Info scraper results v2"

# Wymuszone inputy (dopasowanie po znormalizowanej nazwie - jak w JS_SET_INPUTS).
INFO_INPUT_OVERRIDES = {
    "show ticker": True,
    "show market cap": True,
    "show adr %": True,
    "show atr": True,
    "show avg. turnover": True,
    "show hod price": True,
    "show lod price": True,
    "show lod distance": True,
    "day to time volume %": True,
    "day to time time %": True,
    "mas dist. percentiles": True,
    "sharpe ratio": True,
    "earnings going up": True,
    "industry and sector": True,
    "nbroken extremes": True,
    "years on exchage": True,
    "calculations length": 30,
    "risk free annual rate": 0.05,
}

# Kolumny CSV = pola w bazie (company_metric / company_profile).
# Uwaga: wiersze "LoD price", "LoD dist. [%]", "Dtt vol. [%] (proj.)" i
# "Dtt time [%]" nie są już eksportowane (świadomie poza bazą) - pozostają
# widoczne w kolumnie `raw`.
FIELDS = [
    "ticker_table", "market_cap_m", "adr_pct", "atr", "avg_turnover_m", "hod_price",
    "ma_dist_prctl", "sharpe", "eps_up_1y", "eps_days_1y", "eps_up_2y",
    "eps_days_2y", "sector", "industry", "bench_index", "bench_mod",
    "n_broken_extremes_pct", "n_broken_mod", "years_on_exchange",
]
CSV_COLUMNS = ["group", "symbol", "status"] + FIELDS + ["raw"]


# ---------------------------------------------------------------------------
# Parsowanie tabeli label -> wartość
# ---------------------------------------------------------------------------

def norm_label(text) -> str:
    return re.sub(r"\s+", " ", str(text or "").lower()).strip()


def num(text):
    """Liczba z tekstu ('4.2', '1 234', '-', '∞')."""
    if text is None:
        return None
    t = str(text).strip().replace("\u00a0", "").replace(" ", "").replace(",", ".")
    if t in ("", "-", "–", "∞", "inf", "nan", "NaN"):
        return None
    m = re.match(r"^[+-]?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?", t)
    return float(m.group(0)) if m else None


def int_or_none(text):
    v = num(text)
    return int(v) if v is not None else None


def split_parens(text):
    """'84 (127)' -> ('84', '127'); 'WIG (++)' -> ('WIG', '++')."""
    t = str(text or "").strip()
    m = re.match(r"^(.*?)\s*\(([^)]*)\)\s*$", t)
    if m:
        return m.group(1).strip(), m.group(2).strip()
    return t, None


MCAP_SUFFIX = {"K": 1e-3, "M": 1.0, "B": 1e3, "T": 1e6}   # -> miliony


def parse_mcap(text):
    """'6.376M' / '10.06B' / '890K' / '1.2T' -> wartość w MILIONACH.

    DRE Info pokazuje MCap przez `str.tostring(..., format.volume)`, czyli
    z sufiksem K/M/B/T (waluta instrumentu). 'n/a' i puste -> None.
    """
    t = str(text or "").strip().replace("\u00a0", "").replace(" ", "")
    if t in ("", "-", "n/a", "N/A", "na", "NaN"):
        return None
    m = re.fullmatch(r"([+-]?\d+(?:[.,]\d+)?)\s*([KMBT])?", t, re.I)
    if not m:
        return None
    value = float(m.group(1).replace(",", "."))
    mult = MCAP_SUFFIX.get((m.group(2) or "M").upper(), 1.0)
    return value * mult


def parse_info_rows(rows):
    """Zamienia wiersze tabeli na pola bazy. Zwraca (dict, lista (label, value))."""
    out = {}
    raw_pairs = []
    for cells in rows:
        label = (cells[0] if len(cells) > 0 else "").strip()
        value = (cells[1] if len(cells) > 1 else "").strip()
        if not label and not value:
            continue
        raw_pairs.append((label, value))
        n = norm_label(label)

        if not label:
            # pusta etykieta z wartością = wiersz "Show ticker"
            out["ticker_table"] = value
        elif n.startswith("mcap"):
            out["market_cap_m"] = parse_mcap(value)
        elif n.startswith("adr"):
            out["adr_pct"] = num(value)
        elif n == "atr":
            out["atr"] = num(value)
        elif n.startswith("avg. turnover"):
            out["avg_turnover_m"] = num(value)
        elif n.startswith("hod price"):
            out["hod_price"] = num(value)
        elif n.startswith("close vs mas"):
            out["ma_dist_prctl"] = value or None
        elif n.startswith("sharpe"):
            out["sharpe"] = num(value)
        elif n.startswith("eps up"):
            # 'x/y x/y' -> EPS up 1y / dni 1y / EPS up 2y / dni 2y
            parts = re.findall(r"(\d+)\s*/\s*(\d+)", value)
            if len(parts) >= 1:
                out["eps_up_1y"], out["eps_days_1y"] = int(parts[0][0]), int(parts[0][1])
            if len(parts) >= 2:
                out["eps_up_2y"], out["eps_days_2y"] = int(parts[1][0]), int(parts[1][1])
        elif n == "sector":
            out["sector"] = value or None
        elif n == "industry":
            out["industry"] = value or None
        elif n.startswith("bench"):
            index, mod = split_parens(value)
            out["bench_index"] = index or None
            out["bench_mod"] = mod
        elif n.startswith("nbroken"):
            pct, mod = split_parens(value)
            out["n_broken_extremes_pct"] = num(pct)
            out["n_broken_mod"] = mod
        elif n.startswith("years on exch"):
            out["years_on_exchange"] = int_or_none(value)
    return out, raw_pairs


def rows_structure(rows):
    """Klucz stabilności: same etykiety (wartości zmieniają się w sesji)."""
    return [((c[0] if len(c) > 0 else "").strip()) for c in rows]


def rows_match_symbol(rows, symbol) -> bool:
    """Czy tabela dotyczy scrapowanej spółki?

    Po zmianie symbolu wykres przełącza się szybciej niż przerysowuje tabela,
    więc bez tej kontroli da się zapisać dane poprzedniej spółki (tabela ma
    identyczne etykiety, więc sama stabilność struktury tego nie wychwyci).
    """
    fields, _ = parse_info_rows(rows)
    ticker_table = fields.get("ticker_table")
    return (not ticker_table) or _ticker_matches(ticker_table, symbol)


# ---------------------------------------------------------------------------
# CSV
# ---------------------------------------------------------------------------

def write_csv_header(path, indicator, watchlist, resolution):
    if path.exists() and path.stat().st_size > 0:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            first = f.readline().strip()
        if first != HEADER_MARKER:
            raise SystemExit(
                f"ERROR: {path} exists but is not a current DRE Info scraper "
                f"output (first line: {first!r}, expected {HEADER_MARKER!r}). "
                f"Rename it (e.g. add a _v1 suffix) or use a fresh --tag/date.")
        return
    with open(path, "w", newline="", encoding="utf-8") as f:
        f.write(HEADER_MARKER + "\n")
        f.write(f"# indicator: {indicator}\n")
        f.write(f"# watchlist: {watchlist}\n")
        f.write(f"# resolution: {resolution}\n")
        f.write(f"# generated: {datetime.now().isoformat(timespec='seconds')}\n")
        f.write("# columns: " + ",".join(CSV_COLUMNS) + "\n")
        f.write("# metrics: label->value card of the DRE Info table "
                "(blank = row hidden or value not available)\n")
        f.write("# status: ok | no_data (symbol nieodczytany)\n")
        f.write("# raw: full label | value dump for audit\n")
        w = csv.writer(f)
        w.writerow(CSV_COLUMNS)


def append_row(path, group, symbol, fields, raw_pairs, status="ok", note=None):
    rec = {k: "" for k in FIELDS}
    rec.update({k: v for k, v in fields.items() if v is not None})
    raw = " ; ".join(f"{l} | {v}" for l, v in raw_pairs)
    if note:
        raw = (raw + " ; " if raw else "") + f"note: {note}"
    with open(path, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow([group, symbol, status] + [rec[k] for k in FIELDS] + [raw])


# ---------------------------------------------------------------------------
# Pętla scrapowania
# ---------------------------------------------------------------------------

def tag_from_watchlist(watchlist: str) -> str:
    stem = Path(watchlist).name
    if stem.endswith(".txt"):
        stem = stem[:-4]
    return stem.lstrip(".").upper()


def write_progress(path, **kw):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(kw, f, ensure_ascii=False, indent=2)


async def main_async(args):
    if args.tv_autolaunch:
        tts.ensure_tv_cdp(args.tv_port, args.tv_path,
                          args.tv_kill_existing, args.tv_launch_wait)
    ws_url = tts.wait_for_chart_ws_url(args.tv_port, timeout=args.tv_wait)
    print(f"[i] CDP chart target: {ws_url}")

    symbols = tts.parse_watchlist(args.watchlist)
    total = len(symbols)
    print(f"[i] watchlist: {args.watchlist} -> {total} symbols")

    tag = args.tag or f"{tag_from_watchlist(args.watchlist)}_INFO"
    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    date_tag = datetime.now().strftime("%Y%m%d")
    out_csv = outdir / f"{tag}_{date_tag}.csv"
    progress_path = outdir / f".{tag}_progress.json"

    write_csv_header(out_csv, args.indicator, args.watchlist, args.resolution)
    print(f"[i] output CSV: {out_csv}")

    start = args.start
    end = total if args.limit <= 0 else min(total, start + args.limit)

    ok = 0
    fail = 0
    failed_symbols = []

    async with tts.connect(ws_url, max_size=None, open_timeout=15) as ws:
        cdp = tts.CDP(ws)
        if not await tts.wait_chart_ready(cdp, timeout=90):
            print("[warn] chart did not report ready within 90s - continuing anyway")
        await tts.click_connect_button(cdp)

        if args.resolution:
            ok_res = await tts.set_resolution(cdp, args.resolution)
            print(f"[i] resolution set to '{args.resolution}': {ok_res}")
            if str(args.resolution).upper() in ("W", "1W", "M", "1M"):
                print("[warn] DRE Info nie rysuje tabeli na W/M - użyj D")

        if args.solo_visibility:
            vis = await tts.show_only_indicator(cdp, args.indicator)
            if vis.get("ok"):
                shown = ", ".join(vis.get("shown") or []) or "-"
                print(f"[i] solo visibility: showing [{shown}], "
                      f"hid {vis.get('hidden')} other studies")
                if not vis.get("matched"):
                    print("[warn] target indicator not found on chart - "
                          "it must be added and visible")
            else:
                print(f"[warn] solo visibility failed: {vis.get('err')}")

        cfg = await tts.configure_inputs(cdp, args.indicator,
                                         args.set_input_defaults,
                                         INFO_INPUT_OVERRIDES)
        if cfg.get("ok"):
            print(f"[i] inputs: applied {cfg.get('applied')} "
                  f"({cfg.get('overrides')} forced), skipped {cfg.get('skipped')}")
            if not await tts.wait_inputs_applied(cdp, args.indicator):
                print("[warn] study did not settle after input change - "
                      "continuing anyway")
        else:
            print(f"[warn] input setup failed: {cfg.get('err')}")

        for idx in range(start, end):
            group, symbol = symbols[idx]
            label = f"[{idx+1}/{total}] {symbol} ({group})"
            sys.stdout.write(label + " ... ")
            sys.stdout.flush()

            t0 = time.monotonic()
            rows, err = await tts.scrape_symbol(
                cdp, symbol, args.indicator, args.timeout, args.settle,
                args.min_rows, stable_on=rows_structure,
                accept=partial(rows_match_symbol, symbol=symbol))
            dt = time.monotonic() - t0

            if rows is None:
                fail += 1
                failed_symbols.append((idx, group, symbol, err))
                print(f"FAIL ({err}) [{dt:.1f}s]")
                append_row(out_csv, group, symbol, {}, [], status="no_data",
                           note=f"NO_DATA {err}")
            else:
                fields, raw_pairs = parse_info_rows(rows)
                ticker_table = fields.get("ticker_table") or ""
                warn = ""
                if ticker_table and not _ticker_matches(ticker_table, symbol):
                    warn = f" (uwaga: tabela pokazuje {ticker_table})"
                append_row(out_csv, group, symbol, fields, raw_pairs)
                ok += 1
                print(f"OK ({len(raw_pairs)} rows) [{dt:.1f}s]{warn}")

            write_progress(progress_path, last_index=idx, last_symbol=symbol,
                           ok=ok, fail=fail, updated=datetime.now().isoformat(
                               timespec="seconds"), out_csv=str(out_csv))

        # retry passes for failed symbols (fresh chart state)
        for attempt in range(1, max(args.retries, 0) + 1):
            if not failed_symbols:
                break
            print(f"[i] retry pass {attempt}/{args.retries}: "
                  f"{len(failed_symbols)} symbols")
            pending, failed_symbols = failed_symbols, []
            for idx, group, symbol, err in pending:
                sys.stdout.write(f"[retry {symbol}] ... ")
                sys.stdout.flush()
                rows, err2 = await tts.scrape_symbol(
                    cdp, symbol, args.indicator, args.timeout, args.settle,
                    args.min_rows, stable_on=rows_structure,
                    accept=partial(rows_match_symbol, symbol=symbol))
                if rows is None:
                    failed_symbols.append((idx, group, symbol, err2))
                    print(f"FAIL ({err2})")
                    continue
                fields, raw_pairs = parse_info_rows(rows)
                append_row(out_csv, group, symbol, fields, raw_pairs)
                ok += 1
                fail -= 1
                print("OK")
                write_progress(progress_path, last_index=idx, last_symbol=symbol,
                               ok=ok, fail=fail, updated=datetime.now().isoformat(
                                   timespec="seconds"), out_csv=str(out_csv))

    if failed_symbols:
        print(f"[done] {len(failed_symbols)} symbols still failed:")
        for _, group, symbol, err in failed_symbols:
            print(f"    {group}:{symbol} — {err}")
    print(f"[done] {ok} OK, {fail} FAIL -> {out_csv}")
    return 0 if fail == 0 else 1


def _ticker_matches(ticker_table: str, symbol: str) -> bool:
    """Luźne porównanie tickera z tabeli z symbolem watchlisty."""
    a = str(ticker_table).strip().upper()
    b = str(symbol).strip().upper()
    if a == b:
        return True
    return a.split(":")[-1] == b.split(":")[-1]


def main():
    # Windows consoles may use a non-UTF-8 code page (e.g. cp1250); the scraped
    # table can contain non-ASCII glyphs, which would crash print().
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    ap = argparse.ArgumentParser(
        description="Scrape the DRE Info table (label -> value) for a watchlist")
    ap.add_argument("--watchlist", required=True)
    ap.add_argument("--outdir", default="analysis")
    ap.add_argument("--tag", default=None,
                    help="prefix pliku wyniku (domyślnie <WATCHLISTA>_INFO)")
    ap.add_argument("--indicator", default=DEFAULT_INDICATOR)
    ap.add_argument("--resolution", default="D",
                    help="interwał wykresu ustawiany przed zbieraniem (DRE Info "
                         "nie rysuje tabeli na W/M); domyślnie D")
    ap.add_argument("--min-rows", type=int, default=4, dest="min_rows",
                    help="minimalna liczba wierszy tabeli uznana za gotową (domyślnie 4)")
    ap.add_argument("--limit", type=int, default=0, help="0 = wszystkie")
    ap.add_argument("--start", type=int, default=0, help="indeks startowy (wznowienie)")
    ap.add_argument("--timeout", type=float, default=25.0,
                    help="timeout na symbol (s)")
    ap.add_argument("--settle", type=float, default=0.6, help="interwał odpytywania (s)")
    # TradingView Desktop / CDP
    ap.add_argument("--tv-port", type=int, default=DEFAULT_CDP_PORT,
                    help="port CDP (domyślnie 9222)")
    ap.add_argument("--tv-path", default=None,
                    help="ścieżka do pliku wykonywalnego TradingView Desktop")
    ap.add_argument("--tv-autolaunch", action=argparse.BooleanOptionalAction,
                    default=True,
                    help="uruchom TradingView z CDP, jeśli nie odpowiada (domyślnie tak)")
    ap.add_argument("--tv-kill-existing", action=argparse.BooleanOptionalAction,
                    default=True,
                    help="jeśli TradingView działa bez CDP, zrestartuj go (domyślnie tak)")
    ap.add_argument("--tv-launch-wait", type=float, default=30.0,
                    help="sekundy oczekiwania na CDP po starcie (domyślnie 30)")
    ap.add_argument("--tv-wait", type=float, default=60.0,
                    help="sekundy oczekiwania na stronę wykresu po CDP "
                         "(domyślnie 60)")
    ap.add_argument("--solo-visibility", action=argparse.BooleanOptionalAction,
                    default=True,
                    help="ukryj inne wskaźniki na wykresie (domyślnie tak)")
    ap.add_argument("--set-input-defaults", action=argparse.BooleanOptionalAction,
                    default=True,
                    help="resetuj inputy wskaźnika do domyślnych przed zbieraniem "
                         "(domyślnie tak); komplet pól karty i tak jest wymuszany")
    ap.add_argument("--retries", type=int, default=1,
                    help="liczba podejść ponawiania nieudanych symboli (domyślnie 1)")
    args = ap.parse_args()
    try:
        return asyncio.run(main_async(args))
    except KeyboardInterrupt:
        print("\n[interrupted]")
        return 130
    except RuntimeError as exc:
        print(f"[error] {exc}", file=sys.stderr)
        print("[hint] uruchom TradingView Desktop (scraper zrobi to sam bez "
              "--no-tv-autolaunch) albo wskaż port/ścieżkę: --tv-port / --tv-path",
              file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
