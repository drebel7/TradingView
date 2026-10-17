#!/usr/bin/env python3
"""Cross-sectional analysis: signal quality vs company profile (MCap, ADR, turnover, price, age, sector).

Uses the measurements already stored in db/analysis.db (latest run per universe unless --run is given)
joined with company_metric / company_profile.

For every signal (variant) and every profile bucket the script reports POOLED statistics
(win% and avgR weighted by n, profit factor from the pooled gross win/loss R) so that a bucket's
number is not distorted by symbols with a single trade.

Outputs:
  - console summary (system-level bucket tables, per-signal highlights, filter simulation)
  - analysis/company_profile_<UNIVERSE>.csv  (machine-readable: signal x dimension x bucket)
  - analysis/company_profile_analysis.md     (markdown report)

Usage:
  python3 company_profile_analysis.py [--run N] [--min-n 30]
"""
import argparse
import csv
import os
import sqlite3
from collections import defaultdict

DB = 'db/analysis.db'

BUCKETS = {
    'mcap_m': [('MCap <50M', 0, 50), ('50-200M', 50, 200), ('200M-1B', 200, 1000),
               ('1-10B', 1000, 10000), ('>10B', 10000, 1e12)],
    'adr_pct': [('ADR <3%', 0, 3), ('3-5%', 3, 5), ('5-8%', 5, 8), ('>=8%', 8, 1e9)],
    'turnover_m': [('Turn <0.5M', 0, 0.5), ('0.5-2M', 0.5, 2), ('2-10M', 2, 10),
                   ('10-50M', 10, 50), ('>=50M', 50, 1e12)],
    'price': [('Price <2', 0, 2), ('2-5', 2, 5), ('5-20', 5, 20), ('>20', 20, 1e12)],
    'years': [('Age <3y', 0, 3), ('3-10y', 3, 10), ('>10y', 10, 1e9)],
}


def bucket_of(value, spec):
    if value is None:
        return 'n/a'
    for name, lo, hi in spec:
        if lo <= value < hi:
            return name
    return 'n/a'


def agg(rows):
    rows = [r for r in rows if r['n'] and r['n'] > 0]
    n = sum(r['n'] for r in rows)
    if not n:
        return None
    win = sum(r['win_pct'] * r['n'] for r in rows) / n
    avgr = sum(r['avg_r'] * r['n'] for r in rows) / n
    sw = sum(r['sum_win_r'] or 0.0 for r in rows)
    sl = sum(r['sum_loss_r'] or 0.0 for r in rows)
    pf = (sw / abs(sl)) if sl else float('inf')
    return dict(n=n, instruments=len(rows), win=win, avg_r=avgr, pf=pf, total_r=avgr * n)


