#!/usr/bin/env python3
"""
db_import_company.py
====================
Importuje wyniki scrapera DRE Info (`analysis/*_INFO_*.csv`, patrz
`scripts/tv_info_scraper.py`) do tabel spółek w `db/analysis.db`:

  * instrument        - spółka (ticker z watchlisty),
  * company_profile   - cechy: sector, industry, bench_index, years_on_exchange,
  * company_metric    - snapshot dzienny: ADR%, ATR, turnover, HoD/LoD, LoD dist,
                        Dtt vol/time, percentyle MA, Sharpe, EPS 1y/2y,
                        nBroken extremes (+ mod) i bench_mod,
  * run / run_symbol  - provenance (data, uniwersum, watchlista, ok/fail),
  * universe_member(_group) - skład uniwersum z watchlisty.

Plik rozpoznawany jest po pierwszej linii (`# TradingView DRE Info scraper
results v1`), a nie po nazwie. `snapshot_date` bierze się z nagłówka
`# generated:` (albo z --date).

Usage:
  python3 scripts/db_import_company.py
  python3 scripts/db_import_company.py --date 2026-10-14 --dry-run
"""

import argparse
import csv
import json
import re
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

import db_import_analysis as dia   # reużycie: uniwersa, instrumenty, watchlisty
import tv_info_scraper as tis      # wspólna definicja wymuszonych inputów

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = REPO_ROOT / "db" / "analysis.db"
DEFAULT_DIR = REPO_ROOT / "analysis"

# znacznik nagłówka CSV - jedno źródło prawdy (scraper i importer muszą się zgadzać)
HEADER_MARKER = tis.HEADER_MARKER

METRIC_NUM = ["market_cap_m", "adr_pct", "atr", "avg_turnover_m", "hod_price",
              "sharpe", "n_broken_extremes_pct"]
METRIC_INT = ["eps_up_1y", "eps_days_1y", "eps_up_2y", "eps_days_2y"]
METRIC_TEXT = ["ma_dist_prctl", "bench_mod", "n_broken_mod"]
PROFILE_TEXT = ["sector", "industry", "bench_index"]
PROFILE_INT = ["years_on_exchange"]


def read_info_csv(path: Path):
    meta, rows = {}, []
    with open(path, newline="", encoding="utf-8", errors="replace") as f:
        lines = list(f)
    body = []
    for line in lines:
        if line.startswith("#"):
            m = re.match(r"#\s*([A-Za-z_ ]+):\s*(.*)", line)
            if m:
                meta[m.group(1).strip()] = m.group(2).strip()
            continue
        body.append(line)
    if body:
        rows = list(csv.DictReader(body))
    return meta, rows


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


def fint(value):
    v = fnum(value)
    return int(v) if v is not None else None


