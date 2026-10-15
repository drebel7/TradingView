#!/usr/bin/env python3
"""
db_init.py
==========
Tworzy (lub odtwarza) bazę SQLite `db/analysis.db` ze schematu `db/schema.sql`.

Schemat jest idempotentny (CREATE ... IF NOT EXISTS), więc uruchomienie na
istniejącej bazie tylko doniesie brakujące obiekty i ustawi wersję schematu
(PRAGMA user_version). `--force` usuwa plik bazy i tworzy go od zera.

Usage:
  python3 scripts/db_init.py                  # db/analysis.db (domyślnie)
  python3 scripts/db_init.py --db db/x.db
  python3 scripts/db_init.py --force          # skasuj i utwórz od nowa
"""

import argparse
import sqlite3
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = REPO_ROOT / "db" / "analysis.db"
SCHEMA = REPO_ROOT / "db" / "schema.sql"
SCHEMA_VERSION = 2
# v2: company_metric - dodane market_cap_m; usunięte lod_price, lod_dist_pct,
#     dtt_vol_pct, dtt_vol_proj_pct, dtt_time_pct (+ v_company_card)


def init_db(db_path: Path, force: bool = False, schema_path: Path = SCHEMA) -> dict:
    """Tworzy bazę ze schematu; zwraca słownik z licznikami obiektów."""
    if force and db_path.exists():
        for suffix in ("", "-wal", "-shm", "-journal"):
            p = Path(str(db_path) + suffix)
            if p.exists():
                p.unlink()
    db_path.parent.mkdir(parents=True, exist_ok=True)

    sql = schema_path.read_text(encoding="utf-8")
    con = sqlite3.connect(db_path)
    try:
        con.execute("PRAGMA foreign_keys = ON")
        con.executescript(sql)
        con.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
        con.commit()
        stats = {
            "tables": [r[0] for r in con.execute(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND name NOT LIKE 'sqlite_%' ORDER BY name")],
            "views": [r[0] for r in con.execute(
                "SELECT name FROM sqlite_master WHERE type='view' ORDER BY name")],
            "user_version": con.execute("PRAGMA user_version").fetchone()[0],
        }
    finally:
        con.close()
    return stats


def main() -> int:
    ap = argparse.ArgumentParser(description="Tworzy/migruje bazę analiz (SQLite)")
    ap.add_argument("--db", default=str(DEFAULT_DB), help="ścieżka do pliku bazy")
    ap.add_argument("--schema", default=str(SCHEMA), help="ścieżka do schema.sql")
    ap.add_argument("--force", action="store_true",
                    help="skasuj istniejącą bazę i utwórz od nowa")
    args = ap.parse_args()

    db_path = Path(args.db)
    schema_path = Path(args.schema)
    if not schema_path.exists():
        print(f"[error] brak pliku schematu: {schema_path}", file=sys.stderr)
        return 1

    existed = db_path.exists()
    old_version = None
    if existed:
        try:
            con = sqlite3.connect(db_path)
            old_version = con.execute("PRAGMA user_version").fetchone()[0]
            con.close()
        except sqlite3.Error:
            old_version = None
    if existed and not args.force and old_version and old_version < SCHEMA_VERSION:
        print(f"[warn] baza ma schemat v{old_version}, a kod oczekuje v{SCHEMA_VERSION}.",
              file=sys.stderr)
        print("       CREATE TABLE IF NOT EXISTS nie zmienia istniejących tabel,",
              file=sys.stderr)
        print("       więc uruchom: db_init.py --force + importy (baza jest odtwarzalna).",
              file=sys.stderr)
        return 1

    stats = init_db(db_path, args.force, schema_path)
    action = "odtworzona" if args.force else ("zaktualizowana" if existed else "utworzona")
    print(f"[ok] baza {action}: {db_path}")
    print(f"     schemat v{stats['user_version']}: "
          f"{len(stats['tables'])} tabel, {len(stats['views'])} widoków")
    return 0


if __name__ == "__main__":
    sys.exit(main())
