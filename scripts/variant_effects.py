#!/usr/bin/env python3
"""Per-variant effect table: intervention -> delta vs baseline.

Reads the per-symbol scraper CSVs of one signal family (all iterations, PL+US),
computes pooled metrics per variant and prints the delta against the baseline
variant of the same family. Meant as the raw material for
analysis/VARIANT_EFFECTS.md (intervention -> effect catalogue).

Pooled metrics: N = sum of occurrences; win% and avgR weighted by N; PF from
gross win/loss R; score = mean per-symbol score (as in rank_opt3.py); pos% =
share of symbols with score > 0.

Usage:
  python3 scripts/variant_effects.py \
    --pl analysis/PL_OPT4_RIDING_it1_20261029.csv analysis/PL_OPT4_RIDING_it2_20261029.csv \
    --us analysis/US_OPT4_RIDING_it1_20261029.csv analysis/US_OPT4_RIDING_it2_20261029.csv \
    --baseline ridingOrig --title ridingVwapTAG --out analysis/OPT4_RIDING_EFFECTS.csv
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


def collect(pairs):
    """pairs: [(pl_path, us_path), ...]; first occurrence of a name wins."""
    out = {}
    for idx, (pl, us) in enumerate(pairs):
        for market, path in (("PL", pl), ("US", us)):
            for r in rows(path):
                if not r.get("sig") or r["sig"] == "NO_DATA":
                    continue
                a = out.get(r["sig"])
                if a is None:
                    a = out[r["sig"]] = dict(src=idx, n=0, win=0.0, ar=0.0,
                                             gw=0.0, gl=0.0, scores=[], pl_n=0, us_n=0,
                                             pl_sc=None, us_sc=None)
                elif a["src"] != idx:
                    continue
                n = int(f(r["n"]))
                a["n"] += n
                a["win"] += f(r["win_pct"]) * n
                a["ar"] += f(r["avg_r"]) * n
                a["gw"] += f(r["sum_win_r"])
                a["gl"] += f(r["sum_loss_r"])
                if market == "PL":
                    a["pl_n"] += n
                else:
                    a["us_n"] += n
                sc = r.get("score")
                if sc not in (None, "", "-"):
                    a["scores"].append(f(sc))
                if market == "PL":
                    a["pl_sc"] = f(r["score"], a["pl_sc"] or 0.0)
                else:
                    a["us_sc"] = f(r["score"], a["us_sc"] or 0.0)
    for a in out.values():
        n = a["n"]
        a["win"] = a["win"] / n if n else 0.0
        a["ar"] = a["ar"] / n if n else 0.0
        a["pf"] = a["gw"] / abs(a["gl"]) if a["gl"] else None
        s = a["scores"]
        a["score"] = sum(s) / len(s) if s else 0.0
        a["pos"] = 100.0 * sum(1 for x in s if x > 0) / len(s) if s else 0.0
        a["sym"] = len(s)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pl", nargs="+", required=True)
    ap.add_argument("--us", nargs="+", required=True)
    ap.add_argument("--baseline", required=True)
    ap.add_argument("--title", default="")
    ap.add_argument("--out", required=True, help="output CSV")
    a = ap.parse_args()
    if len(a.pl) != len(a.us):
        raise SystemExit("--pl and --us must have the same length")

    data = collect(list(zip(a.pl, a.us)))
    if a.baseline not in data:
        raise SystemExit(f"baseline {a.baseline} not found")
    b = data[a.baseline]

    recs = []
    for name, v in data.items():
        recs.append(dict(
            signal=a.title, variant=name,
            n=v["n"], n_pct=100.0 * v["n"] / b["n"] if b["n"] else 0.0,
            win=v["win"], d_win=v["win"] - b["win"],
            ar=v["ar"], d_ar=v["ar"] - b["ar"],
            pf=v["pf"] if v["pf"] is not None else 0.0,
            d_pf=(v["pf"] or 0.0) - (b["pf"] or 0.0),
            score=v["score"], d_score=v["score"] - b["score"],
            pos=v["pos"], d_pos=v["pos"] - b["pos"],
            sym=v["sym"],
        ))
    recs.sort(key=lambda r: -r["d_score"])

    cols = ["signal", "variant", "n", "n_pct", "win", "d_win", "ar", "d_ar", "pf", "d_pf", "score", "d_score", "pos", "d_pos", "sym"]
    with open(a.out, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=cols)
        w.writeheader()
        w.writerows(recs)

    pf = f"{b['pf']:.2f}" if b["pf"] is not None else "inf"
    print(f"[base] {a.baseline}: N {b['n']} win {b['win']:.1f} avgR {b['ar']:.2f} "
          f"PF {pf} score {b['score']:+.3f} pos {b['pos']:.0f} sym {b['sym']}")
    print(f"{'variant':22s} {'N%':>5s} {'dWin':>6s} {'avgR':>6s} {'dAvgR':>7s} {'dPF':>6s} {'dScore':>7s} {'pos':>4s} {'dPos':>5s}")
    for r in recs[:18]:
        print(f"{r['variant']:22s} {r['n_pct']:5.0f} {r['d_win']:+6.1f} {r['ar']:6.2f} "
              f"{r['d_ar']:+7.2f} {r['d_pf']:+6.2f} {r['d_score']:+7.2f} {r['pos']:4.0f} {r['d_pos']:+5.0f}")
    print(f"[saved] {a.out}")


if __name__ == "__main__":
    main()