def import_file(con, path: Path, date_override, stats: dict):
    meta, rows = read_info_csv(path)
    try:
        rel = str(path.relative_to(REPO_ROOT))
    except ValueError:      # plik spoza repo (np. testy w katalogu tymczasowym)
        rel = str(path)
    if not rows:
        stats["skipped"].append(f"{rel}: brak wierszy danych")
        return

    universe_code = next((c for c in dia.UNIVERSES if path.name.startswith(c + "_")), None)
    if universe_code is None:
        stats["skipped"].append(f"{rel}: nierozpoznane uniwersum")
        return

    generated = meta.get("generated") or datetime.fromtimestamp(
        path.stat().st_mtime).replace(microsecond=0).isoformat()
    snapshot_date = date_override or generated[:10]
    indicator = meta.get("indicator", "DRE Info")
    watchlist_path = meta.get("watchlist", "")

    script_row = con.execute(
        "SELECT id FROM script WHERE title=? COLLATE NOCASE", (indicator,)).fetchone()
    script_id = script_row[0] if script_row else None
    if script_id is None:
        stats["warnings"].append(
            f"{rel}: brak skryptu '{indicator}' w bazie "
            f"(uruchom db_import_scripts.py) - run bez powiązania z kodem")

    revision_id = None
    if script_id is not None:
        rev = con.execute(
            "SELECT id FROM script_revision WHERE script_id=? ORDER BY id DESC LIMIT 1",
            (script_id,)).fetchone()
        revision_id = rev[0] if rev else None

    # watchlista -> skład uniwersum (jak w imporcie runów sygnałowych)
    watchlist = Path(watchlist_path) if watchlist_path else None
    if watchlist and not watchlist.is_absolute():
        watchlist = REPO_ROOT / watchlist_path
    members, wl_sha = [], None
    if watchlist and watchlist.exists():
        members, wl_sha = dia.parse_watchlist(watchlist)

    progress_path = path.parent / f".{path.stem[:-9]}_progress.json"
    ok_cnt = fail_cnt = None
    finished_at = None
    if progress_path.exists():
        try:
            prog = json.loads(progress_path.read_text(encoding="utf-8"))
            ok_cnt, fail_cnt = prog.get("ok"), prog.get("fail")
            finished_at = prog.get("updated")
        except (ValueError, OSError):
            pass

    universe_id = dia.get_or_create_universe(con, universe_code, watchlist_path or None)
    con.execute(
        """INSERT INTO run(started_at, finished_at, universe_id, script_id,
                           script_revision_id, indicator_title, resolution,
                           watchlist_path, watchlist_sha256, scraper_version,
                           config_json, ok, fail, out_csv, notes)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
           ON CONFLICT(out_csv) DO UPDATE SET
               started_at=excluded.started_at, finished_at=excluded.finished_at,
               universe_id=excluded.universe_id, script_id=excluded.script_id,
               script_revision_id=excluded.script_revision_id,
               indicator_title=excluded.indicator_title,
               resolution=excluded.resolution,
               watchlist_path=excluded.watchlist_path,
               watchlist_sha256=excluded.watchlist_sha256,
               config_json=excluded.config_json, ok=excluded.ok, fail=excluded.fail,
               notes=excluded.notes""",
        (generated, finished_at, universe_id, script_id, revision_id, indicator,
         meta.get("resolution"), watchlist_path or None, wl_sha, None,
         _config_json(), ok_cnt, fail_cnt, rel, "DRE Info (company snapshot)"))
    run_id = con.execute("SELECT id FROM run WHERE out_csv=?", (rel,)).fetchone()[0]

    con.execute("DELETE FROM run_symbol WHERE run_id=?", (run_id,))
    if members:
        dia.update_members(con, universe_id, members, run_id)

    now = datetime.now().replace(microsecond=0).isoformat()
    for r in rows:
        ticker = (r.get("symbol") or "").strip()
        if not ticker:
            continue
        iid = dia.get_or_create_instrument(con, ticker)
        raw = (r.get("raw") or "").strip()
        ticker_table = (r.get("ticker_table") or "").strip()
        status = (r.get("status") or "ok").strip().lower()
        if status == "no_data":
            con.execute(
                """INSERT OR REPLACE INTO run_symbol(run_id, instrument_id, grp,
                                                     status, note)
                   VALUES (?,?,?,?,?)""",
                (run_id, iid, (r.get("group") or "").strip(), "no_data",
                 raw[:500] or "brak danych"))
            stats["no_data"] += 1
            continue

        if ticker_table and ticker_table.split(":")[-1].upper() != ticker.split(":")[-1].upper():
            stats["warnings"].append(
                f"{rel}: {ticker}: tabela pokazuje {ticker_table}")

        # --- profil (cechy wolnozmienne) ---
        profile = {k: (r.get(k) or "").strip() or None for k in PROFILE_TEXT}
        profile["years_on_exchange"] = fint(r.get("years_on_exchange"))
        con.execute(
            """INSERT INTO company_profile(instrument_id, sector, industry,
                                           bench_index, years_on_exchange, updated_at)
               VALUES (?,?,?,?,?,?)
               ON CONFLICT(instrument_id) DO UPDATE SET
                   sector=COALESCE(excluded.sector, company_profile.sector),
                   industry=COALESCE(excluded.industry, company_profile.industry),
                   bench_index=COALESCE(excluded.bench_index, company_profile.bench_index),
                   years_on_exchange=COALESCE(excluded.years_on_exchange,
                                              company_profile.years_on_exchange),
                   updated_at=excluded.updated_at""",
            (iid, profile["sector"], profile["industry"], profile["bench_index"],
             profile["years_on_exchange"], now))

        # --- snapshot dzienny ---
        cols = (["instrument_id", "snapshot_date", "run_id"]
                + METRIC_NUM + METRIC_INT + METRIC_TEXT + ["config_json"])
        vals = ([iid, snapshot_date, run_id]
                + [fnum(r.get(c)) for c in METRIC_NUM]
                + [fint(r.get(c)) for c in METRIC_INT]
                + [(r.get(c) or "").strip() or None for c in METRIC_TEXT]
                + [_config_json()])
        placeholders = ",".join("?" * len(cols))
        con.execute(f"INSERT OR REPLACE INTO company_metric({','.join(cols)}) "
                    f"VALUES ({placeholders})", vals)

        con.execute(
            """INSERT OR REPLACE INTO run_symbol(run_id, instrument_id, grp,
                                                 status, note)
               VALUES (?,?,?,?,?)""",
            (run_id, iid, (r.get("group") or "").strip(), "ok", None))
        stats["metrics"] += 1

    stats["runs"] += 1
    stats["files"].append((rel, len(rows)))


