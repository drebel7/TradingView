# ETSB-ia — log iteracji optymalizacyjnych

Cel: podnosić skuteczność sygnałów `ai-*` przez iteracyjne zmiany parametrów/algorytmów,
z zachowaniem każdej wersji skryptu (`variants/ETSB-ia_itN.pine`) i danych w bazie
(`db/analysis.db`: `script_revision` po sha256 + `run`/`measurement` per iteracja).

Metoda każdej iteracji:
1. zmiany w `src/indicators/ETSB-ia.pine` (parametry/algorytmy),
2. `pine check` (0 błędów) + push do TradingView (hash zgodny z plikiem),
3. archiwum: `variants/ETSB-ia_itN.pine`,
4. scrape (GPW_NC, w iteracjach walidacyjnych też US_BIG),
5. `summarize_signals.py` → `analysis/<UNIWERSUM>_<TAG>_SUMMARY.csv`,
6. `db_import_scripts.py` + `db_import_analysis.py` + `db_verify.py`,
7. porównanie z poprzednią iteracją (`/tmp/opencode/iter_compare.py`),
8. czyszczenie surowych CSV (dane są już w bazie).

---

## IT0 — baseline (EP + market timing, 30 sygnałów)
- Plik: `variants/ETSB-ia_baseline.pine` (1173 linie)
- Zmiany: dodane `ai-ep` / `ai-ep20` (Episodic Pivot) + moduł market timing
  (distribution days + follow-through day, bramka `f_gate` na wszystkie sygnały, domyślnie OFF)
- Poprawka: limit 64 plotów — zakomentowane 6 debugowych `plot()` (AVWAP×3, pivot VCP, flaga HTF×2)
  i `plotshape` FTD (został `bgcolor`)
- Scrape: GPW_NC_IT0 (434/434) + US_BIG_IT0 (843/843), import do bazy, `db_verify` 0 niezgodności
- Kontrola regresji: 28 wcześniejszych sygnałów **identyczne** jak w runie ETSBIA3 (0 różnic)
- **Wyniki GPW_NC (top):**
  | sygnał | win% | occ | avgR | PF | maxDD | score |
  |---|---|---|---|---|---|---|
  | ai-ep20 | 31.5 | 54 | 0.49 | 1.78 | 1.31 | **+0.47** |
  | ai-caplow | 31.9 | 620 | 0.68 | 2.04 | 1.86 | +0.34 |
  | ai-htf100 | 34.0 | 47 | 0.36 | 1.56 | 0.72 | +0.32 |
  | ai-flatb | 38.7 | 1910 | 0.62 | 2.07 | 2.84 | +0.27 |
  | ai-wonhp | 44.5 | 153 | 0.27 | 1.53 | 3.51 | +0.21 |
  | ai-mtsb | 32.0 | 15615 | 0.34 | 1.54 | 12.41 | +0.20 |
  | ai-ep | 27.2 | 242 | 0.23 | 1.35 | 1.92 | +0.01 |
- Wniosek: **`ai-ep20` (gap ≥20%) to najlepszy sygnał z 30** — potwierdza tezę Qullamaggiego,
  że najlepsze EP to największe gappy; `ai-ep` (10%+) jest przeciętny.

## IT1 — bramka rynkowa ON (distribution days + FTD) + fallback wolumenu
- Plik: `variants/ETSB-ia_it1.pine`
- Zmiany:
  1. `iMktGateOn` default `false` → **`true`** (bramka filtruje wszystkie sygnały: ploty, alerty, tabelę),
  2. fallback: gdy benchmark nie ma wolumenu (`na(benchVolume)`, np. SPX/NDX/WIG), distribution day
     i FTD oceniane tylko po zamknięciu (bez warunku wolumenu).
- Scrape: GPW_NC_IT1 (434/434), import + `db_verify` (2 kosmetyczne niezgodności: `0.0` vs `None`
  dla sygnałów z zerową liczbą wystąpień — `ai-ep20`, `ai-wonhp`)
- **Wynik: 23 sygnały poprawione, 4 pogorszone** (pogorszenia przy próbkach 6–23 zdarzeń = szum):
  | sygnał | win% IT0→IT1 | score IT0→IT1 | occ IT0→IT1 |
  |---|---|---|---|
  | ai-flatb | 38.7 → **55.7** | 0.27 → **1.02** | 1910 → 88 |
  | ai-caplow | 31.9 → **50.0** | 0.34 → 0.73 | 620 → 18 |
  | ai-et3 | 31.1 → 43.5 | −0.03 → **0.78** | 4682 → 186 |
  | ai-et1yh | 31.4 → 45.3 | −0.20 → **0.70** | 2711 → 95 |
  | ai-vwaptag | 19.7 → 25.6 | **−0.86 → +0.88** | 7675 → 203 |
  | ai-vcp2 | 30.2 → 33.3 | −0.21 → **+0.72** | 804 → 33 |
  | ai-wonturn | 24.9 → 28.4 | −0.39 → **+0.48** | 2280 → 67 |
  | ai-ragpb | 18.6 → 22.0 | −0.70 → +0.04 | 2171 → 50 |
  | ai-mtsb | 32.0 → 42.3 | 0.20 → 0.46 | 15615 → 553 |
