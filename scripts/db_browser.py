#!/usr/bin/env python3
"""
db_browser.py
=============
Lekka przeglądarka bazy `db/analysis.db` w przeglądarce - bez żadnych
zależności (tylko biblioteka standardowa Pythona).

Serwer otwiera bazę w trybie **tylko do odczytu** (`mode=ro`) i udostępnia:

  * listę wszystkich tabel i widoków (+ liczba wierszy, kolumny),
  * stronicowany podgląd danych z sortowaniem i filtrem tekstowym,
  * schemat obiektu (kolumny, typy, klucze, indeksy, SQL),
  * podgląd pełnej wartości komórki (dla długich tekstów, np. kodu Pine),
  * eksport bieżącego widoku do CSV/JSON,
  * zakładkę SQL (tylko zapytania czytające: SELECT/WITH/PRAGMA/EXPLAIN).

UI: `db/browser.html` (serwowany z tego samego procesu).

Usage:
  python3 scripts/db_browser.py                 # http://127.0.0.1:8765
  python3 scripts/db_browser.py --port 9000 --open
  python3 scripts/db_browser.py --db db/analysis.db --host 0.0.0.0
"""

import argparse
import csv
import io
import json
import re
import sqlite3
import sys
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = REPO_ROOT / "db" / "analysis.db"
UI_FILE = REPO_ROOT / "db" / "browser.html"

MAX_LIMIT = 1000
DEFAULT_LIMIT = 100
CELL_MAX_CHARS = 400          # dłuższe teksty w tabeli są obcinane (pełna wartość: /api/value)
SQL_TIME_BUDGET_S = 1.5       # próg przerwania COUNT(*) w zbiorczym /api/counts
SQL_TIME_BUDGET_LONG_S = 8.0  # dłuższy budżet dla pojedynczego obiektu

DB_PATH = DEFAULT_DB


# ---------------------------------------------------------------------------
# Dostęp do bazy (tylko odczyt)
# ---------------------------------------------------------------------------

def connect():
    con = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True, timeout=5)
    con.row_factory = sqlite3.Row
    return con


def quote_ident(name: str) -> str:
    """Bezpieczne ujęcie identyfikatora (nazwy walidujemy osobno)."""
    return '"' + str(name).replace('"', '""') + '"'


def list_objects(con):
    return [(r["name"], r["type"]) for r in con.execute(
        "SELECT name, type FROM sqlite_master "
        "WHERE type IN ('table','view') AND name NOT LIKE 'sqlite_%' "
        "ORDER BY type DESC, name")]


def object_columns(con, name: str):
    """Kolumny obiektu albo None, gdy nazwa nie jest tabelą/widokiem w bazie."""
    if not is_known_object(con, name):
        return None
    return [dict(r) for r in con.execute(f"PRAGMA table_info({quote_ident(name)})")]


def is_known_object(con, name: str) -> bool:
    return con.execute(
        "SELECT 1 FROM sqlite_master WHERE name = ? AND type IN ('table','view')",
        (name,)).fetchone() is not None


def count_rows(con, name: str, budget=None):
    """Liczba wierszy; None gdy zapytanie przekroczy budżet czasu."""
    deadline = time.monotonic() + (budget or SQL_TIME_BUDGET_S)
    con.set_progress_handler(lambda: 1 if time.monotonic() > deadline else 0, 20000)
    try:
        return con.execute(f"SELECT COUNT(*) FROM {quote_ident(name)}").fetchone()[0]
    except sqlite3.OperationalError:
        return None
    finally:
        con.set_progress_handler(None, 0)


def build_where(columns, q, qcol):
    """Filtr tekstowy: wszystkie kolumny albo jedna wybrana (LIKE, bez wielkości liter)."""
    if not q:
        return "", []
    if qcol and qcol in {c["name"] for c in columns}:
        cols = [qcol]
    else:
        cols = [c["name"] for c in columns]
    clause = " OR ".join(f"CAST({quote_ident(c)} AS TEXT) LIKE ?" for c in cols)
    return f" WHERE ({clause})", [f"%{q}%"] * len(cols)


