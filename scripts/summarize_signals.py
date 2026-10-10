#!/usr/bin/env python3
"""
summarize_signals.py
====================
Aggregate one or more tv_table_scraper CSV files per signal (`sig`), across all
symbols, and write a tidy summary CSV.

Input columns (see tv_table_scraper.py, schema v2):
    group,symbol,sig,succ,total,success_pct,avg_gain,win_pct,n,avg_r,pf,max_dd,
    score,sum_win_r,sum_loss_r,raw

Per signal it computes (ignoring rows where the signal did not occur):

    symbols        distinct symbols with total>0
    occurrences    sum(total)
    success_pct    100 * sum(succ) / sum(total)                 (pooled)
    avg_gain       sum(avg_gain * total) / sum(total)           (pooled)
    win_pct        sum(win_pct * n) / sum(n)                    (pooled)
    avg_r          sum(avg_r * n) / sum(n)                      (pooled, R-weighted)
    pf             pooled profit factor = gross_win_r / |gross_loss_r|
                   from sum_win_r / sum_loss_r (blank = no losing trades).
                   Falls back to an n-weighted mean of the per-symbol pf column
                   for older CSVs that lack sum_win_r/sum_loss_r.
    max_dd         n-weighted mean of max_dd
    score_mean     mean of per-symbol score
    score_sum      sum of per-symbol score
    score_pos_pct  % of occurring symbols whose per-symbol score > 0
                   (repeatability - how often the signal is a net positive edge)
    median_avg_r   median of per-symbol avg_r (robust to outlier symbols)
    median_pf      median of per-symbol profit factor (from gross win/loss R,
                   symbols with losing trades only; robust to outlier symbols)
    gross_win_r    sum of gross winning R (positive)
    gross_loss_r   sum of gross losing R (<= 0)

Usage:
  python summarize_signals.py --out analysis\\SIG_SUMMARY.csv file1.csv [file2.csv ...]
"""

import argparse
import csv
import statistics
from pathlib import Path


def read_scraper_csv(path):
    rows = []
    with open(path, newline="", encoding="utf-8", errors="replace") as f:
        for line in f:
            if line.startswith("#"):
                continue
            rows.append(line)
    if not rows:
        return []
    return list(csv.DictReader(rows))


def fnum(x):
    try:
        if x is None or str(x).strip() == "":
            return None
        return float(x)
    except (TypeError, ValueError):
        return None


def aggregate(records):
    agg = {}
    for r in records:
        sig = (r.get("sig") or "").strip()
        if not sig or sig in ("sig", "NO_DATA"):
            continue
        a = agg.setdefault(sig, {
            "sig": sig,
            "symbols": 0,
            "occ_total": 0.0,
            "sum_total": 0.0, "sum_succ": 0.0, "sum_gain_total": 0.0,
            "sum_n": 0.0, "sum_win_n": 0.0, "sum_r_n": 0.0,
            "sum_pf_n": 0.0, "pf_n": 0.0, "sum_dd_n": 0.0,
            "gross_win_r": 0.0, "gross_loss_r": 0.0, "has_gross": False,
            "score_sum": 0.0, "score_cnt": 0, "score_pos": 0,
            "avg_r_list": [], "pf_list": [],
        })
        total = fnum(r.get("total"))
        n = fnum(r.get("n"))
        if total and total > 0:
            a["symbols"] += 1
            a["occ_total"] += total
            a["sum_total"] += total
            succ = fnum(r.get("succ"))
            if succ is not None:
                a["sum_succ"] += succ
            gain = fnum(r.get("avg_gain"))
            if gain is not None:
                a["sum_gain_total"] += gain * total
        if n and n > 0:
            a["sum_n"] += n
            win = fnum(r.get("win_pct"))
            if win is not None:
                a["sum_win_n"] += win * n
            ar = fnum(r.get("avg_r"))
            if ar is not None:
                a["sum_r_n"] += ar * n
                a["avg_r_list"].append(ar)
            pf = fnum(r.get("pf"))
            if pf is not None:
                a["sum_pf_n"] += pf * n
                a["pf_n"] += n
            dd = fnum(r.get("max_dd"))
            if dd is not None:
                a["sum_dd_n"] += dd * n
            sc = fnum(r.get("score"))
            if sc is not None:
                a["score_sum"] += sc
                a["score_cnt"] += 1
                if sc > 0:
                    a["score_pos"] += 1
        swr = fnum(r.get("sum_win_r"))
        slr = fnum(r.get("sum_loss_r"))
        if swr is not None or slr is not None:
            a["has_gross"] = True
            if swr is not None:
                a["gross_win_r"] += swr
            if slr is not None:
                a["gross_loss_r"] += slr
            if swr is not None and slr is not None and slr < 0:
                a["pf_list"].append(swr / abs(slr))

    out = []
    for a in agg.values():
        st, sn = a["sum_total"], a["sum_n"]
        if a["has_gross"]:
            pf = round(a["gross_win_r"] / abs(a["gross_loss_r"]), 2) if a["gross_loss_r"] < 0 else ""
        else:
            pf = round(a["sum_pf_n"] / a["pf_n"], 2) if a["pf_n"] else ""
        out.append({
            "sig": a["sig"],
            "symbols": a["symbols"],
            "occurrences": int(a["occ_total"]),
            "success_pct": round(100.0 * a["sum_succ"] / st, 1) if st else "",
            "avg_gain": round(a["sum_gain_total"] / st, 2) if st else "",
            "win_pct": round(a["sum_win_n"] / sn, 1) if sn else "",
            "avg_r": round(a["sum_r_n"] / sn, 3) if sn else "",
            "pf": pf,
            "max_dd": round(a["sum_dd_n"] / sn, 2) if sn else "",
            "score_mean": round(a["score_sum"] / a["score_cnt"], 2) if a["score_cnt"] else "",
            "score_sum": round(a["score_sum"], 1),
            "score_pos_pct": round(100.0 * a["score_pos"] / a["score_cnt"]) if a["score_cnt"] else "",
            "median_avg_r": round(statistics.median(a["avg_r_list"]), 3) if a["avg_r_list"] else "",
            "median_pf": round(statistics.median(a["pf_list"]), 2) if a["pf_list"] else "",
            "gross_win_r": round(a["gross_win_r"], 1) if a["has_gross"] else "",
            "gross_loss_r": round(a["gross_loss_r"], 1) if a["has_gross"] else "",
        })
    out.sort(key=lambda x: (x["score_mean"] if x["score_mean"] != "" else -1e9), reverse=True)
    return out


COLUMNS = ["sig", "symbols", "occurrences", "success_pct", "avg_gain",
           "win_pct", "avg_r", "pf", "max_dd", "score_mean", "score_sum",
           "score_pos_pct", "median_avg_r", "median_pf", "gross_win_r",
           "gross_loss_r"]


def main():
    ap = argparse.ArgumentParser(description="Aggregate signal stats from tv_table_scraper CSVs")
    ap.add_argument("--out", required=True, help="output summary CSV path")
    ap.add_argument("inputs", nargs="+", help="scraper CSV file(s)")
    args = ap.parse_args()

    records = []
    for p in args.inputs:
        records += read_scraper_csv(p)
    summary = aggregate(records)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS)
        w.writeheader()
        for row in summary:
            w.writerow(row)
    print(f"[done] {len(summary)} signals -> {out}")


if __name__ == "__main__":
    main()