- ⚠️ Koszt: ~10–25× mniej zdarzeń; `ai-ep20` i `ai-wonhp` **0 wystąpień** (rzadkie sygnały × rzadkie okna).

## IT2 — reguła trend-MA zamiast distribution days + gap EP 10% → 15%
- Plik: `variants/ETSB-ia_it2.pine`
- **Odkrycie z próby:** wyłączenie wymogu świeżego FTD (`iMktRequireFtd = false`) **nie zmieniło nic**
  (smoke identyczny jak IT1) → warunek FTD prawie nigdy nie wiązał; wiążącym filtrem jest
  `mktInCorrection` (≥6 distribution days w 25 sesjach jest spełniane często).
- Zmiany finalne IT2:
  1. nowy przełącznik `iMktUseMaRule` (domyślnie **true**): bramka = `benchClose > SMA(benchClose, 50)`
     — klasyczna, odporna reguła O'Neila zamiast zliczania dystrybucji,
  2. `iEpGapPct` 10 → **15** (w IT0 wąskie gappy były słabe),
  3. `iMktRequireFtd` → `false` (bez zmian zachowania, patrz wyżej).
- Smoke: 21/30 sygnałów ma wystąpienia (vs 13/30 w IT1) — bramka łagodniejsza, rzadsze sygnały wracają.
- Scrape: GPW_NC_IT2 (434/434), import + `db_verify` 0 niezgodności
- **Wynik — porównania:**
  - **IT2 vs IT0** (bramka MA vs brak bramki): 24 poprawione, 3 pogorszone → sama reguła MA też pomaga,
    ale słabiej i bez redukcji próbki.
  - **IT2 vs IT1** (MA vs distribution days + FTD): **6 poprawionych, 22 pogorszone** →
    **bramka distribution days + FTD (IT1) jest wyraźnie lepsza**.
- Wniosek: najlepszy filtr reżimu = IT1. Reguła MA zostaje jako opcja (`iMktUseMaRule`, domyślnie off).

