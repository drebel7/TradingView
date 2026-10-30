#!/usr/bin/env python3
"""Rank opt3 variant summaries (PL + US) against a baseline variant.

Reads summarize_signals.py outputs for the same iteration on two markets,
combines them (N-weighted), and prints/saves a markdown ranking with per-market
N ratios and scores.

Usage:
  python3 scripts/rank_opt3.py --pl analysis/PL_OPT3_VIP_it1_SUMMARY.csv \
      --us analysis/US_OPT3_VIP_it1_SUMMARY.csv --baseline vipOrig \
      --out analysis/OPT3_VIP_it1_RANK.md
"""
import argparse
import csv
from pathlib import Path


def rows(path):
    with open(path, encoding="utf-8", errors="replace") as f:
        return list(csv.DictReader(line for line in f if not line.startswith("#")))


def f(x, default=0.0):
    try:
        return float(x)
    except (TypeError, ValueError):
        return default


def combine(pl, us):
    out = {}
    for market, r in [("PL", r) for r in pl] + [("US", r) for r in us]:
        s = r["sig"]
        a = out.setdefault(s, dict(n=0, win=0.0, ar=0.0, gw=0.0, gl=0.0,
                                   score=0.0, sym=0, pos=0.0, dd=0.0,
                                   pl_n=0, us_n=0, pl_sc=0.0, us_sc=0.0))
        n = int(f(r["occurrences"]))
        a["n"] += n
        a["win"] += f(r["win_pct"]) * n
        a["ar"] += f(r["avg_r"]) * n
        a["gw"] += f(r["gross_win_r"])
        a["gl"] += f(r["gross_loss_r"])
        sym = int(f(r["symbols"]))
        a["sym"] += sym
        a["score"] += f(r["score_mean"]) * sym
        a["pos"] += f(r["score_pos_pct"]) * sym
        a["dd"] += f(r["max_dd"]) * sym
        if market == "PL":
            a["pl_n"] = n
            a["pl_sc"] = f(r["score_mean"])
        else:
            a["us_n"] = n
            a["us_sc"] = f(r["score_mean"])
    for a in out.values():
        n, sym = a["n"], a["sym"]
        a["win"] = a["win"] / n if n else 0.0
        a["ar"] = a["ar"] / n if n else 0.0
        a["score"] = a["score"] / sym if sym else 0.0
        a["pos"] = a["pos"] / sym if sym else 0.0
        a["dd"] = a["dd"] / sym if sym else 0.0
        a["pf"] = a["gw"] / abs(a["gl"]) if a["gl"] else None
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pl", required=True)
    ap.add_argument("--us", required=True)
    ap.add_argument("--baseline", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()

    data = combine(rows(a.pl), rows(a.us))
    if a.baseline not in data:
        raise SystemExit(f"baseline {a.baseline} not found")
    b = data[a.baseline]
    base_n, base_pl, base_us = b["n"], b["pl_n"], b["us_n"]

    ranked = sorted(data.items(), key=lambda kv: kv[1]["score"], reverse=True)
    lines = [
        "| # | Wariant | N | N/orig | PL N | US N | win% | avgR | PF | score | sc>0 | PL sc | US sc |",
        "|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for i, (name, v) in enumerate(ranked, 1):
        ratio = 100.0 * v["n"] / base_n if base_n else 0.0
        plr = 100.0 * v["pl_n"] / base_pl if base_pl else 0.0
        usr = 100.0 * v["us_n"] / base_us if base_us else 0.0
        pf = f"{v['pf']:.2f}" if v["pf"] is not None else "inf"
        lines.append(
            f"| {i} | `{name}` | {v['n']} | {ratio:.0f}% | "
            f"{v['pl_n']} ({plr:.0f}%) | {v['us_n']} ({usr:.0f}%) | "
            f"{v['win']:.1f} | {v['ar']:.2f} | {pf} | "
            f"{v['score']:+.2f} | {v['pos']:.0f} | "
            f"{v['pl_sc']:+.2f} | {v['us_sc']:+.2f} |"
        )
    text = "\n".join(lines) + "\n"
    Path(a.out).write_text(text)
    print(text)
    print(f"[saved] {a.out}")


if __name__ == "__main__":
    main()
