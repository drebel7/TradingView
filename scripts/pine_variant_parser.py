#!/usr/bin/env python3
"""
pine_variant_parser.py
======================
Wyciąga z kodu Pine metadane potrzebne bazie `db/analysis.db`:

  * tytuł / shorttitle / wersję języka / typ skryptu (indicator|strategy|library),
  * importy bibliotek (alias + nazwa + wersja),
  * inputy skryptu (defval, title, group),
  * fabryki wariantów (`xxxCalc(int _a, bool _b) =>`),
  * warianty sygnałów wraz z WARTOŚCIAMI PARAMETRÓW, w dwóch wariantach:
      - `pine_parse`       - z wywołań fabryk: `sig = xxxCalc(200, 150, 95, true)`,
      - `script_defaults`  - sygnały bez fabryk (np. ETSB): parametry = domyślne
                             inputy skryptu, więc nie ma czego parsować,
  * nazwy sygnałów z tabeli wskaźnika (`renderRow(tbl, 3, "capLowTTT_90", ...)`
    albo `renderQualityRow(tbl, 3, "et3sb", ...)`),
  * wariant odpowiadający oryginalnym domyślnym (`// Sanity check: X == original`).

Obsługiwane wzorce (zweryfikowane na wszystkich skryptach w src/):

  perf_opt_sig_*.pine   -> fabryka + wywołania (czysty, jednolity wzorzec)
  perf_opt_sig_mtsb.pine-> brak fabryki; warianty inline - deklaratywny ekstraktor
  ETSB_*.pine           -> brak fabryk; nazwy z renderQualityRow -> script_defaults

Świadome ograniczenie: nazwy sygnałów czytamy wyłącznie z wywołań `render*`
z literałem tekstowym. Tabele budowane bezpośrednio przez `table.cell` (np.
"DRE Info") nie tworzą sygnałów - inaczej etykiety typu "ADR [%]" trafiłyby
do bazy jako sygnały.

Usage (podgląd):
  python3 scripts/pine_variant_parser.py src/indicators/perf_opt_sig_caplow.pine
"""

import json
import re
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Wzorce
# ---------------------------------------------------------------------------

HEADER_RE = re.compile(r"(?m)^\s*(indicator|strategy|library)\s*\(")
IMPORT_RE = re.compile(r"(?m)^\s*import\s+([\w./]+?)(?:/(\d+))?\s+as\s+(\w+)")
INPUT_RE = re.compile(r"(?m)^\s*([A-Za-z_]\w*)\s*=\s*(input\.[A-Za-z_]\w*)\s*\(")
FACTORY_RE = re.compile(r"(?m)^([A-Za-z_]\w*)\s*\(([^()]*)\)\s*=>\s*$")
LINE_CALL_RE = re.compile(r"(?m)^\s*([A-Za-z_]\w*)\s*=\s*([A-Za-z_]\w*)\s*\(")
RENDER_RE = re.compile(r'\brender\w*\s*\(\s*\w+\s*,\s*\d+\s*,\s*"([^"]+)"', re.I)
SANITY_RE = re.compile(r"Sanity check:\s*([A-Za-z0-9_][A-Za-z0-9_:.\-]*)", re.I)

# Skrypty bez fabryki wariantów: deklaratywny ekstraktor parametrów.
# (Pine nie pozwala wołać request.*() w funkcjach, więc mtsb ma warianty inline.
#  Warianty T przekazują zmienną doInclEarnings = sigMod < 1, ale wg konwencji
#  nazewnictwa i nagłówka skryptu odpowiadają one iIncludeEarnings = true.)
DECLARATIVE_EXTRACTORS = {
    "perf_opt_sig_mtsb": {
        "pattern": (r"(?m)^\s*(\w+)\s*=\s*ta\.barssince\(\s*"
                    r"drelib\.isMinevriniBullishTrend\(\s*true\s*,\s*"
                    r"([A-Za-z_]\w*)\s*,\s*([\d.]+)\s*\)"),
        "params": [
            {"name": "includeEarnings", "type": "bool",
             "map": {"doInclEarnings": True, "true": True, "false": False}},
            {"name": "betterEarningsRate", "type": "num"},
        ],
        "notes": ("includeEarnings w wariantach T realizowany przez "
                  "doInclEarnings = sigMod < 1"),
    },
}

