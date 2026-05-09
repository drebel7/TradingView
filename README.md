# TradingView Pine Script v6 - drebel

Repozytorium moich wskaźników, bibliotek i narzędzi do TradingView w **Pine Script v6**.

## Struktura projektu

TradingView/
├── README.md
├── src/                    ← źródła
│   ├── indicators/         ← Wskaźniki
│   ├── libraries/          ← Biblioteki
│   	├── DRELib/
│   	├── DRECandles/
│   	└── DREPerf/
│   ├── strategies/         ← Strategie
│   └── zzOthers/           ← źródła autorstwa innych użytkowników, znalezione w internecie
│
├── tickers/                ← Listy tickerów (opcjonalnie)
│
└── docs/                   ← Dokumentacja (opcjonalnie)


## Biblioteki (`src/libraries/`)

- **DRELib** — główna biblioteka (wersja 31+)
- **DRECandles** — formacje świecowe
- **DREPerf** — analiza performance i statystyki

## Wskaźniki (`src/indicators/`)

- `ETSB_earlyTrendStrongBreakout.pine` — główny wskaźnik Early Trend Strong Breakout + ETH

*(Pozostałe wskaźniki będą dodawane z krótkim opisem poniżej)*

## Jak używać

1. Skopiuj foldery z `src/libraries/` jako biblioteki na TradingView.
2. Import: `import drebel/DRELib/31 as drelib`
3. Dodawaj skrypty z `src/indicators/`.

## Ważne

- Wszystkie pliki w wersji **v6**
- Rozszerzenie `.pine`
- Główna ramka: **1D**

---

**Ostatnia aktualizacja:** 2026-05