def fmt(v, nd=2, dash='-'):
    if v is None:
        return dash
    if v == float('inf'):
        return 'inf'
    return f'{v:.{nd}f}'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--run', type=int, help='run id (default: latest run per universe)')
    ap.add_argument('--min-n', type=int, default=60, help='min occurrences for a per-signal bucket to be shown')
    args = ap.parse_args()

    con = sqlite3.connect(DB)
    if args.run:
        runs = con.execute('select id, universe_id from run where id=?', (args.run,)).fetchall()
    else:
        runs = con.execute('select max(id), universe_id from run group by universe_id').fetchall()
    run_ids = tuple(r[0] for r in runs)
    print('runy w analizie:', run_ids)

    q = f"""
        select u.code as uni, v.sig_name as sig, i.ticker, i.exchange,
               cp.sector, cm.market_cap_m, cm.adr_pct, cm.avg_turnover_m, cm.hod_price,
               cp.years_on_exchange,
               m.n, m.win_pct, m.avg_r, m.sum_win_r, m.sum_loss_r
        from measurement m
        join run r on r.id = m.run_id
        join universe u on u.id = r.universe_id
        join variant v on v.id = m.variant_id
        join instrument i on i.id = m.instrument_id
        left join company_metric cm on cm.instrument_id = i.id
        left join company_profile cp on cp.instrument_id = i.id
        where m.run_id in ({','.join('?' * len(run_ids))})
    """
    cols = ['uni', 'sig', 'ticker', 'exchange', 'sector', 'mcap_m', 'adr_pct', 'turnover_m',
            'price', 'years', 'n', 'win_pct', 'avg_r', 'sum_win_r', 'sum_loss_r']
    data = [dict(zip(cols, row)) for row in con.execute(q, run_ids)]
    print(f'wierszy pomiarów: {len(data)}')

    out_rows = []
    report = []
    for uni in sorted({d['uni'] for d in data}):
        rows = [d for d in data if d['uni'] == uni]
        sigs = sorted({d['sig'] for d in rows})
        report.append(f'\n# {uni}: {len(rows)} pomiarów, {len({d["ticker"] for d in rows})} spółek, {len(sigs)} sygnałów\n')

        # ---------- system level: every signal pooled, split by profile bucket
        for dim, spec in BUCKETS.items():
            report.append(f'## {uni} — cały system wg {dim}\n')
            report.append('| bucket | spółek | zdarzeń | win% | avgR | PF | suma R | R/100 zdarzeń |')
            report.append('|---|---|---|---|---|---|---|---|')
            buckets = defaultdict(list)
            for d in rows:
                buckets[bucket_of(d[dim], spec)].append(d)
            for name, _, _ in spec + [('n/a', 0, 0)]:
                b = buckets.get(name)
                a = agg(b) if b else None
                if not a:
                    continue
                report.append(f"| {name} | {a['instruments']} | {a['n']:.0f} | {fmt(a['win'],1)} | {fmt(a['avg_r'])} | "
                              f"{fmt(a['pf'])} | {a['total_r']:.0f} | {fmt(a['avg_r']*100,1)} |")
                out_rows.append(dict(universe=uni, scope='all', dim=dim, bucket=name, **a))
            report.append('')

        # ---------- per signal: ADR / MCap / turnover highlights
        report.append(f'## {uni} — sygnały × ADR\n')
        header = '| sygnał | ' + ' | '.join(n for n, _, _ in BUCKETS['adr_pct']) + ' |'
        report.append(header)
        report.append('|---' * (len(BUCKETS['adr_pct']) + 1) + '|')
        for sig in sigs:
            srows = [d for d in rows if d['sig'] == sig]
            if sum(d['n'] or 0 for d in srows) < args.min_n:
                continue
            cells = []
            for name, _, _ in BUCKETS['adr_pct']:
                b = [d for d in srows if bucket_of(d['adr_pct'], BUCKETS['adr_pct']) == name]
                a = agg(b)
                cells.append(f"{fmt(a['avg_r'])} / {fmt(a['win'],1)} / {a['n']:.0f}" if a else '-')
                if a:
                    out_rows.append(dict(universe=uni, scope=sig, dim='adr_pct', bucket=name, **a))
            report.append(f'| {sig} | ' + ' | '.join(cells) + ' |')
        report.append('')

        for dim in ('mcap_m', 'turnover_m'):
            report.append(f'## {uni} — sygnały × {dim} (avgR)\n')
            report.append('| sygnał | ' + ' | '.join(n for n, _, _ in BUCKETS[dim]) + ' |')
            report.append('|---' * (len(BUCKETS[dim]) + 1) + '|')
            for sig in sigs:
                srows = [d for d in rows if d['sig'] == sig]
                if sum(d['n'] or 0 for d in srows) < args.min_n:
                    continue
                cells = []
                for name, _, _ in BUCKETS[dim]:
                    b = [d for d in srows if bucket_of(d[dim], BUCKETS[dim]) == name]
                    a = agg(b)
                    cells.append(f"{fmt(a['avg_r'])} ({a['n']:.0f})" if a else '-')
                    if a:
                        out_rows.append(dict(universe=uni, scope=sig, dim=dim, bucket=name, **a))
                report.append(f'| {sig} | ' + ' | '.join(cells) + ' |')
            report.append('')

        # ---------- filter simulation (system level)
        report.append(f'## {uni} — symulacja filtrów profilowych (cały system)\n')
        report.append('| filtr | spółek | zdarzeń | win% | avgR | PF | suma R | ΔavgR | ΔPF |')
        report.append('|---|---|---|---|---|---|---|---|---|')
        base = agg(rows)
        report.append(f"| bez filtra | {base['instruments']} | {base['n']:.0f} | {fmt(base['win'],1)} | "
                      f"{fmt(base['avg_r'])} | {fmt(base['pf'])} | {base['total_r']:.0f} | - | - |")
        filters = {
            'ADR >= 3%': lambda d: (d['adr_pct'] or 0) >= 3,
            'ADR >= 5%': lambda d: (d['adr_pct'] or 0) >= 5,
            'ADR >= 8%': lambda d: (d['adr_pct'] or 0) >= 8,
            'MCap >= 50M': lambda d: (d['mcap_m'] or 0) >= 50,
            'MCap >= 200M': lambda d: (d['mcap_m'] or 0) >= 200,
            'MCap 50M-10B': lambda d: 50 <= (d['mcap_m'] or 0) <= 10000,
            'Turnover >= 0.5M': lambda d: (d['turnover_m'] or 0) >= 0.5,
            'Turnover >= 2M': lambda d: (d['turnover_m'] or 0) >= 2,
            'ADR>=3% i Turn>=0.5M': lambda d: (d['adr_pct'] or 0) >= 3 and (d['turnover_m'] or 0) >= 0.5,
            'ADR>=5% i MCap>=50M': lambda d: (d['adr_pct'] or 0) >= 5 and (d['mcap_m'] or 0) >= 50,
        }
        for label, fn in filters.items():
            a = agg([d for d in rows if fn(d)])
            if not a:
                continue
            report.append(f"| {label} | {a['instruments']} | {a['n']:.0f} | {fmt(a['win'],1)} | {fmt(a['avg_r'])} | "
                          f"{fmt(a['pf'])} | {a['total_r']:.0f} | {a['avg_r']-base['avg_r']:+.3f} | {a['pf']-base['pf']:+.2f} |")
            out_rows.append(dict(universe=uni, scope='filter', dim='filter', bucket=label, **a))
        report.append('')

    os.makedirs('analysis', exist_ok=True)
    with open('analysis/company_profile_runs.csv', 'w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=['universe', 'scope', 'dim', 'bucket', 'n', 'instruments', 'win', 'avg_r', 'pf', 'total_r'])
        w.writeheader()
        for r in out_rows:
            w.writerow({k: r.get(k) for k in w.fieldnames})
    with open('analysis/company_profile_analysis.md', 'w', encoding='utf-8') as f:
        f.write('\n'.join(report))
    print('zapisano: analysis/company_profile_runs.csv, analysis/company_profile_analysis.md')
    print('\n'.join(report[:40]))


if __name__ == '__main__':
    main()
