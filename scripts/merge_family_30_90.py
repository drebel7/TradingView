#!/usr/bin/env python3
"""Merge 30-day and 90-day rankings for a signal family.

The 30-day side can be several rank files (iterations); the 90-day side is one
rank file produced by scripts/rank_opt3.py. Variants are matched by name.

Usage:
  python3 scripts/merge_family_30_90.py \
    --thirty analysis/OPT3_RAG_it1_RANK.md analysis/OPT3_RAG_it2_RANK.md analysis/OPT3_RAG_it3_RANK.md \
    --ninety analysis/OPT3_RAG_T15_90_RANK.md \
    --out analysis/OPT3_RAG_30_vs_90.md
"""
import argparse
from pathlib import Path

import pandas as pd


def parse_rank(path):
    out = {}
    for line in Path(path).read_text().splitlines():
        if not line.startswith("|") or "`" not in line:
            continue
        c = [x.strip() for x in line.strip().strip("|").split("|")]
        if len(c) < 13:
            continue
        name = c[1].strip("`")

        def num(x):
            x = x.replace("%", "").replace("−", "-").replace("+", "")
            try:
                return float(x)
            except ValueError:
                return None

        out[name] = dict(
            n=num(c[2]), ratio=num(c[3]), win=num(c[6]), ar=num(c[7]),
            pf=num(c[8]), sc=num(c[9]), pos=num(c[10]),
            pl=num(c[11]), us=num(c[12]),
        )
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--thirty", nargs="+", required=True)
    ap.add_argument("--ninety", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    thirty = {}
    for path in args.thirty:
        for name, m in parse_rank(path).items():
            thirty[name] = m
    ninety = parse_rank(args.ninety)

    rows = []
    for name, m90 in ninety.items():
        m30 = thirty.get(name)
        if not m30:
            continue
        rows.append(dict(
            name=name,
            sc30=m30["sc"], sc90=m90["sc"],
            dsc=(m90["sc"] or 0) - (m30["sc"] or 0),
            n30=m30["n"], n90=m90["n"],
            win30=m30["win"], win90=m90["win"],
            ar30=m30["ar"], ar90=m90["ar"],
            pf30=m30["pf"], pf90=m90["pf"],
            pos30=m30["pos"], pos90=m90["pos"],
            pl30=m30["pl"], pl90=m90["pl"],
            us30=m30["us"], us90=m90["us"],
        ))
    df = pd.DataFrame(rows).sort_values("sc90", ascending=False).reset_index(drop=True)

    corr = df["sc30"].rank().corr(df["sc90"].rank())
    lines = [
        f"Spearman rank correlation 30d vs 90d: **{corr:.2f}**\n",
        "| # | Wariant | score 30d | score 90d | Δscore | N 30/90 | win% 30/90 | avgR 30/90 | PF 30/90 | sc>0 30/90 | PL 30/90 | US 30/90 |",
        "|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for i, r in df.iterrows():
        lines.append(
            f"| {i+1} | `{r['name']}` | {r['sc30']:+.2f} | {r['sc90']:+.2f} | "
            f"{r['dsc']:+.2f} | {int(r['n30'])}/{int(r['n90'])} | "
            f"{r['win30']:.1f}/{r['win90']:.1f} | {r['ar30']:.2f}/{r['ar90']:.2f} | "
            f"{r['pf30']:.2f}/{r['pf90']:.2f} | {r['pos30']:.0f}/{r['pos90']:.0f} | "
            f"{r['pl30']:+.2f}/{r['pl90']:+.2f} | {r['us30']:+.2f}/{r['us90']:+.2f} |"
        )
    text = "\n".join(lines) + "\n"
    Path(args.out).write_text(text)
    df.to_csv(args.out.replace(".md", ".csv"), index=False)
    print(text)
    print(f"[saved] {args.out}")


if __name__ == "__main__":
    main()
