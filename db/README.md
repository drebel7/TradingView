# Baza analiz sygnałów (`db/analysis.db`)

SQLite-owa baza zbierająca wyniki analiz wskaźników z katalogu `analysis/`:
surowe pomiary per spółka, warianty sygnałów wraz z **wartościami parametrów**,
kod skryptów Pine, składy uniwersów i dane spółek z tabeli **DRE Info**.

Baza jest commitowana do repozytorium (zgodnie z decyzją projektową), ale jest
w pełni odtwarzalna z CSV i kodu poleceniami poniżej.

## Pipeline

```bash
python3 scripts/db_init.py            # schemat (db/schema.sql) -> db/analysis.db
python3 scripts/db_import_scripts.py  # kod skryptów, sygnały, warianty, parametry
python3 scripts/db_import_analysis.py # analysis/*.csv -> runy + pomiary
python3 scripts/db_import_company.py  # analysis/*_INFO_*.csv -> dane spółek (DRE Info)
python3 scripts/db_verify.py          # kontrola: widoki vs pliki *_SUMMARY*.csv
```

Zbieranie danych spółek (DRE Info):

```bash
python3 scripts/tv_info_scraper.py --watchlist watchlist/.PL.txt
python3 scripts/tv_info_scraper.py --watchlist watchlist/.US.txt
python3 scripts/db_import_company.py
```

`db_import_analysis.py --verify` uruchamia weryfikację od razu po imporcie.
Wszystkie importy są **idempotentne** — można je uruchamiać wielokrotnie.
`db_init.py --force` odtwarza bazę od zera.

> **Zmiana schematu**: `db_init.py` używa `CREATE TABLE IF NOT EXISTS`, więc nie
> zmienia istniejących tabel. Po podniesieniu `SCHEMA_VERSION` skrypt odmówi
> pracy z ostrzeżeniem — trzeba wtedy `db_init.py --force` i powtórzyć importy
> (baza jest w pełni odtwarzalna z CSV i kodu). Aktualny schemat: **v2**
> (`company_metric.market_cap_m`; usunięte `lod_price`, `lod_dist_pct`,
> `dtt_vol_pct`, `dtt_vol_proj_pct`, `dtt_time_pct`).

## Model danych

| Tabela | Znaczenie |
|---|---|
| `script`, `script_revision` | pliki `.pine` (kod, sha256, commit git) + historia wersji |
| `script_dependency` | importy bibliotek (`DRELib/39`, `DREPerf/27`) |
| `script_param` | inputy skryptu (`defval`) = konfiguracja pomiaru |
| `signal` | sygnał bazowy (`CapLow`, `mtsb`, `rmv1`, ...) |
| `variant` | nazwa z kolumny `sig` (`capLowTTT_95`), rola i parametry (JSON) |
| `variant_param` | znormalizowane parametry (`name`/`type`/`value_num|bool|text`) |
| `universe`, `universe_member`, `universe_member_group` | uniwersa i aktualny skład z watchlist |
| `instrument` | spółka (`GPW:AQU`, `NASDAQ:GOOGL`) |
| `company_profile`, `company_metric` | dane z tabeli DRE Info (cechy + snapshoty dzienne) |
| `run` | jeden scrape = jeden plik CSV (data, uniwersum, skrypt, wersja kodu) |
| `run_symbol` | status symbolu w runie (`ok` / `no_data` / `recovered` / `fail`) |
| `measurement` | wynik wariantu dla spółki: `n, win_pct, avg_r, pf, max_dd, score, ...` |

### Role wariantów

* `original` — sygnał oryginalny ze skryptu bazowego (np. `CapLow` w ETSB);
  parametry = domyślne inputy skryptu (`params_source='script_defaults'`),
* `equivalent` — wariant przeglądu replikujący oryginał (komentarz
  `// Sanity check: X == original default` w `perf_opt_sig_*.pine`),
* `variant` — pozostały wariant parametryczny (ma `variant_param`).

### Skąd biorą się parametry

`scripts/pine_variant_parser.py` czyta kod Pine:

* sygnatury fabryk (`capLowCalc(int _lowLookback, ..., bool _highAbovePrev) =>`)
  i wywołania (`capLowTTT_95 = capLowCalc(200, 150, 95, true, true, true)`),
* nazwy sygnałów z tabeli wskaźnika (`renderRow` / `renderQualityRow`),
* odpowiednik oryginału z komentarza `Sanity check:` (+ mały override dla
  niejednoznacznych przypadków),
* skrypty bez fabryk (`ETSB`, `DRE parabolic top`, `DRE When-Sell`) dostają po
  jednym sygnale na nazwę z tabeli, z `params_source='script_defaults'`.

