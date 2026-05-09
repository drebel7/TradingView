# TradingView Pine Script v6 - drebel

Repozytorium zawiera moje wskaźniki, biblioteki i strategie napisane w **Pine Script v6**.

## Struktura projektu
/
├── DRELib/          ← Główna biblioteka (wersja 31+)
├── DRECandles/      ← Biblioteka świecowa
├── DREPerf/         ← Biblioteka do performance / backtest
├── *.pine           ← Główne skrypty wskaźników
└── README.md


## Biblioteki

### 1. DRELib (drebel/DRELib/31)
Główna biblioteka z najczęściej używanymi funkcjami:
- `generalFilter()` – filtry płynności, ceny, ADR, odległości od LoD, benchmark
- `strongBreakout()` – silne wybicia z wolumenem
- `nonBrokenExtremesPct()` – analiza non-broken lows/highs
- `openingRangeBreakout()`
- `getDefaultBenchmarkClose()`, `getWideIndexAndSectorSignalMod()` itp.

### 2. DRECandles
Funkcje związane z formacjami świecowymi (hammer, engulfing itp.).

### 3. DREPerf
Narzędzia do analizy performance, equity curve, statystyk.

## Główne wskaźniki

- **early trend strong breakout** (`ETSB_earlyTrendStrongBreakout.txt`)  
  Główny wskaźnik szukający wczesnych silnych trendów z breakoutem + dodatkowe potwierdzenia (ETH).

- Pozostałe skrypty (w folderze głównym lub podfolderach) – lista zostanie uzupełniona po dodaniu pełnej struktury.

## Kluczowe filtry (wspólne)

- Min. Turnover, Min. ADR%, zakres ceny
- Max dystans od Low of Day
- Benchmark nie w trendzie spadkowym
- Relative Strength vs benchmark
- OBV momentum
- Non-broken lows
- Silne wybicie z wolumenem
- Niezbyt wyciągnięty od MA

## Ważne informacje dev

- Wszystkie skrypty używają **//@version=6**
- Import: `import drebel/DRELib/31 as drelib`
- Testowane głównie na ramce **1D**
- Alertconditiony gotowe do użycia (ETSB, ETSB+, ETH, ET++)
- Dokumentacja Pine v6: https://github.com/codenamedevan/pinescriptv6

## Jak używać

1. Skopiuj bibliotekę DRELib do swoich bibliotek na TradingView
2. Dodaj import w skrypcie
3. Włącz/wyłącz poszczególne warunki w ustawieniach

---

**Ostatnia aktualizacja:** 2026-05