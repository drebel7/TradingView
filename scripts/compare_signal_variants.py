#!/usr/bin/env python3
"""Compare the ORIGINAL ETSB signal performance with the best perf_opt variant.

For every signal and universe it prints the baseline (from the ETSB scrape,
summary CSV) next to the best variant from the corresponding perf_opt summary.

Two "best" picks are shown:
  * BEST(sc)      - highest score_mean (may be a tiny-sample fluke)
  * BEST(robust)  - highest score_mean among variants whose occurrence count is
                    at least ROBUST_FRAC of the largest occurrence count in that
                    universe (a sample-size guard)

Usage: python3 scripts/compare_signal_variants.py
"""
import csv
import os

ROBUST_FRAC = 0.30
ANALYSIS = "analysis"

# signal -> per-universe variant summary CSV, plus the variant that replicates
# the original defaults (for a faithful-replication sanity check).
SIGNALS = {
    "obvDiv": {
        "GPW": "GPW_NC_OBVDIV_SUMMARY.csv",
        "US": "US_BIG_OBVDIV_SUMMARY.csv",
        "ALL": "OBVDIV_SUMMARY_ALL.csv",
        "equiv": "obvDiv50",
    },
    "rag-pb": {
        "GPW": "GPW_NC_RAGPB_SUMMARY.csv",
        "US": "US_BIG_RAGPB_SUMMARY.csv",
        "ALL": "RAGPB_SUMMARY_ALL.csv",
        "equiv": "ragPb50a15",
    },
    "WON:hp-sb": {
        "GPW": "GPW_NC_WONHPSB_SUMMARY.csv",
        "US": "US_BIG_WONHPSB_SUMMARY.csv",
        "ALL": "WONHPSB_SUMMARY_ALL.csv",
        "equiv": None,
    },
    "WON:turnUp": {
        "GPW": "GPW_NC_WONTURNUP_SUMMARY.csv",
        "US": "US_BIG_WONTURNUP_SUMMARY.csv",
        "ALL": "WONTURNUP_SUMMARY_ALL.csv",
        "equiv": "wtUp45_3_r0",
    },
    "CapLow": {
        "GPW": "GPW_NC_CAPLOW_SUMMARY.csv",
        "US": "US_BIG_CAPLOW_SUMMARY.csv",
        "ALL": "CAPLOW_SUMMARY_ALL.csv",
        "equiv": "capLowTFT_95",
    },
    "FlatB": {
        "GPW": "GPW_NC_FLATB_SUMMARY.csv",
        "US": "US_BIG_FLATB_SUMMARY.csv",
        "ALL": "FLATB_SUMMARY_ALL.csv",
        "equiv": "flatB100_3_90",
    },
    "mtsb": {
        "GPW": "GPW_NC_MTSB_SUMMARY.csv",
        "US": "US_BIG_MTSB_SUMMARY.csv",
        "ALL": "MTSB_SUMMARY_ALL.csv",
        "equiv": "mtsbT50",
    },
    "vip": {
        "GPW": "VIPOPT_SUMMARY.csv",
        "US": "US_BIG_VIPOPT_SUMMARY.csv",
        "ALL": "VIPOPT_SUMMARY_ALL.csv",
        "equiv": "vip50F",
    },
}

UNIVERSES = ["GPW", "US", "ALL"]


def rows(path):
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8", errors="replace") as f:
        return [r for r in csv.DictReader(l for l in f if not l.startswith("#"))]


def get(path, sig):
    for r in rows(path):
        if r["sig"] == sig:
            return r
    return None


def occ(r):
    try:
        return int(r["occurrences"])
    except (TypeError, ValueError, KeyError):
        return 0


def fmt(r):
    if not r or occ(r) == 0:
        return "--"
    pf = r["pf"] if r["pf"] else "inf"
    return (
        f"sym={int(r['symbols']):>4} occ={occ(r):>6} win%={float(r['win_pct']):5.1f} "
        f"PF={pf:>5} sc={float(r['score_mean']):+.2f} sc>0={float(r['score_pos_pct']):3.0f}% "
        f"medAvgR={r['median_avg_r']:>6} medPF={r['median_pf']:>5}"
    )


def main():
    for sig, cfg in SIGNALS.items():
        print("=" * 132)
        print(f"SIGNAL: {sig}")
        print("=" * 132)
        for u in UNIVERSES:
            if u not in cfg:
                continue
            vpath = os.path.join(ANALYSIS, cfg[u])
            if not os.path.exists(vpath):
                print(f"[{u}] (brak pliku {cfg[u]})")
                continue
            base = get(os.path.join(ANALYSIS, f"BASE_{u}.csv"), sig)
            valid = [r for r in rows(vpath) if occ(r) > 0]
            if not valid:
                print(f"[{u}] (brak wariantow)")
                continue
            best_sc = max(valid, key=lambda r: float(r["score_mean"]))
            max_occ = max(occ(r) for r in valid)
            robust = [r for r in valid if occ(r) >= ROBUST_FRAC * max_occ]
            best_rob = max(robust, key=lambda r: float(r["score_mean"])) if robust else best_sc
            equiv = cfg.get("equiv")
            meq = get(vpath, equiv) if equiv else None
            print(f"[{u}] ORIGINAL   : {fmt(base)}")
            if meq is not None:
                print(f"      {equiv:>10} : {fmt(meq)}   (replika oryginalu)")
            print(f"      BEST(sc)   {best_sc['sig']:>10} : {fmt(best_sc)}")
            if best_rob["sig"] != best_sc["sig"]:
                print(f"      BEST(robust){best_rob['sig']:>10} : {fmt(best_rob)}")
        print()


if __name__ == "__main__":
    main()