Nowy skrypt-przegląd `perf_opt_sig_<x>.pine` wymaga tylko dopisania mapowania
w `BASE_SIGNAL_MAP` (`scripts/db_import_scripts.py`), jeśli `<x>` nie odpowiada
nazwie sygnału z ETSB.

## Widoki (do analiz)

| Widok | Zawartość |
|---|---|
| `v_signal_summary` | podsumowanie per run (odpowiednik `<UNIWERSUM>_<SIG>_SUMMARY.csv`) |
| `v_signal_summary_latest` | podsumowanie z najnowszych runów per uniwersum |
| `v_signal_summary_all` | wszystkie uniwersa razem (odpowiednik `*_SUMMARY_ALL.csv`) |
| `v_signal_by_mcap` | wyniki sygnałów w podziale na **kubełek kapitalizacji** spółki |
| `v_signal_by_sector` | wyniki sygnałów w podziale na **sektor** spółki |
| `v_company_signal` | **pomiary sygnałów wzbogacone danymi spółki** (MCap, ADR, Sharpe, EPS, sektor…) — podstawa własnych zapytań screeningowych |
| `v_baseline_vs_best` | oryginał vs replika vs najlepszy wariant (jak `compare_signal_variants.py`) |
| `v_variant_params` | parametry wariantu w formie `nazwa=wartość` |
| `v_measurement_ok` / `v_measurement_uniq` | pomiary z sygnałem / zdeduplikowane per spółka |
| `v_measurement_recovered` | dane odzyskane z timeoutów (poza podsumowaniami) |
| `v_run_gaps` | symbole nieodczytane (`NO_DATA`) |
| `v_run_latest`, `v_measurement_latest` | pomocnicze |
| `v_instrument_company` | spółka + najnowszy snapshot DRE Info + kubełek MCap |
| `v_company_card` | karta spółki (widok na `v_instrument_company`) |

Kubełki kapitalizacji (`mcap_bucket`, w milionach waluty instrumentu):
`micro` <50, `small` <200, `mid` <1000, `large` <10000, `mega` ≥10000,
`unknown` = brak danych o akcjach (`n/a` w karcie).

Logika agregacji w widokach jest 1:1 z `scripts/summarize_signals.py`
(`win_pct`/`avg_r`/`max_dd` ważone przez `n`, `pf` z sum brutto, mediany per
spółka, `score_pos_pct`). Wszystkie zakresy (`run` / `latest` / `mcap` /
`sector`) liczy jeden widok `v_signal_summary_scope` — kolumna `scope`
wybiera zakres, a `dim1`/`dim2` niosą wymiar (uniwersum + kubełek/sektor).

## Konwencje i pułapki

* **`measurement.grp`** — ten sam ticker może być w kilku grupach watchlisty
  (np. US: `FAANG` i `AI`), więc pomiar jest zapisywany per wiersz CSV.
  Widoki podsumowań liczą zgodnie z tym (jak pliki `*_SUMMARY.csv`).
  Do statystyk „na spółkę" służy `v_measurement_uniq`.
* **`pf = NULL`** oznacza brak strat (w CSV: puste pole / znak ∞).
* **`status`**: `ok` (n>0), `no_signal` (n=0), `recovered` (odzyskane z
  `--salvage-timeouts`, poza podsumowaniami), `fail`.
* **`run_symbol`** rejestruje `NO_DATA` (symbol nieodczytany) niezależnie od
  wariantów — patrz `v_run_gaps`.
* **Wersja kodu**: `run.script_revision_id` wskazuje dokładną wersję skryptu,
  która wyliczyła pomiary.

## CLI

```bash
python3 scripts/db_query.py runs                     # lista runów
python3 scripts/db_query.py summary --universe GPW   # podsumowanie sygnałów
python3 scripts/db_query.py summary --all --min-occ 500
python3 scripts/db_query.py top --by score_mean --min-occ 100
python3 scripts/db_query.py compare --signal CapLow  # oryginał/replika/best
python3 scripts/db_query.py trend --sig capLowTFT_95 --universe GPW
python3 scripts/db_query.py variants --signal vip    # warianty + parametry
python3 scripts/db_query.py params --sig vip50F      # parametry wariantu
python3 scripts/db_query.py company GPW:PKO
python3 scripts/db_query.py gaps                     # luki danych
python3 scripts/db_query.py screen --max-mcap 200 --min-adr 4 --min-occ 50
python3 scripts/db_query.py sql "SELECT * FROM v_signal_summary_all LIMIT 5"
```

### Screening: sygnały a fundamenty spółek

`screen` przesiewa spółki po kryteriach z DRE Info i liczy im wyniki sygnałów
(agregacja jak w widokach, na najnowszych runach, bez dublowania spółek z wielu
grup watchlisty):

