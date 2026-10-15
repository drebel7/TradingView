#!/usr/bin/env python3
"""
db_import_analysis.py
=====================
Importuje surowe wyniki scrapera z `analysis/*.csv` do bazy `db/analysis.db`.

Zasila tabele:
  * universe / instrument / universe_member - z pliku watchlisty (skład aktualny),
  * run / run_symbol  - jeden run na plik CSV (+ status symboli: ok / no_data),
  * measurement       - jeden wiersz na (run, spółka, wariant sygnału).

Reguły:
  * plik `<UNIWERSUM>_<TAG>_<YYYYMMDD>.csv` -> run (klucz naturalny: ścieżka CSV),
  * nagłówki `# indicator:` / `# watchlist:` / `# generated:` -> metadane runu,
  * `sig = NO_DATA` -> run_symbol.status='no_data' (nie tworzy pomiarów),
  * `n > 0` -> measurement.status='ok', puste `n` -> 'no_signal',
  * `pf = ∞`/puste -> NULL,
  * import jest idempotentny: pomiary runu są odtwarzane od zera.

Opcje:
  --salvage-timeouts  odzyskuje dane z wierszy NO_DATA, które mimo timeoutu
                      niosą kompletną tabelę (`rows` w komunikacie); trafiają
                      jako measurement.status='recovered' + run_symbol 'recovered'
                      i celowo NIE wchodzą do widoków podsumowań,
  --verify            po imporcie porównuje widoki z plikami *_SUMMARY*.csv,
  --dry-run           nic nie zapisuje.

Usage:
  python3 scripts/db_import_analysis.py
  python3 scripts/db_import_analysis.py --verify
  python3 scripts/db_import_analysis.py --dir analysis --salvage-timeouts
"""

import argparse
import ast
import csv
import datetime as dt
import hashlib
import json
import re
import sqlite3
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = REPO_ROOT / "db" / "analysis.db"
DEFAULT_DIR = REPO_ROOT / "analysis"

# Uniwersa rozpoznawane po prefiksie nazwy pliku CSV
UNIVERSES = {
    "GPW_NC": "GPW NewConnect + grupy GPW",
    "US_BIG": "Akcje USA (duże spółki)",
}

RAW_FILE_RE = re.compile(r"^(?P<tag>[A-Z0-9]+)_(?P<date>\d{8})\.csv$")
NUM_METRICS = ("win_pct", "avg_r", "pf", "max_dd", "score", "sum_win_r", "sum_loss_r")
CELL_METRICS = ("win_pct", "n", "avg_r", "pf", "max_dd", "score", "sum_win_r", "sum_loss_r")

# Statusy, dla których surowy tekst wiersza jest zapisywany mimo --keep-raw
KEEP_RAW_STATUSES = ("no_data", "recovered", "fail")


# ---------------------------------------------------------------------------
# Wejście: nagłówki i wiersze CSV
# ---------------------------------------------------------------------------

def read_scraper_csv(path: Path):
    """Zwraca (meta, fieldnames, rows). Meta z linii '# klucz: wartość'."""
    meta, body = {}, []
    with open(path, newline="", encoding="utf-8", errors="replace") as f:
        for line in f:
            if line.startswith("#"):
                m = re.match(r"#\s*([A-Za-z_ ]+):\s*(.*)", line)
                if m:
                    meta[m.group(1).strip()] = m.group(2).strip()
                continue
            body.append(line)
    if not body:
        return meta, [], []
    reader = csv.DictReader(body)
    return meta, reader.fieldnames or [], list(reader)


def parse_watchlist(path: Path):
    """Zwraca (lista (grupa, ticker), sha256) wg formatu scrapera."""
    content = path.read_text(encoding="utf-8", errors="replace")
    sha = hashlib.sha256(content.encode("utf-8")).hexdigest()
    out, group = [], "UNKNOWN"
    for item in (x.strip() for x in content.split(",")):
        if not item:
            continue
        if item.startswith("###"):
            group = item[3:].strip()
        else:
            out.append((group, item))
    return out, sha


def fnum(value):
    if value is None:
        return None
    t = str(value).strip()
    if t in ("", "∞", "-∞", "inf", "-inf", "nan", "NaN"):
        return None
    try:
        return float(t)
    except ValueError:
        return None


