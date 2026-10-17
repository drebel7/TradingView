#!/usr/bin/env python3
"""Deep dive: how company profile (volatility, liquidity, cap, age, sector) drives signal quality.

Reads the measurements already stored in db/analysis.db (latest run per universe unless --run),
joins them with company_metric / company_profile and writes:

  analysis/profile_deep_dive.md   - the report (tables + conclusions)
  analysis/profile_deep_dive.csv  - machine readable per signal x dimension x bucket

Everything is POOLED (weighted by the signal count n) so single-trade symbols do not distort a bucket.
No new measurements are taken - this is a pure analysis of what is already in the database.
"""
import argparse
import csv
import os
import sqlite3
from collections import defaultdict

DB = 'db/analysis.db'

ADR_B = [('ADR<3', 0, 3), ('ADR3-5', 3, 5), ('ADR5-8', 5, 8), ('ADR>=8', 8, 1e9)]
TURN_B = [('T<0.5M', 0, 0.5), ('T0.5-2M', 0.5, 2), ('T2-10M', 2, 10), ('T10-50M', 10, 50), ('T>=50M', 50, 1e12)]
MCAP_B = [('<50M', 0, 50), ('50-200M', 50, 200), ('200M-1B', 200, 1000), ('1-10B', 1000, 10000), ('>10B', 10000, 1e12)]

# the two concept classes that show opposite volatility preferences in the data
QUIET_FAMILY = ('ai-htf', 'ai-htf100', 'ai-htftight', 'ai-vip')


def bname(v, spec):
    if v is None:
        return 'n/a'
    for n, lo, hi in spec:
        if lo <= v < hi:
            return n
    return 'n/a'


def agg(rows):
    rows = [r for r in rows if r['n'] and r['n'] > 0]
    n = sum(r['n'] for r in rows)
    if not n:
        return None
    sw = sum(r['sum_win_r'] or 0.0 for r in rows)
    sl = sum(r['sum_loss_r'] or 0.0 for r in rows)
    return dict(n=n, sym=len({r['ticker'] for r in rows}),
                win=sum(r['win_pct'] * r['n'] for r in rows) / n,
                avg=sum(r['avg_r'] * r['n'] for r in rows) / n,
                pf=(sw / abs(sl)) if sl else float('inf'),
                tot=sum(r['avg_r'] * r['n'] for r in rows))