# Recznie potwierdzone odpowiedniki oryginalnych domyślnych tam, gdzie komentarz
# "Sanity check" nie wskazuje jednoznacznie jednej nazwy (np. "wonHp200_3_...").
BASELINE_OVERRIDE = {
    "perf_opt_sig_wonhpsb": "wonHp200_3_75",
}


# ---------------------------------------------------------------------------
# Niskopoziomowe pomocniki
# ---------------------------------------------------------------------------

def strip_comments(src: str) -> str:
    """Usuwa komentarze `//` (z pominięciem tych wewnątrz literałów)."""
    out = []
    for line in src.splitlines():
        buf = []
        quote = None
        i = 0
        while i < len(line):
            ch = line[i]
            if quote:
                buf.append(ch)
                if ch == quote:
                    quote = None
            elif ch in ("'", '"'):
                quote = ch
                buf.append(ch)
            elif ch == "/" and i + 1 < len(line) and line[i + 1] == "/":
                break
            else:
                buf.append(ch)
            i += 1
        out.append("".join(buf))
    return "\n".join(out)


def read_args(src: str, paren_pos: int):
    """Zwraca (argumenty, pozycja ')' dla nawiasu otwartego na paren_pos)."""
    depth = 0
    quote = None
    j = paren_pos
    while j < len(src):
        ch = src[j]
        if quote:
            if ch == quote:
                quote = None
        elif ch in ("'", '"'):
            quote = ch
        elif ch in "([":
            depth += 1
        elif ch in ")]":
            depth -= 1
            if depth == 0:
                return src[paren_pos + 1:j], j
        j += 1
    return None, -1


def split_top_level(s: str):
    """Dzieli listę argumentów po przecinkach spoza nawiasów i literałów."""
    parts, cur, depth, quote = [], [], 0, None
    for ch in s:
        if quote:
            cur.append(ch)
            if ch == quote:
                quote = None
        elif ch in ("'", '"'):
            quote = ch
            cur.append(ch)
        elif ch in "([":
            depth += 1
            cur.append(ch)
        elif ch in ")]":
            depth -= 1
            cur.append(ch)
        elif ch == "," and depth == 0:
            parts.append("".join(cur).strip())
            cur = []
        else:
            cur.append(ch)
    tail = "".join(cur).strip()
    if tail:
        parts.append(tail)
    return parts


def is_literal_token(tok: str) -> bool:
    """Czy argument jest literałem (liczbą, true/false albo napisem)?"""
    t = tok.strip()
    if t in ("true", "false"):
        return True
    if re.fullmatch(r"[+-]?(\d+\.\d*|\.\d+|\d+)([eE][+-]?\d+)?", t):
        return True
    return len(t) >= 2 and t[0] == t[-1] and t[0] in ("'", '"')


def parse_literal(tok: str):
    """('num'|'bool'|'text', wartość) dla literału Pine."""
    t = tok.strip()
    if t in ("true", "false"):
        return ("bool", t == "true")
    if re.fullmatch(r"[+-]?\d+", t):
        return ("num", int(t))
    if re.fullmatch(r"[+-]?(\d+\.\d*|\.\d+|\d+)([eE][+-]?\d+)?", t):
        return ("num", float(t))
    if len(t) >= 2 and t[0] == t[-1] and t[0] in ("'", '"'):
        return ("text", t[1:-1])
    return ("text", t)


def arg_value(args, name):
    """Wartość argumentu nazwanego `name=` z listy argumentów."""
    for a in split_top_level(args):
        m = re.match(rf"^{name}\s*=\s*(.+)$", a, re.S)
        if m:
            return m.group(1).strip()
    return None


def positional_args(args):
    """Argumenty bez `nazwa =` (np. pierwszy argument = title)."""
    out = []
    for a in split_top_level(args):
        if re.match(r"^[A-Za-z_]\w*\s*=", a):
            continue
        out.append(a)
    return out


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------

