#!/usr/bin/env python3
"""Merge 30d and 90d robust rankings (winsorized score) for one signal family.

Same idea as merge_family_30_90.py, but the score is winsorized per symbol so a
handful of outliers cannot drive the ranking. A variant present in both horizons
gets rank30 + rank90; the lower the sum, the better the compromise.

Usage:
  python3 scripts/merge_robust.py \
    --thirty-pl analysis/PL_OPT4_RIDING_it1_20261029.csv analysis/PL_OPT4_RIDING_it3_20261029.csv \
    --thirty-us analysis/US_OPT4_RIDING_it1_20261029.csv analysis/US_OPT4_RIDING_it3_20261029.csv \
    --ninety-pl analysis/PL_OPT4_RIDING_90_20261030.csv \
    --ninety-us analysis/US_OPT4_RIDING_90_20261030.csv \
    --out analysis/OPT4_RIDING_30_vs_90_ROBUST.md
"""
import argparse
import statistics as st
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from rank_robust import collect  # noqa: E402


def win(v, cap):
    s = v["scores"]
    return sum(min(x, cap) for x in s) / len(s) if s else 0.0


def ranks(d, names):
    order = sorted(names, key=lambda k: win(d[k], 3.0), reverse=True)
    out, i = {}, 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and round(win(d[order[j + 1]], 3.0), 6) == round(win(d[order[i]], 3.0), 6):
            j += 1
        avg = (i + 1 + j + 1) / 2
        for k in order[i:j + 1]:
            out[k] = avg
        i = j + 1
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--thirty-pl", nargs="+", required=True)
    ap.add_argument("--thirty-us", nargs="+", required=True)
    ap.add_argument("--ninety-pl", required=True)
    ap.add_argument("--ninety-us", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--cap", type=float, default=3.0)
    a = ap.parse_args()

    d30 = collect(list(zip(a.thirty_pl, a.thirty_us)))
    d90 = collect([(a.ninety_pl, a.ninety_us)])
    common = [k for k in d90 if k in d30]
    r30, r90 = ranks(d30, common), ranks(d90, common)

    recs = []
    for k in common:
        recs.append(dict(
            name=k, r30=r30[k], r90=r90[k], tot=r30[k] + r90[k],
            w30=win(d30[k], a.cap), w90=win(d90[k], a.cap),
            raw30=d30[k]["raw"], raw90=d90[k]["raw"],
            n30=d30[k]["n"], n90=d90[k]["n"],
            win30=d30[k]["win"], win90=d90[k]["win"],
            ar30=d30[k]["ar"], ar90=d90[k]["ar"],
            pf30=d30[k]["pf"], pf90=d90[k]["pf"],
            pos30=d30[k]["pos"], pos90=d90[k]["pos"],
        ))
    recs.sort(key=lambda r: (r["tot"], r["r90"]))

    corr = None
    try:
        import pandas as pd
        s30 = pd.Series({k: win(d30[k], a.cap) for k in common})
        s90 = pd.Series({k: win(d90[k], a.cap) for k in common})
        corr = s30.corr(s90, method="spearman")
    except Exception:
        pass

    lines = [
        "# Ranking skumulowany 30d + 90d — metryka odporna (winsorized score)",
        "",
        f"Korelacja Spearmana 30d vs 90d: **{corr:.2f}**" if corr is not None else "",
        "",
        "| # | Wariant | r30 | r90 | Σ | winsor 30d | winsor 90d | Δ | N 30/90 | win% 30/90 | avgR 30/90 | PF 30/90 | pos% 30/90 |",
        "|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for i, r in enumerate(recs, 1):
        pf90 = f"{r['pf90']:.2f}" if r["pf90"] is not None else "inf"
        lines.append(
            f"| {i} | `{r['name']}` | {r['r30']:g} | {r['r90']:g} | **{r['tot']:g}** | "
            f"{r['w30']:+.2f} | {r['w90']:+.2f} | {r['w90'] - r['w30']:+.2f} | "
            f"{r['n30']}/{r['n90']} | {r['win30']:.1f}/{r['win90']:.1f} | "
            f"{r['ar30']:.2f}/{r['ar90']:.2f} | {r['pf30']:.2f}/{pf90} | "
            f"{r['pos30']:.0f}/{r['pos90']:.0f} |"
        )
    text = "\n".join(line for line in lines if line is not None) + "\n"
    Path(a.out).write_text(text)
    print(text)


if __name__ == "__main__":
    main()