def fetch_rows(con, name, limit, offset, sort, direction, q, qcol, only,
               max_chars=CELL_MAX_CHARS):
    columns = object_columns(con, name)
    if columns is None:
        raise ValueError(f"nieznany obiekt: {name}")
    col_names = [c["name"] for c in columns]
    if only:
        wanted = [c for c in only if c in col_names]
        columns = [c for c in columns if c["name"] in wanted]

    where, params = build_where(object_columns(con, name), q, qcol)
    order = ""
    if sort and sort in col_names:
        order = f" ORDER BY {quote_ident(sort)} {'DESC' if direction == 'desc' else 'ASC'}"
    select_cols = ", ".join(quote_ident(c["name"]) for c in columns)

    total = None
    if not only:
        deadline = time.monotonic() + SQL_TIME_BUDGET_LONG_S
        con.set_progress_handler(lambda: 1 if time.monotonic() > deadline else 0, 20000)
        try:
            total = con.execute(
                f"SELECT COUNT(*) FROM {quote_ident(name)}{where}", params).fetchone()[0]
        except sqlite3.OperationalError:
            total = None
        finally:
            con.set_progress_handler(None, 0)

    t0 = time.monotonic()
    cur = con.execute(
        f"SELECT {select_cols} FROM {quote_ident(name)}{where}{order} LIMIT ? OFFSET ?",
        (*params, limit, offset))
    rows, truncated = [], []
    for ri, r in enumerate(cur):
        vals = []
        for ci, v in enumerate(tuple(r)):
            if max_chars and isinstance(v, str) and len(v) > max_chars:
                truncated.append([ri, ci, len(v)])   # [wiersz, kolumna, pełna długość]
                vals.append(v[:max_chars])
            else:
                vals.append(v)
        rows.append(vals)
    return {
        "name": name,
        "columns": [{"name": c["name"], "type": c["type"]} for c in columns],
        "rows": rows,
        "truncated": truncated,
        "total": total,
        "limit": limit,
        "offset": offset,
        "sort": sort,
        "dir": direction,
        "q": q,
        "qcol": qcol,
        "ms": round((time.monotonic() - t0) * 1000, 1),
    }


def fetch_schema(con, name):
    if not is_known_object(con, name):
        raise ValueError(f"nieznany obiekt: {name}")
    columns = [dict(r) for r in con.execute(f"PRAGMA table_info({quote_ident(name)})")]
    fks = [dict(r) for r in con.execute(f"PRAGMA foreign_key_list({quote_ident(name)})")]
    indexes = []
    for idx in con.execute(f"PRAGMA index_list({quote_ident(name)})"):
        cols = [r["name"] for r in con.execute(
            f"PRAGMA index_info({quote_ident(idx['name'])})")]
        indexes.append({"name": idx["name"], "unique": bool(idx["unique"]),
                        "columns": cols, "origin": idx["origin"]})
    row = con.execute(
        "SELECT type, sql FROM sqlite_master WHERE name = ?", (name,)).fetchone()
    return {
        "name": name,
        "type": row["type"] if row else None,
        "sql": row["sql"] if row else None,
        "columns": columns,
        "foreign_keys": fks,
        "indexes": indexes,
    }


READ_ONLY_RE = re.compile(r"^\s*(select|with|pragma|explain)\b", re.I)


def run_sql(con, sql: str, limit: int):
    stripped = sql.strip().rstrip(";")
    if not stripped:
        raise ValueError("puste zapytanie")
    if not READ_ONLY_RE.match(stripped):
        raise ValueError("dozwolone są tylko zapytania czytające "
                         "(SELECT / WITH / PRAGMA / EXPLAIN)")
    if ";" in stripped:
        raise ValueError("dozwolone jest tylko jedno zapytanie")
    t0 = time.monotonic()
    cur = con.execute(stripped)
    columns = [d[0] for d in (cur.description or [])]
    rows, more = [], False
    for i, r in enumerate(cur):
        if i >= limit:
            more = True
            break
        vals = []
        for v in tuple(r):
            if isinstance(v, str) and len(v) > CELL_MAX_CHARS:
                vals.append(v[:CELL_MAX_CHARS])
            else:
                vals.append(v)
        rows.append(vals)
    return {"columns": [{"name": c, "type": ""} for c in columns], "rows": rows,
            "truncated": [], "total": None, "limit": limit, "offset": 0,
            "sort": None, "dir": "asc", "q": None, "qcol": None, "more": more,
            "ms": round((time.monotonic() - t0) * 1000, 1)}


def to_csv(columns, rows) -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow([c["name"] for c in columns])
    w.writerows(rows)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------

