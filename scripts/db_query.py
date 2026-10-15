#!/usr/bin/env python3
"""
db_query.py
===========
Gotowe zapytania do bazy `db/analysis.db` - jedno polecenie zamiast pisania SQL.

Polecenia:
  runs                        - lista runów (uniwersum x skrypt x data, ok/fail)
  summary                     - podsumowanie sygnałów (jak *_SUMMARY.csv)
      --all                     po wszystkich uniwersach (jak *_SUMMARY_ALL.csv)
      --universe GPW_NC|US_BIG  filtr uniwersum (akceptuje GPW/US)
      --signal CODE             filtr sygnału bazowego (np. CapLow)
      --sort COL                score_mean|avg_r|pf|win_pct|score_pos_pct|occurrences
      --min-occ N               tylko warianty z co najmniej N wystąpieniami
  top                         - najlepsze warianty wg wybranej metryki
      --by COL (domyślnie score_mean), --min-occ, --universe, --limit
  compare                     - sygnał oryginalny vs replika vs najlepszy wariant
  screen                      - screening: sygnały na spółkach wg kryteriów
      --min-mcap/--max-mcap, --bucket, --min-adr, --min-turnover, --min-sharpe,
      --sector, --industry, --min-years, --only-known-mcap, --min-occ, --by
  trend                       - metryki wariantu w kolejnych runach (historia)
      --sig NAME  lub  --signal CODE [--universe U]
  variants                    - warianty + PARAMETRY (name=value)
      --signal CODE, --sig NAME
  params                      - parametry jednego wariantu (klucz: wartość)
  company TICKER              - karta spółki (DRE Info + skład uniwersów)
  companies                   - lista spółek (--sector, --limit)
  gaps                        - symbole nieodczytane w runach (NO_DATA)
  runs_detail                 - rozkład statusów pomiarów w runach
  schema                      - tabele i widoki
  sql "SELECT ..."            - dowolne zapytanie (read-only)

Opcje globalne: --db PATH, --json, --limit N.

Przykłady:
  python3 scripts/db_query.py compare --universe GPW --signal CapLow
  python3 scripts/db_query.py top --by score_mean --min-occ 100
  python3 scripts/db_query.py trend --sig capLowTFT_95 --universe GPW
  python3 scripts/db_query.py params --signal vip
"""

import argparse
import json
import os
import sqlite3
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = REPO_ROOT / "db" / "analysis.db"

UNIVERSE_ALIASES = {"GPW": "GPW_NC", "GPW_NC": "GPW_NC", "US": "US_BIG",
                    "US_BIG": "US_BIG", "ALL": None}

SORT_COLS = ("score_mean", "avg_r", "pf", "win_pct", "score_pos_pct",
             "occurrences", "symbols", "median_avg_r", "median_pf")


# ---------------------------------------------------------------------------
# Prezentacja
# ---------------------------------------------------------------------------

def fmt(value, dec=2, width=60):
    if value is None:
        return "-"
    if isinstance(value, float):
        text = f"{value:.{dec}f}"
    else:
        text = str(value)
    if width and len(text) > width:
        text = text[:width - 3] + "..."
    return text


def print_table(rows, columns=None, dec=2, limit=None):
    """Prosta tabela tekstowa z wyrównaniem kolumn."""
    if not rows:
        print("(brak wierszy)")
        return
    columns = columns or list(rows[0].keys())
    data = [[fmt(r.get(c), dec) for c in columns] for r in (rows[:limit] if limit else rows)]
    widths = [max(len(str(c)), *(len(row[i]) for row in data)) for i, c in enumerate(columns)]
    print("  ".join(str(c).rjust(w) if i else str(c).ljust(w)
                    for i, (c, w) in enumerate(zip(columns, widths))))
    print("  ".join("-" * w for w in widths))
    for row in data:
        print("  ".join(v.rjust(w) if i else v.ljust(w)
                        for i, (v, w) in enumerate(zip(row, widths))))


