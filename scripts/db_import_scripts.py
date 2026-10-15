#!/usr/bin/env python3
"""
db_import_scripts.py
====================
Importuje do bazy `db/analysis.db` definicje ze źródeł Pine:

  * script + script_revision   - kod i historia wersji (sha256, commit git),
  * script_dependency          - importy bibliotek (DRELib/39, DREPerf/27),
  * script_param               - inputy skryptu (defval/title/group),
  * signal + variant           - sygnały i warianty z WARTOŚCIAMI PARAMETRÓW,
  * variant_param              - znormalizowane parametry (num/bool/text).

Reguły przypisania sygnałów:
  * skrypt z fabrykami wariantów (perf_opt_sig_*.pine) -> JEDEN sygnał bazowy
    (mapowany na nazwę z ETSB) i wiele wariantów z parametrami z kodu,
  * skrypt bez fabryk (ETSB, DRE parabolic top, DRE When-Sell) -> po jednym
    sygnale na nazwę z tabeli; wariant = oryginał (is_baseline=1), parametry =
    domyślne inputy skryptu (params_source='script_defaults').

Import jest idempotentny. Elementy usunięte z kodu są przycinane, ale wariant
z historią pomiarów nie jest kasowany (dostaje ostrzeżenie w `notes`).

Usage:
  python3 scripts/db_import_scripts.py
  python3 scripts/db_import_scripts.py --db db/analysis.db --dry-run
"""

import argparse
import hashlib
import json
import sqlite3
import subprocess
import sys
from pathlib import Path

import pine_variant_parser as pvp

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = REPO_ROOT / "db" / "analysis.db"

# Skrypt perf_opt_* -> sygnał bazowy, którego jest parametrycznym przeglądem
# (nazwy 1:1 z tabeli ETSB_earlyTrendStrongBreakout.pine).
BASE_SIGNAL_MAP = {
    "perf_opt_sig_caplow": "CapLow",
    "perf_opt_sig_flatb": "FlatB",
    "perf_opt_sig_mtsb": "mtsb",
    "perf_opt_sig_obvdiv": "obvDiv",
    "perf_opt_sig_ragpb": "rag-pb",
    "perf_opt_sig_vip": "vip",
    "perf_opt_sig_wonhpsb": "WON:hp-sb",
    "perf_opt_sig_wonturnup": "WON:turnUp",
}

KIND_BY_DIR = {
    "indicators": "indicator",
    "libraries": "library",
    "strategies": "strategy",
}


def script_kind(rel_path: str) -> str:
    parts = Path(rel_path).parts
    if len(parts) >= 2 and parts[0] == "src":
        return KIND_BY_DIR.get(parts[1], "other")
    return "other"


def git_commit(rel_path: str):
    try:
        out = subprocess.run(
            ["git", "log", "-1", "--format=%H", "--", rel_path],
            cwd=REPO_ROOT, capture_output=True, text=True, timeout=10)
        commit = out.stdout.strip()
        return commit or None
    except Exception:
        return None


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def upsert_script(con, rel_path, parsed, code, commit, now):
    sha = sha256_text(code)
    con.execute(
        """INSERT INTO script(path, kind, title, shorttitle, pine_version,
                              sha256, git_commit, code, imported_at)
           VALUES (?,?,?,?,?,?,?,?,?)
           ON CONFLICT(path) DO UPDATE SET
               kind=excluded.kind, title=excluded.title,
               shorttitle=excluded.shorttitle, pine_version=excluded.pine_version,
               sha256=excluded.sha256, git_commit=excluded.git_commit,
               code=excluded.code, imported_at=excluded.imported_at""",
        (rel_path, script_kind(rel_path), parsed["title"], parsed["shorttitle"],
         parsed["pine_version"], sha, commit, code, now))
    script_id = con.execute("SELECT id FROM script WHERE path=?", (rel_path,)).fetchone()[0]
    con.execute(
        """INSERT INTO script_revision(script_id, sha256, git_commit, code, created_at)
           VALUES (?,?,?,?,?)
           ON CONFLICT(script_id, sha256) DO UPDATE SET
               git_commit=excluded.git_commit""",
        (script_id, sha, commit, code, now))
    revision_id = con.execute(
        "SELECT id FROM script_revision WHERE script_id=? AND sha256=?",
        (script_id, sha)).fetchone()[0]
    return script_id, revision_id


def import_dependencies(con, script_id, parsed, lib_ids):
    seen = set()
    for dep in parsed["imports"]:
        seen.add(dep["alias"])
        con.execute(
            """INSERT INTO script_dependency(script_id, alias, lib_name,
                                             lib_version, lib_script_id)
               VALUES (?,?,?,?,?)
               ON CONFLICT(script_id, alias) DO UPDATE SET
                   lib_name=excluded.lib_name, lib_version=excluded.lib_version,
                   lib_script_id=excluded.lib_script_id""",
            (script_id, dep["alias"], dep["lib_name"], dep["lib_version"],
             lib_ids.get(dep["lib_name"])))
    return seen