```bash
# najlepsze warianty CapLow na spółkach < 200 M z ADR > 4%
python3 scripts/db_query.py screen --signal CapLow --max-mcap 200 --min-adr 4 --min-occ 20

# wszystkie sygnały na mikro/małych spółkach, płynnych, sortowane po medianie
python3 scripts/db_query.py screen --bucket micro,small --min-turnover 0.5 \
    --by median_avg_r --min-occ 200

# konkretny sektor, tylko spółki z danymi o kapitalizacji
python3 scripts/db_query.py screen --sector Energy --only-known-mcap --by avg_r
```

Dostępne filtry: `--min-mcap/--max-mcap`, `--bucket` (micro,small,mid,large,mega,unknown),
`--min-adr/--max-adr`, `--min-turnover`, `--min-sharpe`, `--min-years`,
`--sector`, `--industry`, `--only-known-mcap`, `--require-company`, `--min-occ`,
`--by` (score_mean, avg_r, pf, win_pct, score_pos_pct, median_avg_r, occurrences, symbols).

To samo można zrobić w SQL przez `v_company_signal` (pomiary + fundamenty):

```sql
SELECT cs.ticker, cs.sig_name, cs.n, cs.avg_r, cs.score, cs.market_cap_m, cs.adr_pct
FROM v_company_signal cs
JOIN v_run_latest l ON l.id = cs.run_id
WHERE cs.status = 'ok' AND cs.market_cap_m < 200 AND cs.adr_pct > 4
ORDER BY cs.score DESC LIMIT 20;
```

## Dane z DRE Info (`company_profile` / `company_metric`)

Zbiera je `scripts/tv_info_scraper.py` (tabela label→wartość wskaźnika
`src/indicators/DRE Info.pine`), a do bazy wgrywa `scripts/db_import_company.py`.

```bash
# 1. Zbieranie (TradingView Desktop z dodanym wskaźnikiem "DRE Info";
#    scraper sam go uruchomi, ustawi interwał D i wymusi komplet pól karty)
python3 scripts/tv_info_scraper.py --watchlist watchlist/.PL.txt
python3 scripts/tv_info_scraper.py --watchlist watchlist/.US.txt --tag US_INFO

# 2. Import (snapshot_date z nagłówka '# generated:'; --date nadpisuje)
python3 scripts/db_import_company.py
```

Wynik: `analysis/<TAG>_<YYYYMMDD>.csv` (domyślnie `PL_INFO_*.csv`) z jednym
wierszem na spółkę: `group, symbol, status, ticker_table, market_cap_m, adr_pct,
atr, avg_turnover_m, hod_price, ma_dist_prctl, sharpe, eps_up_1y, eps_days_1y,
eps_up_2y, eps_days_2y, sector, industry, bench_index, bench_mod,
n_broken_extremes_pct, n_broken_mod, years_on_exchange, raw`.

Zasady:

* `market_cap_m` to kapitalizacja w **milionach** waluty instrumentu; wskaźnik
  pokazuje ją jako `MCap` w pierwszej linii pod tickerem (`str.tostring(..., format.volume)`,
  czyli `6.376M`, `10.06B`, `890K`), a scraper przelicza sufiksy K/M/B/T na liczby,
* wiersze **`LoD price`, `LoD dist. [%]`, `Dtt vol. [%] (proj.)` i `Dtt time [%]`**
  są świadomie **poza bazą i poza CSV** (nadal widać je na wykresie); ich wartości
  pozostają w kolumnie `raw` (pełny zrzut `label | value`), więc nic nie ginie,

* etykiety tabeli dopasowywane są po znormalizowanym prefiksie, więc ukryte
  wiersze zostają puste (`--set-input-defaults` i tak wymusza komplet),
* pełny zrzut `label | value` ląduje w kolumnie `raw` (audyt, odporność na
  zmiany wskaźnika),
* `ticker_table` (z `Show ticker`) służy do kontroli, czy tabela dotyczy
  właściwej spółki — niezgodność trafia do ostrzeżeń importera,
* import tworzy też `run` (z `script_id` wskaźnika DRE Info) i `run_symbol`,
  odświeża skład uniwersum oraz ustawia `company_metric.run_id`,
* `sector`, `industry`, `bench_index`, `years_on_exchange` trafiają do
  `company_profile` (cechy wolnozmienne), reszta do `company_metric`
  (snapshot dzienny, klucz: spółka + data).

```bash
python3 scripts/db_query.py company GPW:PKO      # karta spółki
python3 scripts/db_query.py companies --limit 20
python3 scripts/db_query.py companies --sector Financials
python3 scripts/db_query.py sql "SELECT ticker, adr_pct, sharpe FROM v_company_card \
                                 WHERE sharpe > 1.5 ORDER BY sharpe DESC"
```

