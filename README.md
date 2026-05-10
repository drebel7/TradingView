# TradingView Pine Script v6 - drebel

Repozytorium moich wskaźników, bibliotek i narzędzi do TradingView w **Pine Script v6**.

Całość aktualna znajduje się na GitHubie pod adresem: https://github.com/drebel7/TradingView (branch `main`).

**Dokumentacja Pine Script v6:** [codenamedevan/pinescriptv6](https://github.com/codenamedevan/pinescriptv6)

Nie zmieniaj i nie usuwaj linii komentarzy.

## Struktura projektu

TradingView/
├── README.md
├── .gitignore
│
├── src/                          ← Główna zawartość
│   ├── indicators/               ← Gotowe wskaźniki (+ README.md)
│   ├── libraries/                ← Biblioteki (+ README.md)
│   │   ├── DRELib/               ← Główna biblioteka (v31+)
│   │   ├── DRECandles/           ← Formacje świecowe
│   │   └── DREPerf/              ← Analiza performance
│   ├── strategies/               ← Strategie (w przygotowaniu)
│   └── zzOthers/                 ← Skrypty innych autorów
│
├── watchlist/                    ← Listy tickerów
└── docs/                         ← Dokumentacja (opcjonalnie)


Szczegółowe opisy znajdują się w plikach `README.md` w poszczególnych podkatalogach.

## Biblioteki (`src/libraries/`)

- **DRELib** — główna i najważniejsza biblioteka (wersja 31+)
- **DRECandles** — funkcje do analizy świec i formacji
- **DREPerf** — narzędzia do statystyk i success rate

Import przykład:  
`import drebel/DRELib/31 as drelib`

## Wskaźniki (`src/indicators/`)

Główny wskaźnik:  
**ETSB_earlyTrendStrongBreakout.pine** — Early Trend Strong Breakout + wariant ETH (hammer)

Pełna lista wskaźników w [`src/indicators/README.md`](src/indicators/README.md).

## Jak używać

1. Skopiuj foldery z `src/libraries/` jako **biblioteki** na TradingView.
2. Importuj biblioteki w skryptach.
3. Dodawaj gotowe wskaźniki z `src/indicators/`.

## Ważne

- Wszystkie pliki w wersji **v6**
- Rozszerzenie `.pine`
- Główna ramka czasowa: **1D**

---

**Ostatnia aktualizacja:** 2026-05-10