def salvage_rows(note: str):
    """Wyciąga listę wierszy tabeli z komunikatu timeoutu (jeśli jest)."""
    i = note.find("'rows':")
    if i < 0:
        return None
    j = note.find("[", i)
    if j < 0:
        return None
    depth = 0
    k = j
    while k < len(note):
        ch = note[k]
        if ch == "[":
            depth += 1
        elif ch == "]":
            depth -= 1
            if depth == 0:
                break
        k += 1
    try:
        rows = ast.literal_eval(note[j:k + 1])
    except (ValueError, SyntaxError):
        return None
    return rows if isinstance(rows, list) and rows else None


# ---------------------------------------------------------------------------
# Zapis do bazy
# ---------------------------------------------------------------------------

def get_or_create_universe(con, code, watchlist_path):
    con.execute(
        """INSERT INTO universe(code, watchlist_path, description) VALUES (?,?,?)
           ON CONFLICT(code) DO UPDATE SET
               watchlist_path=COALESCE(excluded.watchlist_path, universe.watchlist_path),
               description=COALESCE(universe.description, excluded.description)""",
        (code, watchlist_path, UNIVERSES.get(code)))
    return con.execute("SELECT id FROM universe WHERE code=?", (code,)).fetchone()[0]


def get_or_create_instrument(con, ticker):
    con.execute("INSERT OR IGNORE INTO instrument(ticker, exchange) VALUES (?,?)",
                (ticker, ticker.split(":", 1)[0] if ":" in ticker else None))
    return con.execute("SELECT id FROM instrument WHERE ticker=?", (ticker,)).fetchone()[0]


def update_members(con, universe_id, members, run_id):
    for grp, ticker in members:
        iid = get_or_create_instrument(con, ticker)
        con.execute(
            """INSERT INTO universe_member(universe_id, instrument_id,
                                           first_seen_run_id, last_seen_run_id)
               VALUES (?,?,?,?)
               ON CONFLICT(universe_id, instrument_id) DO UPDATE SET
                   last_seen_run_id=excluded.last_seen_run_id""",
            (universe_id, iid, run_id, run_id))
        con.execute(
            """INSERT OR IGNORE INTO universe_member_group(universe_id, instrument_id, grp)
               VALUES (?,?,?)""",
            (universe_id, iid, grp or ""))


def script_inputs_json(con, script_id):
    """Snapshot domyślnych inputów skryptu (konfiguracja pomiaru)."""
    inputs = {}
    for name, num, boolean, text in con.execute(
            """SELECT name, value_num, value_bool, value_text FROM script_param
               WHERE script_id=? ORDER BY name""", (script_id,)):
        inputs[name] = num if num is not None else (
            bool(boolean) if boolean is not None else text)
    return json.dumps({"inputs": inputs}, ensure_ascii=False, sort_keys=True)