def emit(args, rows, columns=None, dec=2, limit=None):
    if args.json:
        print(json.dumps(rows, ensure_ascii=False, indent=2, default=str))
    else:
        print_table(rows, columns, dec, limit)


def lit(value):
    """Bezpieczny literał SQL (podwojenie apostrofów)."""
    return "'" + str(value).replace("'", "''") + "'"


def eq_nocase(col, value):
    """Warunek SQL: kolumna = wartość, bez rozróżniania wielkości liter."""
    return f" AND {col} = {lit(value)} COLLATE NOCASE"


def universe_arg(value):
    if value is None:
        return None
    key = value.upper()
    if key not in UNIVERSE_ALIASES:
        raise SystemExit(f"[error] nieznane uniwersum: {value} "
                         f"(dozwolone: {', '.join(sorted(UNIVERSE_ALIASES))})")
    return UNIVERSE_ALIASES[key]


# ---------------------------------------------------------------------------
# Polecenia
# ---------------------------------------------------------------------------

SUMMARY_COLS = ["universe", "started_at", "signal_code", "sig_name", "role",
                "symbols", "occurrences", "win_pct", "avg_r", "pf", "max_dd",
                "score_mean", "score_sum", "score_pos_pct", "median_avg_r",
                "median_pf", "gross_win_r", "gross_loss_r"]


def cmd_runs(con, args):
    sql = """SELECT u.code AS universe, r.indicator_title, r.started_at,
                    r.finished_at, r.ok, r.fail, r.out_csv, sc.path AS script,
                    COUNT(m.variant_id) AS pomiary
             FROM run r
             LEFT JOIN universe u ON u.id = r.universe_id
             LEFT JOIN script sc ON sc.id = r.script_id
             LEFT JOIN measurement m ON m.run_id = r.id
             GROUP BY r.id ORDER BY r.started_at, u.code"""
    rows = [dict(r) for r in con.execute(sql)]
    emit(args, rows, ["universe", "indicator_title", "started_at", "ok", "fail",
                      "pomiary", "out_csv"])


def cmd_summary(con, args):
    universe = universe_arg(args.universe)
    if args.all:
        sql = f"SELECT 'ALL' AS universe, NULL AS started_at, {', '.join(SUMMARY_COLS[2:])} FROM v_signal_summary_all WHERE 1=1"
    else:
        sql = f"SELECT {', '.join(SUMMARY_COLS)} FROM v_signal_summary_latest WHERE 1=1"
        if universe:
            sql += eq_nocase("universe", universe)
    if args.signal:
        sql += eq_nocase("signal_code", args.signal)
    if args.min_occ:
        sql += f" AND occurrences >= {int(args.min_occ)}"
    sort = args.sort if args.sort in SORT_COLS else "score_mean"
    sql += f" ORDER BY {sort} DESC NULLS LAST, occurrences DESC"
    rows = [dict(r) for r in con.execute(sql)]
    emit(args, rows, None, 2, args.limit or 60)


def cmd_top(con, args):
    universe = universe_arg(args.universe)
    by = args.by if args.by in SORT_COLS else "score_mean"
    sql = f"""SELECT universe, signal_code, sig_name, role, symbols, occurrences,
                     win_pct, avg_r, pf, score_mean, score_pos_pct, median_avg_r
              FROM v_signal_summary_latest
              WHERE occurrences >= {int(args.min_occ or 0)}"""
    if universe:
        sql += eq_nocase("universe", universe)
    sql += f" ORDER BY {by} DESC NULLS LAST, occurrences DESC LIMIT {int(args.limit or 25)}"
    rows = [dict(r) for r in con.execute(sql)]
    emit(args, rows)


