#!/usr/bin/env python3
"""Merge 30-day and 90-day variant rankings (VIP top-30 anti-overfitting check).

Reads the four 30-day rank files (IT1/IT2/IT3/P45) and the 90-day rank file,
matches variants by name, and writes a markdown + CSV table sorted by the
90-day score. Also prints the Spearman rank correlation between horizons.

Usage:
  python3 scripts/merge_horizons.py --out analysis/OPT3_VIP_30_vs_90.md
"""
import argparse
from pathlib import Path

import pandas as pd

THIRTY = {
    "IT1": "analysis/OPT3_VIP_it1_RANK.md",
    "IT2": "analysis/OPT3_VIP_it2_RANK.md",
    "IT3": "analysis/OPT3_VIP_it3_RANK.md",
    "P45": "analysis/OPT3_VIP45_it1_RANK.md",
}
NINETY = "analysis/OPT3_VIPTOP30_90_RANK.md"

# variant name in the 30-day files -> name used in the 90-day run
ALIAS = {
    "vipP45_X100_T0_ref": "vipP45_Base",
}


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
    ap.add_argument("--out", default="analysis/OPT3_VIP_30_vs_90.md")
    args = ap.parse_args()

    thirty = {}
    for it, path in THIRTY.items():
        for name, m in parse_rank(path).items():
            thirty[name] = m
    ninety = parse_rank(NINETY)

    rows = []
    for name, m90 in ninety.items():
        src = ALIAS.get(name, name)
        m30 = thirty.get(src)
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