def f(v, nd=2):
    if v is None:
        return '-'
    if v == float('inf'):
        return 'inf'
    return f'{v:.{nd}f}'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--run', type=int)
    ap.add_argument('--min-occ', type=int, default=40)
    args = ap.parse_args()
    con = sqlite3.connect(DB)
    if args.run:
        run_ids = (args.run,)
    else:
        run_ids = tuple(r[0] for r in con.execute('select max(id) from run group by universe_id'))
    q = f"""select u.code uni, v.sig_name sig, i.ticker, cp.sector,
                   cm.market_cap_m, cm.adr_pct, cm.avg_turnover_m, cm.hod_price, cp.years_on_exchange,
                   m.n, m.win_pct, m.avg_r, m.sum_win_r, m.sum_loss_r
            from measurement m
            join run r on r.id=m.run_id join universe u on u.id=r.universe_id
            join variant v on v.id=m.variant_id join instrument i on i.id=m.instrument_id
            left join company_metric cm on cm.instrument_id=i.id
            left join company_profile cp on cp.instrument_id=i.id
            where m.run_id in ({','.join('?' * len(run_ids))})"""
    cols = ['uni', 'sig', 'ticker', 'sector', 'mcap', 'adr', 'turn', 'price', 'years', 'n', 'win_pct', 'avg_r', 'sum_win_r', 'sum_loss_r']
    data = [dict(zip(cols, r)) for r in con.execute(q, run_ids)]
    out = []
    md = ['# Profile deep dive — signal quality vs company profile',
          '',
          f'Runs: {run_ids}; rows: {len(data)}. All statistics pooled (weighted by n).']

    for uni in sorted({d['uni'] for d in data}):
        rows = [d for d in data if d['uni'] == uni]
        md.append(f'\n## {uni}\n')
        base = agg(rows)
        md.append(f'System (all signals): {base["n"]:.0f} events, {base["sym"]} symbols, '
                  f'win {f(base["win"],1)}%, avgR {f(base["avg"])}, PF {f(base["pf"])}, total {base["tot"]:.0f}R.\n')

        # ---------------- ADR x turnover
        md.append('### ADR x turnover (avgR / PF / events)\n')
        md.append('| ADR \\ turnover | ' + ' | '.join(n for n, _, _ in TURN_B) + ' |')
        md.append('|---' * (len(TURN_B) + 1) + '|')
        for an, alo, ahi in ADR_B:
            cells = []
            for tn, tlo, thi in TURN_B:
                b = [d for d in rows if alo <= (d['adr'] or -1) < ahi and tlo <= (d['turn'] or -1) < thi]
                a = agg(b)
                if a and a['n'] >= 30:
                    cells.append(f'{f(a["avg"])} / {f(a["pf"])} / {a["n"]:.0f}')
                    out.append(dict(universe=uni, scope='all', dim='adr_x_turn', bucket=f'{an}|{tn}', **a))
                else:
                    cells.append('-')
            md.append(f'| {an} | ' + ' | '.join(cells) + ' |')
        md.append('')

        # ---------------- sectors
        md.append('### Sectors (sorted by total R; only sectors with >=100 events)\n')
        md.append('| sector | symbols | events | win% | avgR | PF | total R |')
        md.append('|---|---|---|---|---|---|---|')
        sec = defaultdict(list)
        for d in rows:
            sec[d['sector'] or 'n/a'].append(d)
        items = []
        for name, rs in sec.items():
            a = agg(rs)
            if a and a['n'] >= 100:
                items.append((name, a))
        for name, a in sorted(items, key=lambda t: -t[1]['tot'])[:15]:
            md.append(f'| {name} | {a["sym"]} | {a["n"]:.0f} | {f(a["win"],1)} | {f(a["avg"])} | {f(a["pf"])} | {a["tot"]:.0f} |')
            out.append(dict(universe=uni, scope='all', dim='sector', bucket=name, **a))
        md.append('')

        # ---------------- per signal ADR split
        md.append('### Per signal: overall vs low/high volatility (ADR 5% split)\n')
        md.append('| signal | side | events | win% | avgR | PF | total R | verdict |')
        md.append('|---|---|---|---|---|---|---|---|')
        sigs = sorted({d['sig'] for d in rows})
        for s in sigs:
            sr = [d for d in rows if d['sig'] == s]
            a_all = agg(sr)
            if not a_all or a_all['n'] < args.min_occ:
                continue
            lo = agg([d for d in sr if (d['adr'] or 0) < 5])
            hi = agg([d for d in sr if (d['adr'] or 0) >= 5])
            for label, a in (('all', a_all), ('ADR<5', lo), ('ADR>=5', hi)):
                if not a:
                    continue
                md.append(f'| {s if label == "all" else ""} | {label} | {a["n"]:.0f} | {f(a["win"],1)} | '
                          f'{f(a["avg"])} | {f(a["pf"])} | {a["tot"]:.0f} | |')
                out.append(dict(universe=uni, scope=s, dim='adr_split', bucket=label, **a))
            if lo and hi:
                pref = 'HIGH vol' if hi['avg'] > lo['avg'] * 1.15 else ('LOW vol' if lo['avg'] > hi['avg'] * 1.15 else 'both')
                md.append(f'| {s} | **pref** | | | | | | **{pref}** |')
        md.append('')

        # ---------------- filter simulation
        md.append('### Profile filters on the whole system\n')
        md.append('| filter | symbols | events | win% | avgR | PF | total R | ΔavgR | ΔPF |')
        md.append('|---|---|---|---|---|---|---|---|---|')
        md.append(f'| none | {base["sym"]} | {base["n"]:.0f} | {f(base["win"],1)} | {f(base["avg"])} | {f(base["pf"])} | {base["tot"]:.0f} | - | - |')
        flt = {
            'ADR>=5%': lambda d: (d['adr'] or 0) >= 5,
            'ADR>=3%': lambda d: (d['adr'] or 0) >= 3,
            'ADR<5% (quiet)': lambda d: (d['adr'] or 0) < 5,
            'turnover 2-50M': lambda d: 2 <= (d['turn'] or 0) <= 50,
            'turnover>=0.5M': lambda d: (d['turn'] or 0) >= 0.5,
            'mcap>=50M': lambda d: (d['mcap'] or 0) >= 50,
            'age>=3y': lambda d: (d['years'] or 0) >= 3,
            'ADR>=5 & turn2-50M': lambda d: (d['adr'] or 0) >= 5 and 2 <= (d['turn'] or 0) <= 50,
            'ADR>=5 & turn2-50 & age>=3': lambda d: (d['adr'] or 0) >= 5 and 2 <= (d['turn'] or 0) <= 50 and (d['years'] or 0) >= 3,
            'proposed: HIGH-vol families ADR>=5, QUIET families ADR<5': None,
        }
        # market-aware rule derived from the MCap x ADR control:
        # GPW = ADR>=5 everywhere; US = ADR>=5 only for MCap>=200M (high-ADR small caps are bad there)
        if uni.startswith('GPW'):
            flt['MARKET-AWARE: ADR>=5'] = lambda d: (d['adr'] or 0) >= 5
        else:
            flt['MARKET-AWARE: ADR>=5 & MCap>=200M'] = lambda d: (d['adr'] or 0) >= 5 and (d['mcap'] or 0) >= 200
        for label, fn in flt.items():
            if fn is None:
                b = [d for d in rows if (d['sig'] in QUIET_FAMILY and (d['adr'] or 0) < 5) or
                     (d['sig'] not in QUIET_FAMILY and (d['adr'] or 0) >= 5)]
            else:
                b = [d for d in rows if fn(d)]
            a = agg(b)
            if not a:
                continue
            md.append(f'| {label} | {a["sym"]} | {a["n"]:.0f} | {f(a["win"],1)} | {f(a["avg"])} | {f(a["pf"])} | '
                      f'{a["tot"]:.0f} | {a["avg"]-base["avg"]:+.2f} | {a["pf"]-base["pf"]:+.2f} |')
            out.append(dict(universe=uni, scope='filter', dim='filter', bucket=label, **a))
        md.append('')

    os.makedirs('analysis', exist_ok=True)
    with open('analysis/profile_deep_dive.csv', 'w', newline='', encoding='utf-8') as fh:
        w = csv.DictWriter(fh, fieldnames=['universe', 'scope', 'dim', 'bucket', 'n', 'sym', 'win', 'avg', 'pf', 'tot'])
        w.writeheader()
        for r in out:
            w.writerow({k: r.get(k) for k in w.fieldnames})
    open('analysis/profile_deep_dive.md', 'w', encoding='utf-8').write('\n'.join(md))
    print('\n'.join(md))


if __name__ == '__main__':
    main()