def cmd_compare(con, args):
    sql = "SELECT * FROM v_baseline_vs_best WHERE 1=1"
    if args.signal:
        sql += eq_nocase("signal_code", args.signal)
    universe = universe_arg(args.universe)
    if universe:
        sql += eq_nocase("universe", universe)
    sql += " ORDER BY universe, signal_code"
    rows = [dict(r) for r in con.execute(sql)]
    if args.json:
        emit(args, rows)
        return
    for r in rows:
        print(f"[{r['universe']}] {r['signal_code']}  (oryginał z {r['baseline_started_at']})")
        print(f"    ORIGINAL     {r['baseline_sig']:>12}: sym={r['baseline_symbols']:>4} "
              f"occ={r['baseline_occ']:>6} win%={fmt(r['baseline_win_pct'],1):>5} "
              f"PF={fmt(r['baseline_pf']):>5} sc={fmt(r['baseline_score']):>6} "
              f"sc>0={fmt(r['baseline_score_pos_pct'],0):>3}%")
        if r["equiv_sig"]:
            print(f"    REPLIKA      {r['equiv_sig']:>12}: sym={r['equiv_symbols']:>4} "
                  f"occ={r['equiv_occ']:>6} win%={fmt(r['equiv_win_pct'],1):>5} "
                  f"PF={fmt(r['equiv_pf']):>5} sc={fmt(r['equiv_score']):>6} "
                  f"sc>0={fmt(r['equiv_score_pos_pct'],0):>3}%")
        if r["best_sig"]:
            print(f"    BEST(sc)     {r['best_sig']:>12}: sym={r['best_symbols']:>4} "
                  f"occ={r['best_occ']:>6} win%={fmt(r['best_win_pct'],1):>5} "
                  f"PF={fmt(r['best_pf']):>5} sc={fmt(r['best_score']):>6} "
                  f"sc>0={fmt(r['best_score_pos_pct'],0):>3}%")
        if r["best_robust_sig"] and r["best_robust_sig"] != r["best_sig"]:
            print(f"    BEST(robust) {r['best_robust_sig']:>12}: "
                  f"occ={r['best_robust_occ']:>6} sc={fmt(r['best_robust_score']):>6}")
        print()


def cmd_trend(con, args):
    if not (args.sig or args.signal):
        raise SystemExit("[error] podaj --sig NAME albo --signal CODE")
    sql = """SELECT universe, started_at, sig_name, symbols, occurrences, win_pct,
                    avg_r, pf, score_mean, score_pos_pct
             FROM v_signal_summary WHERE 1=1"""
    if args.sig:
        sql += eq_nocase("sig_name", args.sig)
    if args.signal:
        sql += eq_nocase("signal_code", args.signal)
    universe = universe_arg(args.universe)
    if universe:
        sql += eq_nocase("universe", universe)
    sql += " ORDER BY sig_name, universe, started_at"
    rows = [dict(r) for r in con.execute(sql)]
    emit(args, rows, None, 2, args.limit or 100)


def cmd_variants(con, args):
    sql = """SELECT s.code AS signal_code, v.sig_name, v.role, v.params_source,
                    v.params_json, p.params
             FROM variant v
             JOIN signal s ON s.id = v.signal_id
             LEFT JOIN v_variant_params p ON p.variant_id = v.id
             WHERE 1=1"""
    if args.signal:
        sql += eq_nocase("s.code", args.signal)
    if args.sig:
        sql += eq_nocase("v.sig_name", args.sig)
    sql += " ORDER BY s.code, v.sig_name"
    rows = [dict(r) for r in con.execute(sql)]
    if args.json:
        emit(args, rows)
        return
    for r in rows:
        print(f"{r['signal_code']:>12}  {r['sig_name']:<14} [{r['role']:<10}] "
              f"{r['params'] or '(parametry skryptu)'}")