## Przeglądarka w przeglądarce (`scripts/db_browser.py`)

Lekki serwer HTTP na bibliotece standardowej (bez instalacji czegokolwiek) i
strona `db/browser.html`:

```bash
python3 scripts/db_browser.py            # http://127.0.0.1:8765
python3 scripts/db_browser.py --open --port 9000
```

Co potrafi:

- **wszystkie tabele i widoki** w panelu bocznym, z liczbą wierszy i podpowiedzią
  kolumn (liczniki doliczają się w tle; bardzo wolne widoki pokazują `—`),
- stronicowany podgląd danych (25/100/250/1000 wierszy), **sortowanie** po
  kliknięciu nagłówka, **filtr LIKE** po wszystkich kolumnach lub po wybranej,
- **szczegóły wiersza** (wszystkie kolumny, pełne wartości; długie teksty, np.
  `script.code`, dociągane osobno i pokazywane jako `<pre>`; JSON formatowany),
- **schemat** obiektu: kolumny z typami, klucze obce, indeksy, SQL z `sqlite_master`,
- **eksport** bieżącego widoku (z filtrem i sortowaniem) do **CSV** lub **JSON**,
- **zakładka SQL**: dowolne zapytanie czytające (`SELECT`/`WITH`/`PRAGMA`/`EXPLAIN`),
  `Ctrl+Enter` uruchamia; zapytania zapisujące i wiele instrukcji są odrzucane,
- skrót `/` fokusuje szukanie, `Esc` zamyka okno szczegółów.

Bezpieczeństwo i wydajność:

- baza otwierana jest **tylko do odczytu** (`file:…?mode=ro`) — UI nie może
  zmienić danych, nawet przez zakładkę SQL,
- nazwy obiektów i kolumn są walidowane względem `sqlite_master`, więc nie da się
  nimi wstrzyknąć SQL-a; identyfikatory są dodatkowo cytowane,
- odpowiedzi stronicowane (max 1000 wierszy na żądanie), komórki tekstowe obcinane
  do 400 znaków z możliwością wczytania całości,
- domyślnie nasłuch tylko na `127.0.0.1`; `--host 0.0.0.0` świadomie odsłania UI
  w sieci (bez autoryzacji!),
- widoki podsumowań (`v_signal_summary*`, `v_signal_by_*`, `v_baseline_vs_best`)
  liczą agregaty na żądanie — pierwsze wczytanie trwa ~3 s (cztery zakresy
  agregacji w jednym widoku), tabele otwierają się natychmiast;
  `db_verify.py` pobiera widoki raz (2 zapytania) i porównuje w Pythonie, więc
  pełna weryfikacja 528 wierszy trwa ~6 s.

## Statystyki bazy (stan: 2026-10-14)

* 60 skryptów (60 rewizji), 63 sygnały, 203 warianty (148 z parametrami z kodu),
  483 parametry wariantów, 802 inputy skryptów,
* 18 runów, 216 734 pomiary (154 617 z sygnałem, 62 117 bez sygnału),
  52 symbole bez danych,
* weryfikacja: 528 wierszy plików `*_SUMMARY*.csv` / `BASE_*.csv` — 0 niezgodności,
* rozmiar bazy ~32 MB (VACUUM uruchamia się automatycznie po imporcie),
* dane spółek (DRE Info, 2026-10-15): 1236 spółek (434 GPW_NC + 802 US_BIG),
  1183 z kapitalizacją (`market_cap_m`),
* dane DRE Info (GPW_NC, 2026-10-14): 434 snapshoty spółek + 434 profile
  (294 z indeksem sektorowym), run_id 19 powiązany z `src/indicators/DRE Info.pine`.

## Opcje importera

```bash
python3 scripts/db_import_analysis.py --keep-raw          # pełny surowy wiersz CSV
python3 scripts/db_import_analysis.py --salvage-timeouts  # odzyskaj dane z NO_DATA
python3 scripts/db_import_analysis.py --dry-run           # nic nie zapisuj
```

* `--keep-raw` — domyślnie `raw` trafia do bazy tylko dla diagnostyki
  (`NO_DATA` / `recovered` / `fail`); metryki i tak są w kolumnach, a pełny
  wiersz pozostaje w pliku CSV. Flaga zapisuje surowy wiersz dla wszystkich
  pomiarów (baza rośnie wtedy z ~31 MB do ~44 MB).
* `--salvage-timeouts` — z 52 wierszy `NO_DATA` część niesie w komunikacie
  kompletną tabelę (timeout po odczytaniu); takie wiersze wchodzą jako
  `measurement.status='recovered'` i `run_symbol.status='recovered'`, poza
  widokami podsumowań (weryfikacja z plikami SUMMARY nadal przechodzi).
