# TradingView Pine Script v6 - drebel

Repozytorium moich wskaźników, bibliotek i narzędzi do TradingView w **Pine Script v6**.
Całość aktualna znajduje się na GitHubie pod adresem: https://github.com/drebel7/TradingView w branchu main.

Tu jest repozytorium z dokumentacją PineScript v6 w formacie markdown: https://github.com/codenamedevan/pinescriptv6. Pusługuj się tą dokumentacją, aby zrozumieć lepiej język i działanie PineScript aby uniknąć błędów.

Nie zmieniaj i nie usuwaj linii komentarzy.

## Struktura projektu

TradingView/
├── README.md
├── .gitignore
│
├── src/                          ← Główna zawartość
│   ├── indicators/               ← Gotowe wskaźniki
│   ├── libraries/                ← Biblioteki
│   │   ├── DRELib/
│   │   ├── DRECandles/
│   │   └── DREPerf/
│   ├── strategies/               ← Strategie (w przygotowaniu)
│   └── zzOthers/                 ← Skrypty innych autorów / znalezione w internecie
│
├── watchlist/                    ← Listy tickerów
└── docs/                         ← Dokumentacja (opcjonalnie)


## Biblioteki (`src/libraries/`)

- **DRELib** — główna biblioteka (wersja 31+)  
  Najważniejsza. Zawiera filtry ogólne, silne breakouty, analizę non-broken ekstremów, benchmarki, opening range itp.

- **DRECandles** — formacje świecowe  
  Funkcje do analizy cieni, korpusu świec oraz popularnych formacji (hammer, engulfing itp.).

- **DREPerf** — analiza performance  
  Narzędzia do obliczania success rate, średnich zwrotów, statystyk sygnałów.

## Wskaźniki (`src/indicators/`)

- **ETSB_earlyTrendStrongBreakout.pine** — główny wskaźnik *Early Trend Strong Breakout* + warianty ETH (hammer)

*(Kolejne wskaźniki będą dodawane z opisami)*

## Jak używać

1. Skopiuj foldery z `src/libraries/` jako **biblioteki** na TradingView.
2. Import w skryptach: `import drebel/DRELib/31 as drelib`
3. Dodawaj skrypty z `src/indicators/`.

## Ważne

- Wszystkie pliki w wersji **v6**
- Rozszerzenie `.pine`
- Główna ramka: **1D**

---

**Ostatnia aktualizacja:** 2026-05-09