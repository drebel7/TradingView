#!/usr/bin/env python3
"""
db_verify.py
============
Kryterium odbioru importu: widoki SQL muszą odtworzyć istniejące pliki
podsumowań (`*_SUMMARY.csv`, `*_SUMMARY_ALL.csv`, `BASE_*.csv`).

Porównywane są zaokrąglenia 1:1 z scripts/summarize_signals.py; tolerancja to
1 jednostka ostatniego miejsca (SQL ROUND i round() w Pythonie mogą różnić się
kierunkiem zaokrąglenia połówki).

Mapowanie plików na zakres danych:
  BASE_ALL.csv            -> v_signal_summary_all,  indicator 'early trend strong breakout'
  BASE_GPW.csv            -> v_signal_summary_latest, universe GPW_NC
  BASE_US.csv             -> v_signal_summary_latest, universe US_BIG
  <X>_SUMMARY_ALL.csv     -> v_signal_summary_all
  <UNIWERSUM>_<X>_SUMMARY.csv -> v_signal_summary_latest, universe <UNIWERSUM>
  VIPOPT_SUMMARY.csv      -> v_signal_summary_latest, universe GPW_NC

Usage:
  python3 scripts/db_verify.py
  python3 scripts/db_verify.py --dir analysis --quiet
"""

import argparse
import csv
import sqlite3
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = REPO_ROOT / "db" / "analysis.db"
DEFAULT_DIR = REPO_ROOT / "analysis"

UNIVERSES = ("GPW_NC", "US_BIG")

# Pliki legacy bez prefiksu uniwersum i bez sufiksu _ALL: jawny zakres
SCOPE_HINTS = {
    "VIPOPT_SUMMARY.csv": ("latest", "GPW_NC"),
    "SIGNAL_SUMMARY.csv": ("all", None),
}

# (kolumna, miejsca po przecinku)
COLS = [
    ("symbols", 0), ("occurrences", 0), ("win_pct", 1), ("avg_r", 3),
    ("pf", 2), ("max_dd", 2), ("score_mean", 2), ("score_sum", 1),
    ("score_pos_pct", 0), ("median_avg_r", 3), ("median_pf", 2),
    ("gross_win_r", 1), ("gross_loss_r", 1),
]

SUMMARY_COLS = ["indicator", "sig"] + [c for c, _ in COLS]


def read_summary(path: Path):
    with open(path, newline="", encoding="utf-8", errors="replace") as f:
        return list(csv.DictReader(line for line in f if not line.startswith("#")))


def fnum(value):
    if value is None:
        return None
    t = str(value).strip()
    if t == "":
        return None
    try:
        return float(t)
    except ValueError:
        return None


def close_enough(a, b, dec):
    if a is None and b is None:
        return True
    if a is None or b is None:
        return False
    return abs(a - b) <= 10 ** (-dec) + 1e-9


def map_files(directory: Path):
    """[(plik, scope, universe, indicator)]; scope: 'latest' | 'all'."""
    out = []
    for p in sorted(directory.glob("*SUMMARY*.csv")) + sorted(directory.glob("BASE_*.csv")):
        name = p.name
        universe = next((u for u in UNIVERSES if name.startswith(u + "_")), None)
        if name.startswith("BASE_"):
            scope = "all" if name == "BASE_ALL.csv" else "latest"
            indicator = "early trend strong breakout"
            universe = {"BASE_GPW.csv": "GPW_NC", "BASE_US.csv": "US_BIG"}.get(name)
        elif name.endswith("_SUMMARY_ALL.csv"):
            scope, indicator = "all", None
        elif name in SCOPE_HINTS:
            scope, universe = SCOPE_HINTS[name]
            indicator = None
        elif universe is None:
            scope, indicator = "all", None
        else:
            scope, indicator = "latest", None
        out.append((p, scope, universe, indicator))
    return out