class Handler(BaseHTTPRequestHandler):
    server_version = "db-browser/1.0"

    def log_message(self, fmt, *args):        # ciszej w konsoli
        if "/api/" in (self.path or ""):
            sys.stderr.write(f"  {self.command} {self.path.split('?')[0]}\n")

    # --- helpers -----------------------------------------------------------
    def _send(self, code, body, ctype="application/json; charset=utf-8", extra=None):
        data = body.encode("utf-8") if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(data)

    def _json(self, obj, code=200):
        self._send(code, json.dumps(obj, ensure_ascii=False, default=str))

    def _error(self, message, code=400):
        self._json({"error": str(message)}, code)

    # --- GET ---------------------------------------------------------------
    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        args = {k: v[0] for k, v in urllib.parse.parse_qs(parsed.query).items()}

        if path in ("/", "/index.html"):
            if not UI_FILE.exists():
                return self._error(f"brak pliku UI: {UI_FILE}", 500)
            return self._send(200, UI_FILE.read_text(encoding="utf-8"),
                              "text/html; charset=utf-8")

        try:
            con = connect()
        except sqlite3.Error as exc:
            return self._error(f"nie mogę otworzyć bazy {DB_PATH}: {exc}", 500)

        try:
            if path == "/api/meta":
                objs = []
                for name, kind in list_objects(con):
                    cols = [dict(r) for r in con.execute(
                        f"PRAGMA table_info({quote_ident(name)})")]
                    objs.append({"name": name, "type": kind,
                                 "columns": [{"name": c["name"], "type": c["type"],
                                              "pk": c["pk"]} for c in cols]})
                return self._json({
                    "db": str(DB_PATH), "objects": objs,
                    "sqlite_version": sqlite3.sqlite_version,
                    "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                })

            if path == "/api/counts":
                return self._json({"counts": {
                    name: count_rows(con, name) for name, _ in list_objects(con)}})

            if path == "/api/count":
                name = args.get("name", "")
                if not is_known_object(con, name):
                    return self._error(f"nieznany obiekt: {name}")
                return self._json({"name": name,
                                   "count": count_rows(con, name, SQL_TIME_BUDGET_LONG_S)})

            if path == "/api/schema":
                return self._json(fetch_schema(con, args.get("name", "")))

            if path == "/api/rows":
                limit = min(int(args.get("limit", DEFAULT_LIMIT) or DEFAULT_LIMIT), MAX_LIMIT)
                offset = max(int(args.get("offset", 0) or 0), 0)
                only = [c for c in (args.get("only") or "").split(",") if c]
                data = fetch_rows(con, args.get("name", ""), limit, offset,
                                  args.get("sort") or None,
                                  (args.get("dir") or "asc").lower(),
                                  args.get("q") or None,
                                  args.get("qcol") or None, only)
                return self._json(data)

            if path == "/api/value":
                # pełna wartość jednej komórki (bez obcinania, z zachowaniem
                # filtra i sortowania widoku, z którego pochodzi wiersz)
                data = fetch_rows(
                    con, args.get("name", ""), 1,
                    max(int(args.get("offset", 0) or 0), 0),
                    args.get("sort") or None, (args.get("dir") or "asc").lower(),
                    args.get("q") or None, args.get("qcol") or None,
                    only=[args.get("col", "")], max_chars=None)
                value = data["rows"][0][0] if data["rows"] else None
                return self._json({"name": data["name"], "col": args.get("col"),
                                   "offset": data["offset"],
                                   "length": len(value) if isinstance(value, str) else None,
                                   "value": value})

            if path == "/api/sql":
                limit = min(int(args.get("limit", 500) or 500), MAX_LIMIT)
                return self._json(run_sql(con, args.get("q", ""), limit))

            if path == "/api/export":
                fmt = (args.get("format") or "csv").lower()
                limit = min(int(args.get("limit", 50000) or 50000), 500000)
                only = [c for c in (args.get("only") or "").split(",") if c]
                data = fetch_rows(con, args.get("name", ""), limit, 0,
                                  args.get("sort") or None,
                                  (args.get("dir") or "asc").lower(),
                                  args.get("q") or None, args.get("qcol") or None, only)
                stamp = time.strftime("%Y%m%d")
                base = f"{data['name']}_{stamp}"
                if fmt == "json":
                    body = json.dumps(
                        {"object": data["name"], "columns": data["columns"],
                         "rows": data["rows"], "exported_at": stamp},
                        ensure_ascii=False, indent=1, default=str)
                    return self._send(200, body, "application/json; charset=utf-8",
                                      {"Content-Disposition": f'attachment; filename="{base}.json"'})
                body = to_csv(data["columns"], data["rows"])
                return self._send(200, body, "text/csv; charset=utf-8",
                                  {"Content-Disposition": f'attachment; filename="{base}.csv"'})

            return self._error(f"nieznana ścieżka: {path}", 404)
        except ValueError as exc:
            return self._error(exc)
        except sqlite3.Error as exc:
            return self._error(f"błąd SQL: {exc}", 400)
        finally:
            con.close()


def main() -> int:
    global DB_PATH
    ap = argparse.ArgumentParser(description="Przeglądarka bazy analiz w przeglądarce")
    ap.add_argument("--db", default=str(DEFAULT_DB))
    ap.add_argument("--host", default="127.0.0.1",
                    help="adres nasłuchu (domyślnie tylko lokalny)")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--open", action="store_true", help="otwórz przeglądarkę")
    args = ap.parse_args()

    DB_PATH = Path(args.db)
    if not DB_PATH.exists():
        print(f"[error] brak bazy {DB_PATH} - uruchom scripts/db_init.py", file=sys.stderr)
        return 1
    if not UI_FILE.exists():
        print(f"[error] brak pliku UI {UI_FILE}", file=sys.stderr)
        return 1

    try:
        con = connect()
        n_objects = len(list_objects(con))
        con.close()
    except sqlite3.Error as exc:
        print(f"[error] {exc}", file=sys.stderr)
        return 1

    url = f"http://{'127.0.0.1' if args.host in ('0.0.0.0', '') else args.host}:{args.port}/"
    srv = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"[ok] przeglądarka bazy: {url}")
    print(f"     baza: {DB_PATH} (tylko odczyt), obiektów: {n_objects}")
    print("     Ctrl+C aby zatrzymać")
    if args.open:
        import webbrowser
        webbrowser.open(url)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n[stop]")
    finally:
        srv.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