def _config_json():
    """Konfiguracja pomiaru DRE Info (inputy wymuszone przez scraper)."""
    return json.dumps({"inputs": tis.INFO_INPUT_OVERRIDES}, ensure_ascii=False,
                      sort_keys=True)


def find_info_files(directory: Path):
    out = []
    for p in sorted(directory.glob("*.csv")):
        try:
            with open(p, "r", encoding="utf-8", errors="replace") as f:
                if f.readline().strip() == HEADER_MARKER:
                    out.append(p)
        except OSError:
            continue
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Import DRE Info CSV do bazy (spółki)")
    ap.add_argument("--db", default=str(DEFAULT_DB))
    ap.add_argument("--dir", default=str(DEFAULT_DIR))
    ap.add_argument("--date", default=None, help="nadpisz snapshot_date (YYYY-MM-DD)")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    db_path = Path(args.db)
    if not db_path.exists():
        print(f"[error] brak bazy {db_path} - uruchom scripts/db_init.py", file=sys.stderr)
        return 1

    files = find_info_files(Path(args.dir))
    if not files:
        print(f"[i] brak plików DRE Info w {args.dir} "
              f"(uruchom scripts/tv_info_scraper.py)")
        return 0

    stats = {"runs": 0, "metrics": 0, "no_data": 0, "skipped": [],
             "warnings": [], "files": []}
    con = sqlite3.connect(db_path)
    con.execute("PRAGMA foreign_keys = ON")
    try:
        with con:
            for path in files:
                import_file(con, path, args.date, stats)
            if args.dry_run:
                raise RuntimeError("dry-run")
    except RuntimeError:
        con.rollback()
        print("[dry-run] zmiany wycofane")
    except Exception as exc:
        con.rollback()
        print(f"[error] {exc}", file=sys.stderr)
        return 1

    if not args.dry_run:
        con.execute("VACUUM")
        con.commit()

    print(f"[ok] pliki DRE Info: {stats['runs']}  snapshoty spółek: {stats['metrics']} "
          f"(bez danych: {stats['no_data']})")
    for rel, n in stats["files"]:
        print(f"     {rel}: {n} wierszy")
    for s in stats["skipped"]:
        print(f"     [skip] {s}")
    for w in stats["warnings"][:10]:
        print(f"     [warn] {w}")
    if len(stats["warnings"]) > 10:
        print(f"     ... (+{len(stats['warnings']) - 10} ostrzeżeń)")
    con.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