def import_csv(con, path: Path, salvage: bool, keep_raw: bool, stats: dict):
    meta, fieldnames, rows = read_scraper_csv(path)
    try:
        rel = str(path.relative_to(REPO_ROOT))
    except ValueError:      # plik spoza repo (np. testy w katalogu tymczasowym)
        rel = str(path)
    if not rows:
        stats["skipped"].append(f"{rel}: brak wierszy danych")
        return

    universe_code = next((c for c in UNIVERSES if path.name.startswith(c + "_")), None)
    if universe_code is None:
        stats["skipped"].append(f"{rel}: nierozpoznane uniwersum")
        return
    tag = path.name[len(universe_code) + 1:]

    indicator = meta.get("indicator", "")
    watchlist_path = meta.get("watchlist", "")
    generated = meta.get("generated") or dt.datetime.fromtimestamp(
        path.stat().st_mtime).replace(microsecond=0).isoformat()

    # --- skrypt i jego wersja ---------------------------------------------
    row = con.execute(
        "SELECT id FROM script WHERE title=? COLLATE NOCASE", (indicator,)).fetchone()
    if row is None:
        stats["skipped"].append(
            f"{rel}: brak skryptu o tytule '{indicator}' (uruchom db_import_scripts.py)")
        return
    script_id = row[0]
    rev = con.execute(
        """SELECT id FROM script_revision WHERE script_id=?
           ORDER BY id DESC LIMIT 1""", (script_id,)).fetchone()
    revision_id = rev[0] if rev else None

    # --- progress JSON -----------------------------------------------------
    # Scraper zapisuje .<TAG>_progress.json (TAG bez daty), a plik wyniku to
    # <UNIWERSUM>_<TAG>_<YYYYMMDD>.csv - sprawdzamy oba warianty nazwy.
    progress_candidates = [
        path.parent / f".{path.stem}_progress.json",
        path.parent / f".{path.stem[:-9]}_progress.json" if path.stem[-9:-8] == "_" else None,
    ]
    progress_path = next((p for p in progress_candidates if p and p.exists()), None)
    ok_cnt = fail_cnt = None
    finished_at = None
    if progress_path:
        try:
            prog = json.loads(progress_path.read_text(encoding="utf-8"))
            ok_cnt, fail_cnt = prog.get("ok"), prog.get("fail")
            finished_at = prog.get("updated")
        except (ValueError, OSError):
            pass

    # --- watchlista (skład aktualny) --------------------------------------
    watchlist = Path(watchlist_path) if watchlist_path else None
    if watchlist and not watchlist.is_absolute():
        watchlist = REPO_ROOT / watchlist_path
    members, wl_sha = [], None
    if watchlist and watchlist.exists():
        members, wl_sha = parse_watchlist(watchlist)

    # --- run ---------------------------------------------------------------
    universe_id = get_or_create_universe(con, universe_code, watchlist_path or None)
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
               watchlist_path=excluded.watchlist_path,
               watchlist_sha256=excluded.watchlist_sha256,
               config_json=excluded.config_json, ok=excluded.ok, fail=excluded.fail,
               notes=excluded.notes""",
        (generated, finished_at, universe_id, script_id, revision_id, indicator,
         None, watchlist_path or None, wl_sha, None,
         script_inputs_json(con, script_id), ok_cnt, fail_cnt, rel, tag))
    run_id = con.execute("SELECT id FROM run WHERE out_csv=?", (rel,)).fetchone()[0]

    # idempotencja: odtwórz pomiary i statusy symboli tego runu
    con.execute("DELETE FROM measurement WHERE run_id=?", (run_id,))
    con.execute("DELETE FROM run_symbol WHERE run_id=?", (run_id,))

    if members:
        update_members(con, universe_id, members, run_id)

    # --- warianty i pomiary ------------------------------------------------
    variants = {r[0]: r[1] for r in con.execute("SELECT sig_name, id FROM variant")}
    instruments = {r[0]: r[1] for r in con.execute("SELECT ticker, id FROM instrument")}

    batch, symbol_rows = [], {}
    for r in rows:
        ticker = (r.get("symbol") or "").strip()
        sig = (r.get("sig") or "").strip()
        grp = (r.get("group") or "").strip()
        if not ticker:
            continue
        iid = instruments.get(ticker) or get_or_create_instrument(con, ticker)
        instruments[ticker] = iid

        if sig == "NO_DATA" or not sig:
            note = (r.get("raw") or "").strip() or "brak danych"
            recovered = salvage_rows(note) if salvage else None
            if recovered:
                symbol_rows[(iid, grp)] = ("recovered", note[:500])
                for cells in recovered:
                    name = (cells[0] if cells else "").strip()
                    if not name or name == "sig" or name not in variants:
                        continue
                    vals = {k: fnum(cells[i + 1]) for i, k in enumerate(CELL_METRICS)}
                    batch.append((
                        run_id, iid, variants[name], grp, "recovered",
                        int(vals["n"]) if vals["n"] else None,
                        vals["win_pct"], vals["avg_r"], vals["pf"], vals["max_dd"],
                        vals["score"], vals["sum_win_r"], vals["sum_loss_r"],
                        " | ".join(str(c) for c in cells)))
                    stats["recovered"] += 1
            else:
                symbol_rows[(iid, grp)] = ("no_data", note[:500])
                stats["no_data"] += 1
            continue

        vid = variants.get(sig)
        if vid is None:
            stats["unknown_sigs"].add(sig)
            continue
        n = fnum(r.get("n"))
        status = "ok" if (n and n > 0) else "no_signal"
        raw_text = (r.get("raw") or "").strip() or None
        # raw trzymamy tylko tam, gdzie niesie informację ponad metryki
        # (diagnostyka NO_DATA/recovered/fail); pełny zapis: --keep-raw.
        if not keep_raw and status not in KEEP_RAW_STATUSES:
            raw_text = None
        batch.append((
            run_id, iid, vid, grp, status,
            int(n) if n is not None else None,
            fnum(r.get("win_pct")), fnum(r.get("avg_r")), fnum(r.get("pf")),
            fnum(r.get("max_dd")), fnum(r.get("score")),
            fnum(r.get("sum_win_r")), fnum(r.get("sum_loss_r")),
            raw_text))
        if status == "ok":
            stats["measurements_ok"] += 1
        else:
            stats["measurements_no_signal"] += 1
        symbol_rows.setdefault((iid, grp), ("ok", None))

    con.executemany(
        """INSERT OR REPLACE INTO measurement(run_id, instrument_id, variant_id,
               grp, status, n, win_pct, avg_r, pf, max_dd, score,
               sum_win_r, sum_loss_r, raw)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", batch)
    con.executemany(
        """INSERT OR REPLACE INTO run_symbol(run_id, instrument_id, grp, status, note)
           VALUES (?,?,?,?,?)""",
        [(run_id, iid, grp, st, note) for (iid, grp), (st, note) in symbol_rows.items()])

    stats["runs"] += 1
    stats["measurements"] += len(batch)
    stats["files"].append((rel, len(rows), len(batch)))


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(description="Import surowych CSV do bazy analiz")
    ap.add_argument("--db", default=str(DEFAULT_DB))
    ap.add_argument("--dir", default=str(DEFAULT_DIR), help="katalog z CSV scrapera")
    ap.add_argument("--salvage-timeouts", action="store_true",
                    help="odzyskaj dane z wierszy NO_DATA (status 'recovered')")
    ap.add_argument("--verify", action="store_true",
                    help="po imporcie porównaj widoki z plikami *_SUMMARY*.csv")
    ap.add_argument("--keep-raw", action="store_true",
                    help="zapisuj surowy wiersz CSV dla wszystkich pomiarów "
                         "(domyślnie tylko diagnostyka: NO_DATA/recovered/fail)")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    db_path = Path(args.db)
    if not db_path.exists():
        print(f"[error] brak bazy {db_path} - uruchom scripts/db_init.py", file=sys.stderr)
        return 1

    csv_dir = Path(args.dir)
    files = []
    for p in sorted(csv_dir.glob("*.csv")):
        for code in UNIVERSES:
            if p.name.startswith(code + "_"):
                tag = p.name[len(code) + 1:]
                if RAW_FILE_RE.match(tag):
                    files.append(p)
                break
    if not files:
        print(f"[error] brak plików CSV scrapera w {csv_dir}", file=sys.stderr)
        return 1

    stats = {"runs": 0, "measurements": 0, "measurements_ok": 0,
             "measurements_no_signal": 0, "no_data": 0, "recovered": 0,
             "unknown_sigs": set(), "skipped": [], "files": []}

    con = sqlite3.connect(db_path)
    con.execute("PRAGMA foreign_keys = ON")
    try:
        with con:
            for path in files:
                import_csv(con, path, args.salvage_timeouts, args.keep_raw, stats)
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
        con.execute("VACUUM")   # trzymaj commitowany plik bazy w ryzach
        con.commit()

    print(f"[ok] runy: {stats['runs']}  pomiary: {stats['measurements']} "
          f"(ok: {stats['measurements_ok']}, bez sygnału: {stats['measurements_no_signal']})")
    print(f"     symbole bez danych: {stats['no_data']}"
          + (f"  odzyskane: {stats['recovered']}" if stats["recovered"] else ""))
    if stats["unknown_sigs"]:
        print(f"     [warn] nieznane sygnały (pominięte): {sorted(stats['unknown_sigs'])}")
    for s in stats["skipped"]:
        print(f"     [skip] {s}")

    if args.verify:
        import db_verify
        db_verify.main(["--db", str(db_path), "--dir", str(csv_dir)])
    con.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