def parse_script(path) -> dict:
    path = Path(path)
    src = path.read_text(encoding="utf-8", errors="replace")
    clean = strip_comments(src)
    warnings = []

    out = {
        "path": str(path),
        "stem": path.stem,
        "kind": None,
        "title": None,
        "shorttitle": None,
        "pine_version": None,
        "imports": [],
        "inputs": [],
        "factories": {},
        "variants": [],
        "table_names": [],
        "baseline": None,
        "warnings": warnings,
    }

    # --- nagłówek: //@version, indicator/strategy/library(...) -------------
    m = re.search(r"//\s*@version\s*=\s*(\d+)", src)
    if m:
        out["pine_version"] = m.group(1)

    m = HEADER_RE.search(clean)
    if m:
        out["kind"] = m.group(1)
        args, _ = read_args(clean, m.end() - 1)
        if args is not None:
            v = arg_value(args, "title")
            if v:
                out["title"] = parse_literal(v)[1]
            v = arg_value(args, "shorttitle")
            if v:
                out["shorttitle"] = parse_literal(v)[1]
            if out["title"] is None:
                pos = positional_args(args)
                if pos:
                    out["title"] = parse_literal(pos[0])[1]

    # --- importy -----------------------------------------------------------
    for m in IMPORT_RE.finditer(clean):
        lib_path, lib_ver, alias = m.group(1), m.group(2), m.group(3)
        out["imports"].append({
            "alias": alias,
            "lib_name": lib_path.rstrip("/").split("/")[-1],
            "lib_version": lib_ver,
        })

    # --- inputy ------------------------------------------------------------
    for m in INPUT_RE.finditer(clean):
        name, itype = m.group(1), m.group(2).split(".", 1)[1]
        args, _ = read_args(clean, m.end() - 1)
        if args is None:
            warnings.append(f"nieparsowalny input: {name}")
            continue
        inp = {
            "name": name,
            "type": itype,
            "title": None,
            "group": None,
            "defval": None,
        }
        v = arg_value(args, "defval")
        if v is not None:
            inp["defval"] = parse_literal(v)
        v = arg_value(args, "title")
        if v is not None:
            inp["title"] = parse_literal(v)[1]
        v = arg_value(args, "group")
        if v is not None:
            inp["group"] = parse_literal(v)[1]
        out["inputs"].append(inp)

    # --- fabryki wariantów -------------------------------------------------
    for m in FACTORY_RE.finditer(clean):
        fname, params = m.group(1), m.group(2)
        names, types = [], []
        for p in split_top_level(params):
            ids = re.findall(r"[A-Za-z_]\w*", p)
            if not ids:
                continue
            types.append(ids[0])
            names.append(ids[-1].lstrip("_"))
        out["factories"][fname] = {"params": names, "types": types}

    # --- nazwy sygnałów z tabeli wskaźnika ---------------------------------
    out["table_names"] = RENDER_RE.findall(clean)

    # --- warianty ----------------------------------------------------------
    table_set = set(out["table_names"])

    # Fabryki wariantów od pomocniczych (q, renderRow, countChanges...) dzielimy
    # po konwencji nazw (*Calc) albo po tym, że wszystkie ich wywołania są
    # wierszami tabeli sygnałów.
    calls_by_factory = {}
    for m in LINE_CALL_RE.finditer(clean):
        lhs, callee = m.group(1), m.group(2)
        if callee in out["factories"]:
            calls_by_factory.setdefault(callee, []).append(lhs)

    def is_variant_factory(name):
        if name.endswith("Calc"):
            return True
        lhs_list = calls_by_factory.get(name, [])
        return bool(table_set) and bool(lhs_list) and all(l in table_set for l in lhs_list)

    variants = {}
    for m in LINE_CALL_RE.finditer(clean):
        lhs, callee = m.group(1), m.group(2)
        if callee not in out["factories"]:
            continue
        args, end = read_args(clean, m.end() - 1)
        if args is None:
            continue
        rest = clean[end + 1:].split("\n", 1)[0]
        if rest.strip():          # RHS to nie jest samo wywołanie fabryki
            continue
        if table_set and lhs not in table_set:
            if is_variant_factory(callee):
                warnings.append(f"wywołanie {callee} poza tabelą: {lhs}")
            continue
        if not is_variant_factory(callee):
            continue
        names = out["factories"][callee]["params"]
        values = split_top_level(args)
        if not all(is_literal_token(v) for v in values):
            # Wywołanie z argumentami-zmiennymi to helper (np. func_obv(iObvSource)),
            # a nie wariant parametryzowany wartościami.
            continue
        if len(names) != len(values):
            warnings.append(
                f"{lhs}: {len(values)} argumentów, fabryka {callee} ma {len(names)}")
        params = {}
        for pname, raw in zip(names, values):
            ptype, val = parse_literal(raw)
            params[pname] = {"type": ptype, "value": val}
        variants[lhs] = {"sig_name": lhs, "params": params,
                         "params_source": "pine_parse", "raw_args": values,
                         "notes": None}

    # --- warianty z dekleratywnego ekstraktora (brak fabryki) --------------
    for stem, spec in DECLARATIVE_EXTRACTORS.items():
        if path.stem != stem:
            continue
        for m in re.finditer(spec["pattern"], clean):
            sig = m.group(1)
            if table_set and sig not in table_set:
                continue
            params = {}
            for pname, raw in zip(spec["params"], m.groups()[1:]):
                value_map = pname.get("map", {})
                if raw in value_map:
                    val = value_map[raw]
                else:
                    _, val = parse_literal(raw)
                params[pname["name"]] = {"type": pname["type"], "value": val}
            variants[sig] = {"sig_name": sig, "params": params,
                             "params_source": "pine_parse",
                             "raw_args": list(m.groups()[1:]),
                             "notes": spec.get("notes")}

    # Sygnały bez parametrów (skrypt bazowy, np. ETSB, albo sygnały spoza fabryk):
    # to oryginalne sygnały, ich parametry to domyślne inputy skryptu.
    for name in out["table_names"]:
        if name not in variants:
            variants[name] = {"sig_name": name, "params": {},
                              "params_source": "script_defaults", "raw_args": [],
                              "notes": None}

    out["variants"] = [variants[k] for k in sorted(variants)]

    # --- odpowiednik oryginalnych domyślnych -------------------------------
    m = SANITY_RE.search(src)
    token = m.group(1) if m else None
    names = {v["sig_name"] for v in out["variants"]}
    baseline = None
    if token:
        t = token.rstrip(".")
        if t in names:
            baseline = t
        else:
            pref = sorted(n for n in names if n.startswith(t))
            if len(pref) == 1:
                baseline = pref[0]
    if baseline is None:
        baseline = BASELINE_OVERRIDE.get(path.stem)
    out["baseline"] = baseline
    if token and baseline is None:
        warnings.append(f"niejednoznaczny 'Sanity check: {token}'")

    # zgodność nazw tabeli z wariantami
    if out["table_names"]:
        missing = [n for n in out["table_names"] if n not in variants]
        if missing:
            warnings.append(f"nazwy w tabeli bez wariantu: {missing}")

    return out


# ---------------------------------------------------------------------------
# CLI (podgląd)
# ---------------------------------------------------------------------------

def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__.strip().split("Usage")[0].strip())
        print("\nUsage: python3 scripts/pine_variant_parser.py <plik.pine> [...]")
        return 1
    for p in sys.argv[1:]:
        data = parse_script(p)
        print(f"== {data['path']}")
        print(f"   kind={data['kind']} v{data['pine_version']} "
              f"title={data['title']!r} shorttitle={data['shorttitle']!r}")
        print(f"   importy: {data['imports']}")
        print(f"   inputy: {len(data['inputs'])}  fabryki: {list(data['factories'])}")
        print(f"   tabela: {len(data['table_names'])} nazw  "
              f"warianty: {len(data['variants'])}  baseline: {data['baseline']}")
        for w in data["warnings"]:
            print(f"   [warn] {w}")
        for v in data["variants"][:3]:
            print(f"   - {v['sig_name']}: {json.dumps(v['params'], ensure_ascii=False)}")
        if len(data["variants"]) > 3:
            print(f"   ... (+{len(data['variants']) - 3})")
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