def cmd_params(con, args):
    if not (args.sig or args.signal):
        raise SystemExit("[error] podaj --sig NAME albo --signal CODE")
    sql = """SELECT v.sig_name, s.code AS signal_code, v.role, vp.name, vp.type,
                    vp.value_num, vp.value_bool, vp.value_text
             FROM variant_param vp
             JOIN variant v ON v.id = vp.variant_id
             JOIN signal s ON s.id = v.signal_id
             WHERE 1=1"""
    if args.sig:
        sql += eq_nocase("v.sig_name", args.sig)
    if args.signal:
        sql += eq_nocase("s.code", args.signal)
    sql += " ORDER BY v.sig_name, vp.name"
    rows = []
    for r in con.execute(sql):
        d = dict(r)
        d["value"] = (d.pop("value_num") if d["value_num"] is not None else
                      (bool(d["value_bool"]) if d["value_bool"] is not None else d["value_text"]))
        rows.append(d)
    emit(args, rows, ["sig_name", "signal_code", "role", "name", "type", "value"])


def cmd_company(con, args):
    rows = [dict(r) for r in con.execute(
        "SELECT * FROM v_company_card WHERE ticker = ? COLLATE NOCASE", (args.ticker,))]
    if not rows:
        print(f"(brak spółki {args.ticker} w bazie)")
        return
    if args.json:
        emit(args, rows)
        return
    r = rows[0]
    for k, v in r.items():
        if v is not None:
            print(f"  {k:24s} {v}")
    groups = [g[0] for g in con.execute(
        """SELECT umg.grp FROM universe_member_group umg
           JOIN instrument i ON i.id = umg.instrument_id
           WHERE i.ticker = ? COLLATE NOCASE ORDER BY umg.grp""", (args.ticker,))]
    if groups:
        print(f"  {'grupy':24s} {', '.join(groups)}")
    unis = [u[0] for u in con.execute(
        """SELECT u.code FROM universe_member um
           JOIN universe u ON u.id = um.universe_id
           JOIN instrument i ON i.id = um.instrument_id
           WHERE i.ticker = ? COLLATE NOCASE ORDER BY u.code""", (args.ticker,))]
    if unis:
        print(f"  {'uniwersa':24s} {', '.join(unis)}")


def cmd_companies(con, args):
    sql = """SELECT i.ticker, i.exchange, p.sector, p.industry, p.bench_index,
                    p.years_on_exchange, cm.snapshot_date, cm.market_cap_m,
                    cm.adr_pct, cm.avg_turnover_m, cm.sharpe
             FROM instrument i
             LEFT JOIN company_profile p ON p.instrument_id = i.id
             LEFT JOIN company_metric cm ON cm.instrument_id = i.id
                  AND cm.snapshot_date = (SELECT MAX(snapshot_date) FROM company_metric
                                          WHERE instrument_id = i.id)
             WHERE 1=1"""
    if args.sector:
        sql += f" AND p.sector LIKE {lit('%' + args.sector + '%')}"
    sql += f" ORDER BY i.ticker LIMIT {int(args.limit or 50)}"
    emit(args, [dict(r) for r in con.execute(sql)])


def cmd_gaps(con, args):
    universe = universe_arg(args.universe)
    sql = "SELECT * FROM v_run_gaps WHERE 1=1"
    if universe:
        sql += eq_nocase("universe", universe)
    sql += f" ORDER BY run_id, ticker LIMIT {int(args.limit or 60)}"
    emit(args, [dict(r) for r in con.execute(sql)])


def cmd_runs_detail(con, args):
    sql = """SELECT r.out_csv, u.code AS universe, r.indicator_title, m.status,
                    COUNT(*) AS pomiary
             FROM measurement m
             JOIN run r ON r.id = m.run_id
             LEFT JOIN universe u ON u.id = r.universe_id
             GROUP BY r.id, m.status ORDER BY r.started_at, u.code, m.status"""
    emit(args, [dict(r) for r in con.execute(sql)])


SCREEN_METRICS = ("score_mean", "avg_r", "pf", "win_pct", "score_pos_pct",
                  "median_avg_r", "occurrences", "symbols")


