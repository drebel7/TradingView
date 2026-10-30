#!/usr/bin/env python3
"""Generate an unrolled Pine variant-table script from a template + JSON spec.

The template must contain:
  {{TITLE}}        - indicator title
  {{ROWS_COUNT}}   - table rows (header + variants + slack)
  //__CALLS__      - replaced with "<name> = <expr>" + q(...) tuple unpacking
  //__ROWS__       - replaced with renderRow(...) calls

Spec: {"title": "...", "variants": [{"name": "...", "expr": "..."}]}
"""
import argparse
import json
from pathlib import Path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--template", required=True)
    ap.add_argument("--spec", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    spec = json.loads(Path(args.spec).read_text())
    tpl = Path(args.template).read_text()
    variants = spec["variants"]
    avg_ret = bool(spec.get("avg_ret", False))

    calls, rows = [], []
    for i, v in enumerate(variants):
        n, e = v["name"], v["expr"]
        calls.append(f"{n} = {e}")
        ret_vars = f", {n}_ret" if avg_ret else ""
        if v.get("sl"):
            calls.append(f"{n}_sl = {v['sl']}")
            calls.append(
                f"[{n}_wr, {n}_n, {n}_ar, {n}_pf, {n}_dd, {n}_sc, {n}_swr, {n}_slr{ret_vars}] = q({n}, {n}_sl)"
            )
        else:
            calls.append(
                f"[{n}_wr, {n}_n, {n}_ar, {n}_pf, {n}_dd, {n}_sc, {n}_swr, {n}_slr{ret_vars}] = q({n})"
            )
        calls.append("")
        extra = f", {n}_ret" if avg_ret else ""
        rows.append(
            f'    renderRow(tbl, {3 + i}, "{n}", {n}_wr, {n}_n, {n}_ar, '
            f"{n}_pf, {n}_dd, {n}_sc, {n}_swr, {n}_slr{extra})"
        )

    out = (
        tpl.replace("{{TITLE}}", spec["title"])
        .replace("{{ROWS_COUNT}}", str(3 + len(variants) + 3))
        .replace("//__CALLS__", "\n".join(calls))
        .replace("//__ROWS__", "\n".join(rows))
    )
    Path(args.out).write_text(out)
    print(f"[done] {len(variants)} variants -> {args.out}")


if __name__ == "__main__":
    main()