## IT3 — powrót do bramki IT1 + tuning parametrów sygnałów
- Plik: `variants/ETSB-ia_it3.pine`
- Zmiany:
  1. bramka: `iMktUseMaRule = false`, `iMktRequireFtd = true` (konfiguracja IT1 = najlepszy reżim),
  2. `iBrkVolReqClose` 1.25 → **1.5** (wymóg wolumenu na zamknięciu dla wszystkich sygnałów
     breakoutowych — „stricter" ma podnieść jakość wybić),
  3. `iFlatMaxExtPct` 90 → **80** (flatb: bazy mniej rozciągnięte nad średnią),
  4. zachowane z IT2: `iEpGapPct = 15`.
- Scrape: GPW_NC_IT3 (434/434), import + `db_verify` (3 kosmetyczne `0.0` vs `None` dla sygnałów z 0 wystąpień)
- **Wynik (IT3 vs IT1): 7 poprawionych, 2 pogorszone** — ostrzejszy wymóg wolumenu (1.5) podniósł jakość
  wybić przy ~10% mniejszej liczbie zdarzeń:
  `ai-et3` 0.78 → **0.90** (+0.12), `ai-etc3` +0.11, `ai-mtc3` +0.11, `ai-obvdiv` +0.09, `ai-mtsb` +0.06
- Wniosek: IT3 zostaje jako baza.

## IT4 — tuning największych rodzin sygnałów (pod bramką IT1)
- Plik: `variants/ETSB-ia_it4.pine`
- Zmiany:
  1. `iRmvVolMult` 1.15 → **1.3** (rmv / etc / mtc: silniejsze potwierdzenie wolumenem),
  2. `iMtMaxBelowHighPct` 20 → **15** (szablon Minerviniego: lider bliżej 52-tygodniowego maksimum),
  3. `iMtRiseMinDays` 25 → **28** (długa średnia musi rosnąć konsekwentniej).
- Uzasadnienie: to rodziny o największych próbkach pod bramką (rmv1 816, rmv2 551, mtsb 486, rmv3 347,
  mtc1/2/3 ~200-260) — tam zmiany są najlepiej mierzalne.
- Scrape: GPW_NC_IT4 (434/434), import
- **Wynik (IT4 vs IT3): 3 poprawione, 2 pogorszone** — praktycznie neutralne:
  `ai-vcp2c` +0.23, `ai-vcp2` +0.12, `ai-rmv3` +0.02 vs `ai-rmv1` −0.02, `ai-rmv2` −0.03
  (ostrzejszy wolumen rmv: 816→733 i 551→509 zdarzeń).
  Zmiany szablonu mt były neutralne (świeżość szablonu kompensuje ostrzejsze warunki).
- Weryfikacja: studium na wykresie potwierdzone (inputy 1.3 / 28 / 15).

## IT5 — konfiguracja finałowa + walidacja na obu rynkach
- Plik: `variants/ETSB-ia_it5.pine`
- Zmiany: `iRmvVolMult` 1.3 → **1.15** (powrót do wartości z IT3, która była lepsza dla rmv1/rmv2);
  reszta ustawień z IT3/IT4 zostaje (bramka distribution+FTD, `iBrkVolReqClose` 1.5,
  `iFlatMaxExtPct` 80, `iMtMaxBelowHighPct` 15, `iMtRiseMinDays` 28, `iEpGapPct` 15).
- Scrape: **GPW_NC_IT5 + US_BIG_IT5** (walidacja końcowa na obu rynkach: 434/434 i 843/843)
- Import: runy 33-34, +38 310 pomiarów; `db_verify`: 0 niezgodności (3 kosmetyczne `0.0` vs `None`)
- **Wynik — DREAM TEAM (score > 0, occ ≥ 30 na obu rynkach): 21 z 30 sygnałów**
  | sygnał | score | win% GPW/US | occ GPW/US |
  |---|---|---|---|
  | ai-vip | 2.65 | 46.7 / 26.7 | 30 / 972 |
  | ai-flatb | 0.73 | **53.0** / 34.6 | 66 / 887 |
  | ai-et3 | 0.56 | 44.4 / 35.2 | 162 / 1643 |
  | ai-vcp2c | 0.51 | 26.8 / 32.8 | 41 / 476 |
  | ai-vcp2 | 0.46 | 35.3 / 34.5 | 34 / 267 |
  | ai-vwaptag | 0.40 | 25.6 / 25.7 | 203 / 2000 |
  | ai-et1yh | 0.40 | 45.3 / 28.7 | 86 / 1059 |
  | ai-mtc3 | 0.36 | 35.1 / 36.4 | 211 / 3473 |
  | ai-etc3 | 0.32 | 36.1 / 37.0 | 166 / 3027 |
  | ai-etc2 | 0.30 | 43.2 / 35.4 | 183 / 3419 |
  | (dalej: mtsb 0.28, mtc2 0.27, et4 0.25, etc1 0.25, caplow 0.24, mtc1 0.21, rmv2 0.15, wonturn 0.14, htf 0.12, ragpb 0.11, rmv1 0.10) | | | |
- **Poza dream teamem:** `ai-wonhp` (0 na GPW), `ai-ep`/`ai-ep20` (0 na GPW pod bramką; na US: 35/10 zdarzeń),
  `ai-htftight` (−0.06), `ai-vcp3` (−0.15), `ai-htf100` (score 3.23 ale tylko 1 zdarzenie na GPW = szum).
- **Kluczowa obserwacja:** bramka rynkowa podnosi win% **dużo mocniej na GPW** (flatb 53% vs 34.6% na US,
  caplow 50% vs 19.7%, et3 44.4% vs 35.2%) — bo benchmarkiem GPW jest WIG i filtr dystrybucji działa tam lepiej.

## Stan końcowy
- Plik produkcyjny: `src/indicators/ETSB-ia.pine` (= `variants/ETSB-ia_it5.pine`), 1177 linii, 30 sygnałów,
  kompilacja 0 błędów / 0 ostrzeżeń; w TradingView jako `ETSB-ia` (hash = plik repo)
- Baza: **34 runy, 439 932 pomiary, 9 rewizji skryptu ETSB-ia** (każda iteracja po SHA-256)
- Archiwum: `variants/ETSB-ia_{baseline,it1..it5}.pine` + summary każdej iteracji (`variants/*_SUMMARY.csv`)
- Surowe CSV czyszczone po każdym imporcie (dane są w bazie); w `analysis/` zostają tylko najnowsze summary

## Podsumowanie ścieżki optymalizacji
| iteracja | główna zmiana | efekt |
|---|---|---|
| IT0 | baseline (EP + market timing, bramka OFF) | 30 sygnałów, `ai-ep20` score +0.47 |
| IT1 | **bramka distribution days + FTD ON** | **23/30 poprawionych** — największy skok jakości |
| IT2 | reguła MA zamiast dystrybucji | gorsza (22 sygnały niżej) → odrzucona |
| IT3 | wolumen wybicia 1.25→1.5, flatb ext 90→80 | 7 poprawionych, 2 pogorszone |
| IT4 | rmv vol 1.15→1.3, mt below-high 20→15, mt rise 25→28 | neutralne (3/2) |
| IT5 | rmv vol → 1.15 + walidacja obu rynków | finał + dream team |