def cmd_screen(con, args):
    """Screening: wyniki sygnałów na spółkach spełniających kryteria fundamentów."""
    universe = universe_arg(args.universe)
    where = ["cs.status IN ('ok','no_signal')"]
    if universe:
        where.append(f"cs.universe = {lit(universe)}")
    if args.signal:
        where.append(f"cs.signal_code = {lit(args.signal)} COLLATE NOCASE")
    if args.sig:
        where.append(f"cs.sig_name = {lit(args.sig)} COLLATE NOCASE")
    if args.min_mcap is not None:
        where.append(f"cs.market_cap_m >= {float(args.min_mcap)}")
    if args.max_mcap is not None:
        where.append(f"cs.market_cap_m <= {float(args.max_mcap)}")
    if args.bucket:
        buckets = [b.strip() for b in args.bucket.split(",") if b.strip()]
        where.append("cs.mcap_bucket IN (%s)" % ",".join(lit(b) for b in buckets))
    if args.min_adr is not None:
        where.append(f"cs.adr_pct >= {float(args.min_adr)}")
    if args.max_adr is not None:
        where.append(f"cs.adr_pct <= {float(args.max_adr)}")
    if args.min_turnover is not None:
        where.append(f"cs.avg_turnover_m >= {float(args.min_turnover)}")
    if args.min_sharpe is not None:
        where.append(f"cs.sharpe >= {float(args.min_sharpe)}")
    if args.min_years is not None:
        where.append(f"cs.years_on_exchange >= {int(args.min_years)}")
    if args.sector:
        where.append(f"cs.sector LIKE {lit('%' + args.sector + '%')}")
    if args.industry:
        where.append(f"cs.industry LIKE {lit('%' + args.industry + '%')}")
    if args.only_known_mcap:
        where.append("cs.market_cap_m IS NOT NULL")
    if args.require_company:
        where.append("cs.snapshot_date IS NOT NULL")

    by = args.by if args.by in SCREEN_METRICS else "score_mean"
    min_occ = int(args.min_occ or 0)
    sql = f"""
    WITH latest AS (
        SELECT * FROM (
            SELECT cs.*, ROW_NUMBER() OVER (
                       PARTITION BY cs.run_id, cs.instrument_id, cs.variant_id
                       ORDER BY cs.grp) AS rn
            FROM v_company_signal cs
            JOIN v_run_latest l ON l.id = cs.run_id
            WHERE {' AND '.join(where)}
        ) WHERE rn = 1
    ),
    agg AS (
        SELECT
            universe, signal_code, sig_name, role,
            COUNT(CASE WHEN status = 'ok' THEN 1 END) AS symbols,
            CAST(COALESCE(SUM(CASE WHEN status = 'ok' THEN n END), 0) AS INTEGER)
                AS occurrences,
            SUM(CASE WHEN status='ok' AND win_pct IS NOT NULL THEN win_pct * n END)
                / NULLIF(SUM(CASE WHEN status='ok' THEN n END), 0)      AS win_pct,
            SUM(CASE WHEN status='ok' AND avg_r IS NOT NULL THEN avg_r * n END)
                / NULLIF(SUM(CASE WHEN status='ok' THEN n END), 0)      AS avg_r,
            CASE WHEN COUNT(sum_win_r) > 0 OR COUNT(sum_loss_r) > 0
                 THEN CASE WHEN COALESCE(SUM(sum_loss_r), 0) < 0
                           THEN SUM(sum_win_r) / ABS(SUM(sum_loss_r)) END
            END                                                         AS pf,
            AVG(CASE WHEN status='ok' THEN score END)                   AS score_mean,
            100.0 * COUNT(CASE WHEN status='ok' AND score > 0 THEN 1 END)
                  / NULLIF(COUNT(CASE WHEN status='ok' AND score IS NOT NULL
                                      THEN 1 END), 0)                   AS score_pos_pct
        FROM latest
        GROUP BY universe, signal_code, sig_name, role
    ),
    med AS (
        SELECT universe, sig_name, AVG(avg_r) AS median_avg_r FROM (
            SELECT universe, sig_name, avg_r,
                   ROW_NUMBER() OVER (PARTITION BY universe, sig_name
                                      ORDER BY avg_r) AS rn,
                   COUNT(*)     OVER (PARTITION BY universe, sig_name) AS cnt
            FROM latest WHERE status = 'ok' AND avg_r IS NOT NULL
        ) WHERE rn IN ((cnt + 1) / 2, (cnt + 2) / 2)
        GROUP BY universe, sig_name
    )
    SELECT a.universe, a.signal_code, a.sig_name, a.role, a.symbols,
           a.occurrences, a.win_pct, a.avg_r, a.pf, a.score_mean,
           a.score_pos_pct, m.median_avg_r
    FROM agg a
    LEFT JOIN med m ON m.universe = a.universe AND m.sig_name = a.sig_name
    WHERE a.occurrences >= {min_occ}
    ORDER BY a.{by} DESC NULLS LAST, a.occurrences DESC
    """
    rows = [dict(r) for r in con.execute(sql)]
    if not args.json:
        active = " ".join(f"{k}={v}" for k, v in vars(args).items()
                          if k in ("universe", "signal", "sig", "min_mcap", "max_mcap",
                                   "bucket", "min_adr", "max_adr", "min_turnover",
                                   "min_sharpe", "min_years", "sector", "industry",
                                   "min_occ", "only_known_mcap", "require_company")
                          and v not in (None, False, 0))
        print(f"# screen: {active or '(bez filtrów)'}  | sortowanie: {by} DESC")
    emit(args, rows, None, 2, args.limit or 40)