def import_inputs(con, script_id, parsed):
    seen = set()
    for inp in parsed["inputs"]:
        seen.add(inp["name"])
        ptype = inp["defval"][0] if inp["defval"] else None
        val = inp["defval"][1] if inp["defval"] else None
        num = val if ptype == "num" else None
        boolean = (1 if val else 0) if ptype == "bool" else None
        text = val if ptype == "text" else None
        con.execute(
            """INSERT INTO script_param(script_id, name, type, title, group_name,
                                        value_num, value_bool, value_text)
               VALUES (?,?,?,?,?,?,?,?)
               ON CONFLICT(script_id, name) DO UPDATE SET
                   type=excluded.type, title=excluded.title,
                   group_name=excluded.group_name, value_num=excluded.value_num,
                   value_bool=excluded.value_bool, value_text=excluded.value_text""",
            (script_id, inp["name"], inp["type"], inp["title"], inp["group"],
             num, boolean, text))
    return seen


def import_signals(con, script_id, parsed, stats):
    """Tworzy sygnały/warianty skryptu; zwraca zbiór nazw wariantów."""
    variants = parsed["variants"]
    parsed_variants = [v for v in variants if v["params_source"] == "pine_parse"]

    if parsed_variants:
        # Skrypt-przegląd: jeden sygnał bazowy, wiele wariantów.
        code = BASE_SIGNAL_MAP.get(parsed["stem"]) or parsed["title"] or parsed["stem"]
        groups = {code: variants}
    else:
        # Skrypt bazowy: każda nazwa z tabeli to osobny sygnał (wariant = oryginał).
        groups = {v["sig_name"]: [v] for v in variants}

    seen_variants = set()
    seen_signals = set()
    for code, group in groups.items():
        con.execute(
            """INSERT INTO signal(script_id, code, name) VALUES (?,?,?)
               ON CONFLICT(script_id, code) DO UPDATE SET name=excluded.name""",
            (script_id, code, code))
        signal_id = con.execute(
            "SELECT id FROM signal WHERE script_id=? AND code=?",
            (script_id, code)).fetchone()[0]
        seen_signals.add(code)

        for v in group:
            sig_name = v["sig_name"]
            seen_variants.add(sig_name)
            if v["params_source"] == "script_defaults":
                role = "original"           # sygnał oryginalny (skrypt bazowy)
            elif v["sig_name"] == parsed["baseline"]:
                role = "equivalent"         # replika oryginału w przeglądzie
            else:
                role = "variant"
            params_json = json.dumps(
                {k: p["value"] for k, p in v["params"].items()},
                ensure_ascii=False, sort_keys=True) if v["params"] else None
            con.execute(
                """INSERT INTO variant(signal_id, sig_name, role,
                                       params_source, params_json, notes)
                   VALUES (?,?,?,?,?,?)
                   ON CONFLICT(sig_name) DO UPDATE SET
                       signal_id=excluded.signal_id,
                       role=excluded.role,
                       params_source=excluded.params_source,
                       params_json=excluded.params_json,
                       notes=excluded.notes""",
                (signal_id, sig_name, role, v["params_source"],
                 params_json, v["notes"]))
            variant_id = con.execute(
                "SELECT id FROM variant WHERE sig_name=?", (sig_name,)).fetchone()[0]
            con.execute("DELETE FROM variant_param WHERE variant_id=?", (variant_id,))
            for pname, p in v["params"].items():
                con.execute(
                    """INSERT INTO variant_param(variant_id, name, type,
                                                 value_num, value_bool, value_text)
                       VALUES (?,?,?,?,?,?)""",
                    (variant_id, pname, p["type"],
                     p["value"] if p["type"] == "num" else None,
                     (1 if p["value"] else 0) if p["type"] == "bool" else None,
                     p["value"] if p["type"] == "text" else None))
            stats["variants"] += 1
            if v["params"]:
                stats["variants_with_params"] += 1
    stats["signals"] += len(seen_signals)
    return seen_signals, seen_variants


def prune(con, script_id, seen_signals, seen_variants, seen_inputs, seen_deps, stats):
    """Usuwa z bazy elementy, których już nie ma w kodzie (bezpiecznie)."""
    rows = con.execute(
        """SELECT v.id, v.sig_name,
                  (SELECT COUNT(*) FROM measurement m WHERE m.variant_id=v.id) AS used
           FROM variant v JOIN signal s ON s.id = v.signal_id
           WHERE s.script_id=? AND v.sig_name NOT IN (%s)"""
        % ",".join("?" * max(len(seen_variants), 1)),
        (script_id, *sorted(seen_variants)) if seen_variants else (script_id, "")
    ).fetchall()
    for vid, sig_name, used in rows:
        if used:
            con.execute(
                "UPDATE variant SET notes = COALESCE(notes,'') || "
                "' [usunięty z kodu, zachowany: historia pomiarów]' WHERE id=?",
                (vid,))
            stats["kept_with_history"].append(sig_name)
        else:
            con.execute("DELETE FROM variant_param WHERE variant_id=?", (vid,))
            con.execute("DELETE FROM variant WHERE id=?", (vid,))
            stats["pruned_variants"].append(sig_name)

    for (sid, code) in con.execute(
            "SELECT id, code FROM signal WHERE script_id=?", (script_id,)).fetchall():
        left = con.execute("SELECT COUNT(*) FROM variant WHERE signal_id=?", (sid,)).fetchone()[0]
        if left == 0:
            con.execute("DELETE FROM signal WHERE id=?", (sid,))
            stats["pruned_signals"].append(code)

    con.execute(
        """DELETE FROM script_param WHERE script_id=? AND name NOT IN (%s)"""
        % ",".join("?" * max(len(seen_inputs), 1)),
        (script_id, *sorted(seen_inputs)) if seen_inputs else (script_id, ""))
    con.execute(
        """DELETE FROM script_dependency WHERE script_id=? AND alias NOT IN (%s)"""
        % ",".join("?" * max(len(seen_deps), 1)),
        (script_id, *sorted(seen_deps)) if seen_deps else (script_id, ""))


