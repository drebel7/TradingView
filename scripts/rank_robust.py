#!/usr/bin/env python3
"""Robust variant ranking for rare signals.

`rank_opt3.py` ranks by `score_mean` averaged over symbols. When a signal fires
only ~1-2 times per symbol, that mean is dominated by a handful of symbols with
extreme scores (+50..+400), so it ranks luck rather than quality.

This script ranks by a winsorized score instead: each symbol's score is capped
at `--cap` before averaging, and the report shows the raw mean side by side so
the tail dependence stays visible. `pos%` (share of symbols with score > 0) is
the guardrail: a variant must not improve the mean at the cost of repeatability.

Usage:
  python3 scripts/rank_robust.py \
    --pl analysis/PL_OPT4_RIDING_it3_20261029.csv \
    --us analysis/US_OPT4_RIDING_it3_20261029.csv \
    --baseline ridingOrig --out analysis/OPT4_RIDING_it3_ROBUST.md
"""
import argparse
import csv
from collections import defaultdict
from pathlib import Path


def rows(path):
    with open(path, encoding="utf-8", errors="replace") as f:
        return list(csv.DictReader(line for line in f if not line.startswith("#")))


def f(x, default=0.0):
    try:
        return float(x)
    except (TypeError, ValueError):
        return default


def collect(pairs):
    """Per signal: pooled metrics + per-symbol score list.

    `pairs` is a list of (pl_path, us_path) tuples, one per iteration. A name is
    taken from the first iteration it appears in; later iterations only add
    names not seen before, so the baseline (present in every iteration script)
    is counted once.
    """
    out = {}
    for iter_idx, (pl, us) in enumerate(pairs):
        for market, path in (("PL", pl), ("US", us)):
            for r in rows(path):
                if not r.get("sig") or r["sig"] == "NO_DATA":
                    continue
                a = out.get(r["sig"])
                if a is None:
                    a = out[r["sig"]] = dict(n=0, win=0.0, ar=0.0, gw=0.0, gl=0.0,
                                             scores=[], pl_n=0, us_n=0, src=iter_idx)
                elif a["src"] != iter_idx:
                    continue
                n = int(f(r["n"]))
                a["n"] += n
                a["win"] += f(r["win_pct"]) * n
                a["ar"] += f(r["avg_r"]) * n
                a["gw"] += f(r["sum_win_r"])
                a["gl"] += f(r["sum_loss_r"])
                sc = r.get("score")
                if sc not in (None, "", "-"):
                    a["scores"].append(f(sc))
                if market == "PL":
                    a["pl_n"] += n
                else:
                    a["us_n"] += n
    for a in out.values():
        n = a["n"]
        a["win"] = a["win"] / n if n else 0.0
        a["ar"] = a["ar"] / n if n else 0.0
        a["pf"] = a["gw"] / abs(a["gl"]) if a["gl"] else None
        s = a["scores"]
        a["raw"] = sum(s) / len(s) if s else 0.0
        a["pos"] = 100.0 * sum(1 for x in s if x > 0) / len(s) if s else 0.0
        a["sym"] = len(s)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pl", nargs="+", required=True, help="PL per-symbol CSVs (one per iteration)")
    ap.add_argument("--us", nargs="+", required=True, help="US per-symbol CSVs (same order as --pl)")
    ap.add_argument("--baseline", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--cap", type=float, default=3.0)
    args = ap.parse_args()
    if len(args.pl) != len(args.us):
        raise SystemExit("--pl and --us must have the same number of files")

    data = collect(list(zip(args.pl, args.us)))
    if args.baseline not in data:
        raise SystemExit(f"baseline {args.baseline} not found")
    base = data[args.baseline]

    for a in data.values():
        capped = [min(x, args.cap) for x in a["scores"]]
        a["win_score"] = sum(capped) / len(capped) if capped else 0.0
        a["delta"] = a["win_score"] - (sum(min(x, args.cap) for x in base["scores"]) / len(base["scores"]) if base["scores"] else 0.0)

    ranked = sorted(data.items(), key=lambda kv: kv[1]["win_score"], reverse=True)
    base_win = sum(min(x, args.cap) for x in base["scores"]) / len(base["scores"]) if base["scores"] else 0.0

    lines = [
        f"# Ranking odporny (winsorized score, cap +{args.cap:g})",
        "",
        f"Baseline `{args.baseline}`: winsorized **{base_win:+.2f}**, raw {base['raw']:+.2f}, "
        f"pos% {base['pos']:.0f}, N {base['n']}, sym {base['sym']}",
        "",
        "| # | Wariant | N | N/base | win% | avgR | PF | raw score | **winsor** | Δ vs base | pos% | sym |",
        "|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for i, (name, v) in enumerate(ranked, 1):
        pf = f"{v['pf']:.2f}" if v["pf"] is not None else "inf"
        lines.append(
            f"| {i} | `{name}` | {v['n']} | {100.0 * v['n'] / base['n'] if base['n'] else 0:.0f}% | "
            f"{v['win']:.1f} | {v['ar']:.2f} | {pf} | {v['raw']:+.2f} | **{v['win_score']:+.2f}** | "
            f"{v['delta']:+.2f} | {v['pos']:.0f} | {v['sym']} |"
        )
    text = "\n".join(lines) + "\n"
    Path(args.out).write_text(text)
    print(text)
    print(f"[saved] {args.out}")


if __name__ == "__main__":
    main()
