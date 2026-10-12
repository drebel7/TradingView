#!/usr/bin/env python3
"""
gpw_watchlist_sync.py
=====================
Dopisuje na koncu watchlisty spolki z Glownego Rynku GPW, ktorych w niej brakuje.

Zrodlo: https://www.gpw.pl/spolki?limit=1000
(domyslna strona pokazuje tylko 20 pozycji; parametr ?limit=1000 renderuje cala
liste serwerowo). Ticker jest wyciagany z tekstu linku "NAZWA (TICKER)".

Skrypt:
  1. pobiera liste spolek Glownego Rynku i zbiera tickery z linkow
     spolka?isin=... (tekst "(TICKER)"),
  2. czyta plik watchlisty i zbiera istniejace tickery z tokenow "GPW:XXX",
  3. dopisuje brakujace na KONCU pliku jako ",GPW:XXX" (posortowane),
  4. jest idempotentny (ponowne uruchomienie nic nie zmienia).

Uzycie:
  python3 scripts/gpw_watchlist_sync.py [--watchlist watchlist/.GPW_NC.txt] [--dry-run]
"""

import argparse
import re
import sys
import time
import urllib.request
from pathlib import Path

GPW_URL = "https://www.gpw.pl/spolki?limit=1000"
UA = "Mozilla/5.0 (compatible; gpw-watchlist-sync/1.0)"
MIN_EXPECTED = 300  # sanity-check: zabezpieczenie przed zmiana ukladu strony GPW

ROW_RE = re.compile(r'<a[^>]*href="spolka\?isin=([0-9A-Z]+)"[^>]*>([\s\S]*?)</a>')
TICKER_RE = re.compile(r"\(([0-9A-Z]{1,8})\)\s*$")
TAG_RE = re.compile(r"<[^>]+>")


def fetch_gpw_tickers(url, retries=4):
    """Return {TICKER: company name} for every company on the GPW main market.

    Retries on transient network errors (timeouts, truncated/incomplete reads).
    Raises if the page cannot be fetched or yields too few rows (layout change).
    """
    last_err = None
    for attempt in range(1, retries + 1):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            html = urllib.request.urlopen(req, timeout=30).read().decode("utf-8", "replace")
            tickers = {}
            for m in ROW_RE.finditer(html):
                text = re.sub(r"\s+", " ", TAG_RE.sub("", m.group(2))).strip()
                tm = TICKER_RE.search(text)
                if tm:
                    tickers.setdefault(tm.group(1), text[: tm.start()].strip())
            if len(tickers) >= MIN_EXPECTED:
                return tickers
            last_err = RuntimeError(
                f"sparsowano tylko {len(tickers)} tickerow (oczekiwano >= {MIN_EXPECTED}); "
                f"uklad strony GPW mogl sie zmienic")
        except Exception as e:  # transient network / truncated read
            last_err = e
        if attempt < retries:
            print(f"[warn] pobranie nieudane (proba {attempt}/{retries}): {last_err}; ponawiam...",
                  file=sys.stderr)
            time.sleep(2 * attempt)
    raise RuntimeError(f"nie udalo sie pobrac listy GPW z {url}: {last_err}")


def existing_gpw_tickers(text):
    """Tickers already present in a watchlist file (tokens "GPW:XXX")."""
    return {t.strip()[4:] for t in text.split(",") if t.strip().startswith("GPW:")}


def main():
    ap = argparse.ArgumentParser(
        description="Append missing GPW main-market tickers to a watchlist")
    ap.add_argument("--watchlist", default="watchlist/.GPW_NC.txt")
    ap.add_argument("--url", default=GPW_URL)
    ap.add_argument("--dry-run", action="store_true", help="tylko pokaz, nie zapisuj")
    args = ap.parse_args()

    path = Path(args.watchlist)
    if not path.is_file():
        print(f"ERROR: brak pliku watchlisty: {path}", file=sys.stderr)
        return 1

    try:
        gpw = fetch_gpw_tickers(args.url)
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2

    raw = path.read_text(encoding="utf-8")
    existing = existing_gpw_tickers(raw)
    missing = sorted(t for t in gpw if t not in existing)

    print(f"GPW Glowny Rynek: {len(gpw)} | watchlist: {len(existing)} tickerow GPW")
    if not missing:
        print("nic do dodania - watchlista jest kompletna")
        return 0

    print(f"brakujace ({len(missing)}): " + ", ".join(f"GPW:{t}" for t in missing))
    for t in missing:
        print(f"  GPW:{t}  {gpw[t]}")
    if args.dry_run:
        print("(dry-run - plik niezmieniony)")
        return 0

    path.write_text(raw.rstrip("\n") + "".join(f",GPW:{t}" for t in missing), encoding="utf-8")
    print(f"zaktualizowano {path}: +{len(missing)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