def cmd_schema(con, args):
    for kind in ("table", "view"):
        names = [r[0] for r in con.execute(
            "SELECT name FROM sqlite_master WHERE type=? AND name NOT LIKE 'sqlite_%' "
            "ORDER BY name", (kind,))]
        print(f"{kind.upper()}S ({len(names)}):")
        for n in names:
            print(f"  {n}")
        print()


def cmd_sql(con, args):
    sql = args.query.strip()
    if not sql.lower().startswith(("select", "with", "pragma", "explain")):
        raise SystemExit("[error] dozwolone są tylko zapytania czytające "
                         "(SELECT/WITH/PRAGMA/EXPLAIN)")
    cur = con.execute(sql)
    rows = [dict(r) for r in cur.fetchmany(int(args.limit or 500))]
    emit(args, rows)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_parser():
    ap = argparse.ArgumentParser(description="Zapytania do bazy analiz sygnałów",
                                 formatter_class=argparse.RawDescriptionHelpFormatter,
                                 epilog=__doc__.split("Przykłady:")[-1])
    ap.add_argument("--db", default=str(DEFAULT_DB))
    ap.add_argument("--json", action="store_true", help="wyjście JSON")
    ap.add_argument("--limit", type=int, default=0, help="limit wierszy wyjścia")
    sub = ap.add_subparsers(dest="cmd", required=True)

    def add_common(p):
        p.add_argument("--universe", help="GPW_NC/GPW, US_BIG/US, ALL")
        p.add_argument("--signal", help="kod sygnału bazowego, np. CapLow")
        p.add_argument("--sig", help="nazwa wariantu, np. capLowTFT_95")
        p.add_argument("--min-occ", type=int, default=0, dest="min_occ")
        p.add_argument("--limit", type=int, default=argparse.SUPPRESS,
                       help="limit wierszy wyjścia")

    p = sub.add_parser("runs", help="lista runów")
    p.add_argument("--limit", type=int, default=argparse.SUPPRESS)
    p.set_defaults(func=cmd_runs)

    p = sub.add_parser("summary", help="podsumowanie sygnałów")
    add_common(p)
    p.add_argument("--all", action="store_true", help="wszystkie uniwersa razem")
    p.add_argument("--sort", default="score_mean", help="kolumna sortowania")
    p.set_defaults(func=cmd_summary)

    p = sub.add_parser("top", help="najlepsze warianty")
    add_common(p)
    p.add_argument("--by", default="score_mean", help="metryka: " + ", ".join(SORT_COLS))
    p.set_defaults(func=cmd_top)

    p = sub.add_parser("compare", help="oryginał vs replika vs najlepszy wariant")
    add_common(p)
    p.set_defaults(func=cmd_compare)

    p = sub.add_parser("screen",
                       help="screening: sygnały na spółkach wg kryteriów fundamentów")
    add_common(p)
    p.add_argument("--min-mcap", type=float, dest="min_mcap",
                   help="min. kapitalizacja [M]")
    p.add_argument("--max-mcap", type=float, dest="max_mcap",
                   help="max. kapitalizacja [M]")
    p.add_argument("--bucket", help="kubełki MCap: micro,small,mid,large,mega,unknown")
    p.add_argument("--min-adr", type=float, dest="min_adr", help="min. ADR [%%]")
    p.add_argument("--max-adr", type=float, dest="max_adr", help="max. ADR [%%]")
    p.add_argument("--min-turnover", type=float, dest="min_turnover",
                   help="min. średni obrót [M]")
    p.add_argument("--min-sharpe", type=float, dest="min_sharpe")
    p.add_argument("--min-years", type=int, dest="min_years",
                   help="min. staż na giełdzie [lata]")
    p.add_argument("--sector", help="filtr sektora (LIKE)")
    p.add_argument("--industry", help="filtr przemysłu (LIKE)")
    p.add_argument("--only-known-mcap", action="store_true", dest="only_known_mcap",
                   help="pomiń spółki bez danych o kapitalizacji")
    p.add_argument("--require-company", action="store_true", dest="require_company",
                   help="tylko spółki z danymi DRE Info")
    p.add_argument("--by", default="score_mean",
                   help="metryka sortowania: " + ", ".join(SCREEN_METRICS))
    p.set_defaults(func=cmd_screen)

    p = sub.add_parser("trend", help="historia wariantu w runach")
    add_common(p)
    p.set_defaults(func=cmd_trend)

    p = sub.add_parser("variants", help="warianty i ich parametry")
    add_common(p)
    p.set_defaults(func=cmd_variants)

    p = sub.add_parser("params", help="parametry wariantów")
    add_common(p)
    p.set_defaults(func=cmd_params)

    p = sub.add_parser("company", help="karta spółki (DRE Info)")
    p.add_argument("ticker")
    p.set_defaults(func=cmd_company)

    p = sub.add_parser("companies", help="lista spółek")
    p.add_argument("--sector", help="filtr sektora")
    p.add_argument("--limit", type=int, default=argparse.SUPPRESS)
    p.set_defaults(func=cmd_companies)

    p = sub.add_parser("gaps", help="symbole nieodczytane (NO_DATA)")
    p.add_argument("--universe")
    p.add_argument("--limit", type=int, default=argparse.SUPPRESS)
    p.set_defaults(func=cmd_gaps)

    p = sub.add_parser("runs_detail", help="statusy pomiarów w runach")
    p.add_argument("--limit", type=int, default=argparse.SUPPRESS)
    p.set_defaults(func=cmd_runs_detail)

    p = sub.add_parser("schema", help="tabele i widoki")
    p.set_defaults(func=cmd_schema)

    p = sub.add_parser("sql", help="dowolne zapytanie czytające")
    p.add_argument("query")
    p.add_argument("--limit", type=int, default=argparse.SUPPRESS)
    p.set_defaults(func=cmd_sql)
    return ap


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    db_path = Path(args.db)
    if not db_path.exists():
        print(f"[error] brak bazy {db_path} - uruchom scripts/db_init.py",
              file=sys.stderr)
        return 1
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    try:
        args.func(con, args)
    except BrokenPipeError:
        # np. `... | head` zamyka potok - bez brzydkiego tracebacku
        try:
            devnull = os.open(os.devnull, os.O_WRONLY)
            os.dup2(devnull, sys.stdout.fileno())
        except OSError:
            pass
        return 0
    except sqlite3.Error as exc:
        print(f"[sql error] {exc}", file=sys.stderr)
        return 1
    finally:
        con.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