def main() -> int:
    ap = argparse.ArgumentParser(description="Import skryptów/sygnałów/wariantów do bazy")
    ap.add_argument("--db", default=str(DEFAULT_DB))
    ap.add_argument("--src", default=str(REPO_ROOT / "src"), help="katalog ze skryptami")
    ap.add_argument("--dry-run", action="store_true", help="nie zapisuj zmian")
    args = ap.parse_args()

    db_path = Path(args.db)
    if not db_path.exists():
        print(f"[error] brak bazy {db_path} - uruchom najpierw scripts/db_init.py",
              file=sys.stderr)
        return 1

    now = __import__("datetime").datetime.now().replace(microsecond=0).isoformat()
    files = sorted(Path(args.src).rglob("*.pine"))
    if not files:
        print(f"[error] brak plików .pine w {args.src}", file=sys.stderr)
        return 1

    con = sqlite3.connect(db_path)
    con.execute("PRAGMA foreign_keys = ON")
    stats = {"variants": 0, "variants_with_params": 0, "signals": 0,
             "pruned_variants": [], "pruned_signals": [],
             "kept_with_history": [], "warnings": []}
    try:
        with con:  # jedna transakcja
            # 1. skrypty + rewizje (najpierw, żeby znać id bibliotek)
            parsed_by_path = {}
            for f in files:
                rel = str(f.relative_to(REPO_ROOT))
                parsed = pvp.parse_script(f)
                code = f.read_text(encoding="utf-8", errors="replace")
                parsed["stem"] = f.stem
                parsed_by_path[rel] = parsed
                upsert_script(con, rel, parsed, code, git_commit(rel), now)

            lib_ids = {r[0]: r[1] for r in con.execute(
                "SELECT title, id FROM script WHERE kind='library' AND title IS NOT NULL")}

            # 2. zależności, inputy, sygnały/warianty
            for rel, parsed in parsed_by_path.items():
                script_id = con.execute(
                    "SELECT id FROM script WHERE path=?", (rel,)).fetchone()[0]
                deps = import_dependencies(con, script_id, parsed, lib_ids)
                inputs = import_inputs(con, script_id, parsed)
                signals, variants = import_signals(con, script_id, parsed, stats)
                prune(con, script_id, signals, variants, inputs, deps, stats)
                for w in parsed["warnings"]:
                    stats["warnings"].append(f"{rel}: {w}")

            if args.dry_run:
                raise RuntimeError("dry-run")
    except RuntimeError:
        con.rollback()
        print("[dry-run] zmiany wycofane")
    except Exception as exc:
        con.rollback()
        print(f"[error] {exc}", file=sys.stderr)
        return 1
    finally:
        n_scripts = con.execute("SELECT COUNT(*) FROM script").fetchone()[0]
        n_rev = con.execute("SELECT COUNT(*) FROM script_revision").fetchone()[0]
        n_sig = con.execute("SELECT COUNT(*) FROM signal").fetchone()[0]
        n_var = con.execute("SELECT COUNT(*) FROM variant").fetchone()[0]
        n_vp = con.execute("SELECT COUNT(*) FROM variant_param").fetchone()[0]
        n_sp = con.execute("SELECT COUNT(*) FROM script_param").fetchone()[0]
        con.close()

    print(f"[ok] skrypty: {n_scripts} (rewizje: {n_rev})")
    print(f"     sygnały: {n_sig}  warianty: {n_var}  "
          f"(z parametrami w kodzie: {stats['variants_with_params']})  "
          f"parametry wariantów: {n_vp}  inputy skryptów: {n_sp}")
    if stats["pruned_variants"]:
        print(f"     usunięte warianty (nie ma w kodzie): {stats['pruned_variants']}")
    if stats["pruned_signals"]:
        print(f"     usunięte sygnały (bez wariantów): {stats['pruned_signals']}")
    if stats["kept_with_history"]:
        print(f"     zachowane mimo braku w kodzie (mają pomiary): "
              f"{stats['kept_with_history']}")
    for w in stats["warnings"]:
        print(f"     [warn] {w}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