def check_file(path, scope, universe, indicator, latest_rows, all_rows,
               indicator_codes):
    """Porównuje plik SUMMARY z wcześniej wczytanymi wierszami widoków."""
    rows = read_summary(path)
    if not rows:
        return 0, 0, [f"{path.name}: plik bez wierszy"]
    if indicator is None:
        indicator = rows[0].get("indicator", "")
    if scope == "all":
        codes = indicator_codes.get(indicator.lower(), set())
        db_rows = {sig: r for (code, sig), r in all_rows.items() if code in codes}
    else:
        db_rows = {sig: r for (u, ind, sig), r in latest_rows.items()
                   if u == universe and ind == indicator.lower()}

    problems, checked = [], 0
    for r in rows:
        sig = (r.get("sig") or "").strip()
        if not sig:
            continue
        if sig not in db_rows:
            problems.append(f"{path.name}: brak w bazie: {sig}")
            continue
        checked += 1
        db = db_rows[sig]
        for col, dec in COLS:
            exp = fnum(r.get(col))
            got = db[col]
            if not close_enough(exp, got, dec):
                problems.append(
                    f"{path.name}: {sig}.{col}: plik={exp!r} baza={got!r}")
    return checked, len(rows), problems


SUMMARY_SELECT = """SELECT %s, sig_name, symbols, occurrences, win_pct, avg_r, pf,
                           max_dd, score_mean, score_sum, score_pos_pct,
                           median_avg_r, median_pf, gross_win_r, gross_loss_r
                    FROM %s"""


def load_view_rows(con, scope):
    """Wczytuje cały widok podsumowania raz (klucz: sygnał lub (uniwersum, tytuł, sygnał))."""
    con.row_factory = sqlite3.Row
    if scope == "all":
        sql = SUMMARY_SELECT % ("signal_code", "v_signal_summary_all")
        return {(r["signal_code"], r["sig_name"]): r for r in con.execute(sql)}
    sql = SUMMARY_SELECT % ("universe, LOWER(indicator_title) AS indicator_title",
                            "v_signal_summary_latest")
    return {(r["universe"], r["indicator_title"], r["sig_name"]): r
            for r in con.execute(sql)}


def load_indicator_codes(con):
    """indicator (tytuł skryptu) -> zbiór kodów sygnałów (do plików *_SUMMARY_ALL)."""
    out = {}
    for title, code in con.execute(
            """SELECT sc.title, s.code FROM signal s JOIN script sc ON sc.id = s.script_id"""):
        if title:
            out.setdefault(title.lower(), set()).add(code)
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Weryfikacja widoków vs pliki SUMMARY")
    ap.add_argument("--db", default=str(DEFAULT_DB))
    ap.add_argument("--dir", default=str(DEFAULT_DIR))
    ap.add_argument("--quiet", action="store_true", help="tylko podsumowanie")
    args = ap.parse_args(argv)

    con = sqlite3.connect(args.db)
    directory = Path(args.dir)
    print("[i] wczytuję widoki podsumowań (2 zapytania)...")
    latest_rows = load_view_rows(con, "latest")
    all_rows = load_view_rows(con, "all")
    indicator_codes = load_indicator_codes(con)

    total_checked = total_problems = 0
    for path, scope, universe, indicator in map_files(directory):
        checked, n_rows, problems = check_file(path, scope, universe, indicator,
                                               latest_rows, all_rows, indicator_codes)
        total_checked += checked
        total_problems += len(problems)
        status = "OK  " if not problems else "FAIL"
        scope_txt = "ALL" if scope == "all" else (universe or "-")
        print(f"[{status}] {path.name:34s} zakres={scope_txt:7s} "
              f"wierszy={n_rows:3d} sprawdzono={checked:3d} "
              f"niezgodności={len(problems)}")
        if not args.quiet:
            for p in problems[:10]:
                print(f"        {p}")
            if len(problems) > 10:
                print(f"        ... (+{len(problems) - 10})")
    con.close()

    print(f"\nRAZEM: sprawdzono {total_checked} wierszy, "
          f"niezgodności: {total_problems}")
    return 0 if total_problems == 0 else 2


if __name__ == "__main__":
    sys.exit(main())
