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

**Kryterium poprawy (od IT13):** pooled `avgR` z obu rynków (ważone `n`) rośnie o **≥ 0,05**, pooled `PF`
nie spada bardziej niż **0,02**, a łączne `n ≥ 150`. Nowe sygnały nie liczą się jako poprawa — liczy się
wyłącznie poprawa istniejącego sygnału. Iteracja bez takiej poprawy zwiększa licznik „4 z rzędu".

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

## Zasady pracy (ustalone po IT10)
1. **Obszar zamrożony:** parametry wyjścia / SL / testu skuteczności (`iSigCheckTime`, `iSigStopLossDay`,
   `iSigStopLossMaxPct`, `iSigCheckTime`, progi `iMinSigSuccessRate`) **nie są obszarem optymalizacji**.
   Wyjątek: ewidentne błędy algorytmiczne w tych obszarach — do naprawy.
2. `iSigCheckTime` 30 → 45 zostało sprawdzone **raz, diagnostycznie** (IT11); po pomiarze wracamy do **30**
   niezależnie od wyniku.
3. Optymalizacja skupia się **wyłącznie na wejściach i jakości sygnałów**: parametry i algorytmy,
   w tym funkcje z `DRELib.pine` (np. `strongBreakout`).
4. **Biblioteki (`src/libraries/*`) nie są zmieniane.** Własne implementacje funkcji wejściowych
   (prostsze lub bardziej złożone) dodajemy **lokalnie w `ETSB-ia.pine`**, w iteracji, w której sygnały
   ich używają. Do biblioteki trafią tylko te, które okażą się wartościowe.
5. Nowe warianty wejść mierzymy jako **dodatkowe sygnały bez `plotshape`** (0 plotów) — A/B w jednym
   przebiegu: stara wersja vs nowa, na tych samych danych.

## IT6 — diagnostyka bramki + benchmark US z wolumenem + warianty EP bez bramki
- Plik: `variants/ETSB-ia_it6.pine` (1186 linii, 32 sygnały)
- **Diagnostyka benchmarków** (320 barów D, ostatnie 250; replika logiki bramki w Pythonie):
  | benchmark | wolumen | in correction | FTD fresh | **gate OPEN** | śr. dystr./25 |
  |---|---|---|---|---|---|
  | GPW:WIG | **BRAK (0/30)** | 93,6% | 85,6% | **6,4%** | 9,22 |
  | AMEX:SPY | TAK | 65,2% | 53,6% | 20,0% | 6,18 |
  | NASDAQ:QQQ | TAK | 74,0% | 53,6% | 21,2% | 6,27 |
  | NASDAQ:NDX | TAK | 47,2% | 63,2% | 32,0% | 5,42 |
  | SP:SPX | TAK | 44,4% | 53,6% | 35,2% | 5,44 |
  **Wniosek:** to **WIG nie ma wolumenu** (nie US). Fallback „tylko zamknięcie" z progiem 0,2%
  zamienia ~37% dni w distribution days → GPW praktycznie zawsze „in correction" (93,6%) →
  bramka otwarta 6,4% → stąd 5–16× mniej sygnałów na GPW i dużo lepsze statystyki
  (filtruje do rzadkich okien). US ma wolumen w indeksach, więc działa reguła właściwa.
- **Zmiany:**
  1. `autoBench`: `NASDAQ → NASDAQ:QQQ`, `NYSE/AMEX/pozostałe → AMEX:SPY` (ETF-y z wolumenem;
     lista US = 394 NASDAQ + 380 NYSE + 69 AMEX) — bramka US staje się ~1,6× bardziej selektywna,
  2. nowy input `iMktDistDropPctNoVol = 0.4` + `benchVolumeMissing` (wolumen `na` **lub** `<= 0`):
     dla benchmarku bez wolumenu próg spadku 0,2% → **0,4%** (kalibracja „równa selektywność"):
     WIG 20,8% vs SPY 20,0% / QQQ 21,2%,
  3. **`ai-epu` / `ai-ep20u`** — bliźniaki EP bez bramki (`dreperf` bez `f_gate`), bez `plotshape`
     (0 plotów → limit nadal 61/64), wiersze tabeli 33/34; pozwalają zmierzyć surową krawędź EP,
     której bramka nie dusi.
- Smoke (3 spółki): **32 sygnały** w tabeli; `ai-epu` N=1 przy `ai-ep` N=0; `mtsb` N=20 (było 3),
  `et3` N=8 (było 1) — bramka GPW ~6× bardziej otwarta, zgodnie z kalibracją.
- Scrape: GPW_NC_IT6 (434/434) + US_BIG_IT6 (843/843); import + `db_verify` 0 niezgodności (32 sygnały)
- **Wynik GPW (bramka 6,4% → ~21% otwarta):**
  - wg `score`/win%: **22 sygnały gorsze**, 5 lepszych (et3 0,90→−0,09; flatb 1,04→0,40; caplow 0,73→−0,17)
  - **ale wg sumy R: 15 177R vs 4088R (3,7× więcej!)** — luźniejsza bramka daje dużo więcej okazji
    o niższej jakości per-trade (et3: 1020 zdarzeń × avgR 0,34 = 344R vs 162 × 1,11 = 179R)
  - R/DD per sygnał: lepsze przy luźnej bramce dla `rmv1/2/3`, `flatb`, `vcp2`, `etc3`, `mtc3`,
    `et1yh`, `htf`, `obvdiv`; lepsze przy ścisłej dla `mtsb`, `mtc1/2`, `etc1/2`, `et3`, `et4`,
    `vwaptag`, `wonturn`, `vcp2c`, `vip`, `caplow`
  - **Wniosek: bramka to trade-off „jakość per-trade vs liczba okazji"** — ścisła (0,2%) daje
    ~2-4 sygnały/tydzień na GPW, luźna (0,4%) ~3,7× więcej R. Domyślnie zostaje luźna (praktyczna),
    a `iMktDistDropPctNoVol = 0.2` przywraca tryb „high-conviction".
- **Wynik US (QQQ/SPY zamiast NDX/SPX):** 13 poprawionych / 13 pogorszonych (neutralnie),
  ale EP wyraźnie lepiej: `ai-ep` 0,06→**0,70** (win 37,1→64,3%), `ai-ep20` 0,33→0,61, `caplow` −0,25→0,08.
- **EP gated vs ungated (kluczowe):** bramka EP **bardzo pomaga**:
  GPW `ai-ep20` 1,20 (gated, n=7) vs 0,18 (ungated, n=78); `ai-ep` 0,54 vs 0,07;
  US `ai-ep` 0,70 vs 0,24; `ai-ep20` 0,61 vs 0,08. → EP zostaje **gated**; warianty `-u` są pomiarowe.
- **Ważna uwaga metodologiczna:** `score_mean` to średnia per-spółka t-statów
  (`avgR/stdR·√n`) — przy 1–2 transakcjach na spółkę to szum (stąd „gwiazdy" `vip`/`htf100`).
  Wiarygodne metryki to **pooled `win%`, `avgR`, `PF`** (summarizer liczy je ważone przez n)
  oraz **suma R** i **R/maxDD**. Od IT7 rankuję przede wszystkim po pooled avgR/PF i sumie R.

## IT7 — tuning jakości sygnałów (praca na dużych próbkach z IT6)
- Plik: `variants/ETSB-ia_it7.pine` (1188 linii)
- Zmiany (3 dźwignie, każda z czystą atrybucją):
  1. **`iBrkLookback` 7 → 14** — „wybicie" z 7-świecowego sufitu to w większości szum; wymuszam
     realną bazę (14/28/56-bar wysokie przez opcję multi). Dźwignia wspólna dla ~15 sygnałów
     breakoutowych (`et3/et4/et1yh`, `etc1-3`, `mtc1-3`, `mtsb`, `obvdiv`, `vip`, ...),
  2. **`ai-vwaptag`**: nowy wymóg `iVwapReqVolOn` (wolumen na dniu reclaimu > średnia) +
     `iVwapFlushAgo` 30 → **15** barów (flush musi być świeży) — sygnał o najgorszej jakości
     przy dużej próbce (1551 zdarzeń, avgR 0,26, win 20,2%),
  3. **`ai-caplow`**: `iCapLowReqClose = true` (potwierdzenie odzyskania 1/3 poprzedniej świecy) —
     pod luźną bramką sygnał był na zero (avgR −0,01, 86 zdarzeń).
- Scrape: GPW_NC_IT7 (434/434) + US_BIG_IT7 (843/843); `db_verify` 0 niezgodności
- **Wynik GPW — wyraźny sukces (rodzina breakoutowa):**
  | sygnał | avgR IT6→IT7 | PF | suma R | R/DD |
  |---|---|---|---|---|
  | ai-et1yh | 0,32 → **0,77** | 1,51 → 2,18 | 198 → 480 | 112 → 270 |
  | ai-etc2 | 0,48 → 0,70 | 1,74 → 2,12 | 627 → 871 | 240 → 360 |
  | ai-etc1 | 0,43 → 0,65 | 1,66 → 2,02 | 672 → 918 | 217 → 339 |
  | ai-mtc2 | 0,42 → 0,62 | 1,66 → 1,98 | 677 → 892 | 235 → 347 |
  | ai-mtc1 | 0,41 → 0,60 | 1,64 → 1,94 | 762 → 961 | 234 → 341 |
  | ai-et3 | 0,34 → 0,55 | 1,54 → 1,88 | 344 → 517 | 157 → 261 |
  | ai-mtsb | 0,37 → 0,48 | 1,59 → 1,77 | 1208 → 1458 | 270 → 351 |
  | ai-et4 | 0,43 → 0,49 | 1,67 → 1,78 | 754 → 858 | 228 → 263 |
  | ai-vwaptag | 0,26 → 0,32 (n 1551→768) | 1,33 → 1,45 | 397 → 247 | 70 → 92 |
  **Suma R GPW: 15 177 → 16 736 (+10%)**. US: breakouty też w górę (et3 0,69→0,85, PF 2,10→2,38;
  mtc3 0,50→0,56; etc3 0,43→0,47), vwaptag 0,62→0,84 (n 1580→693), suma R 31 737→31 207 (−1,7%).
- **Regresje:** `ai-caplow` −0,01 → −0,06 (ReqClose zaszkodził na GPW; na US pomógł 0,24→0,28),
  `ai-vcp3` 0,55 → 0,24 (dłuższy lookback opóźnia wejście w VCP — pivot rządzi się inną logiką).
- Wniosek: `iBrkLookback` to była ukryta słabość (7-świecowy „sufit" = szum). Zostaje 14 jako baza
  do dalszego testu; ReqClose w caplow wycofany.

## IT8 — kontynuacja trendu lookback + naprawa regresji
- Plik: `variants/ETSB-ia_it8.pine`
- Zmiany:
  1. `iBrkLookback` 14 → **20** (baza 20/40/80 — sprawdzam, czy trend dalej działa),
  2. `iCapLowReqClose` **true → false** (revert po regresji na GPW),
  3. `iTurnAdrMult` 0,35 → **0,5** (`ai-wonturn`: dzień „go" musi być mocniejszy; avgR 0,11 przy 412 zd.),
- Smoke: 32 sygnały; `mtsb` 19 → 11 (lookback 20 ciął ~40%).
- Scrape: GPW_NC_IT8 (434/434) + US_BIG_IT8 (843/843); `db_verify` 0 niezgodności
- **Wynik: IT8 gorsze od IT7 → wycofane.**
  - `iBrkLookback` 20 vs 14: GPW suma R **16 736 → 15 634 (−6,6%)**; avgR w dół w całej rodzinie
    (et4 0,49→0,42, etc3 0,53→0,47, etc1 0,65→0,58, mtc3 0,50→0,44, mtc1 0,60→0,55, etc2 0,70→0,65),
    5 sygnałów z R/DD >10% w dół. US neutralnie (−1,7%). **Optimum lookbacku jest bliżej 14 niż 20.**
  - `iTurnAdrMult` 0,5 vs 0,35: `wonturn` avgR 0,11 → 0,08 (gorzej) → wycofane.
  - `caplow` po wycofaniu ReqClose nadal słaby (−0,08; IT6: −0,01) — sygnał jest wrażliwy na reżim
    (pod ścisłą bramką IT5 miał avgR 0,74), do decyzji później.
- **Ważne zastrzeżenie pomiarowe:** liczba zdarzeń waha się między runami o kilka % (np. `caplow`
  86 → 89 → 91) — to efekt głębokości historii ładowanej przez wykres i wyrównania barów.
  **Delty < ~5% traktuję jako szum**, nie jako efekt zmiany.

## IT9 — powrót do optimum + filtr siły zamknięcia w potwierdzeniu rmv
- Plik: `variants/ETSB-ia_it9.pine` (1190 linii)
- Zmiany:
  1. `iBrkLookback` 20 → **14** (powrót do optimum z IT7),
  2. `iTurnAdrMult` 0,5 → **0,35** (revert),
  3. **`iRmvMinClosePos = 0.5`** — nowy warunek w `rmvConfirm`: zamknięcie w górnej połowie
     zakresu świecy. Dźwignia na `rmv1/2/3` + `etc1/2/3` (~16 tys. transakcji na GPW, największy
     blok systemu: rmv1 5716, rmv2 4399, rmv3 2479 zdarzeń przy avgR ~0,48–0,52).
- Uzasadnienie: „ekspansja zmienności" bez silnego zamknięcia to często fałszywy wybuch; filtr
  pozycji zamknięcia jest klasycznym potwierdzeniem popytu w dniu wybicia.
- Scrape: GPW_NC_IT9 (434/434) + US_BIG_IT9 (843/843); `db_verify` 0 niezgodności
- **Wynik: filtr nie działa → wycofany.** Uciął ~25% transakcji, ale avgR **nie wzrósł**
  (GPW: rmv1 0,49→0,48, rmv2 0,52→0,49, rmv3 0,48→0,41; PF praktycznie bez zmian).
  Usunięte transakcje miały taką samą jakość jak zostawione → hipoteza „silne zamknięcie
  odróżnia prawdziwy wybuch od fałszywego" **obalona** dla tej rodziny.
  (`etc1/2/3` bez zmian — używają `rmvTrig`, nie `rmvConfirm`.)

## IT10 — powrót do IT7 + wymóg uformowanej kontrakcji (rmv)
- Plik: `variants/ETSB-ia_it10.pine` (1194 linie)
- Zmiany:
  1. `iRmvMinClosePos` 0,5 → **0,0** (revert po IT9),
  2. nowy `iRmvMinLowBars = 2` — trigger rmv wymaga **≥2 z 3 ostatnich barów w kontrakcji**
     (zamiast pojedynczego barа). Uzasadnienie: jednodniowy „dołek zmienności" to nie baza;
     prawdziwa kontrakcja trwa kilka sesji. Dźwignia na `rmv1/2/3` + `mtc1/2/3`.
- Scrape: GPW_NC_IT10 (434/434) + US_BIG_IT10 (843/843); `db_verify` 0 niezgodności
- **Wynik: mieszany, netto negatywny → wycofane (iRmvMinLowBars 2 → 1).**
  - `rmv1/2/3` GPW: jakość w górę (avgR 0,49→0,55 / 0,52→0,56 / 0,48→0,51; PF +0,1),
    ale liczba zdarzeń **−21..−29%** (5716→4031, 4399→3304, 2479→2156) → suma R w dół;
    R/DD minimalnie w górę (371→385, 363→372, 282→290).
  - `etc1` 0,65→0,72 i `mtc1` 0,60→0,66, ale **`etc2` 0,70→0,50 i `mtc2` 0,62→0,45 (R/DD −30%)** —
    odcięcie gałęzi `rmvTrig2` przesunęło mieszankę na gałąź „wciąż w kontrakcji", która w tej
    kombinacji wypada gorzej.
  - US: wyraźnie gorzej (`rmv1` R/DD 752→655, `rmv2` 762→671, rodziny etc/mtc −10..−14%).
- Wniosek: zaostrzenie kontrakcji kupuje jakość za zbyt wysoką cenę wolumenu i psuje kombinacje etc2/mtc2.

## IT11 — diagnoza horyzontu: iSigCheckTime 30 → 45 (jednorazowo)
- Plik: `variants/ETSB-ia_it11.pine`
- Zmiany: `iRmvMinLowBars` 2 → **1** (revert po IT10) + `iSigCheckTime` 30 → **45** (tylko pomiar).
- **Zgodnie z ustaleniem: po pomiarze wracamy do 30 niezależnie od wyniku.** Obszar wyjścia/SL
  nie jest obszarem optymalizacji.
- Scrape: GPW_NC_IT11 (434/434) + US_BIG_IT11 (843/843); `db_verify` 0 niezgodności
- **Wynik (diagnostyczny, nie adoptowany):**
  | rynek | mediana ΔavgR | mediana Δwin% | suma R |
  |---|---|---|---|
  | GPW | **−0,12** | −4,7 pp | 16 736 → 11 615 (−31%) |
  | US | **+0,16** | −3,2 pp | 31 207 → **43 627 (+40%)** |
  - GPW: dłuższe trzymanie szkodzi (małe, „poszarpane" spółki szybciej wracają); wyjątki: `vwaptag`
    (0,32→0,38), `vcp2c`, `htf`, `vip` oraz rzadkie EP (n=7–10, szum).
  - US: niemal wszystko w górę (`etc3` 0,47→0,76, `rmv3` 0,32→0,59, `mtc3` 0,56→0,82, `flatb` 0,43→0,70,
    `et4` 0,37→0,56, `rmv1` 0,42→0,60) — duże spółki potrzebują dłuższego horyzontu.
  - **Obserwacja na przyszłość** (poza obecnym zakresem — obszar wyjścia zamrożony): horyzont
    prawdopodobnie powinien być rynkowo-specyficzny (GPW ~30, US ~45–60).
- **`iSigCheckTime` wróciło do 30** (zgodnie z ustaleniem, niezależnie od wyniku).

## IT12 — własna funkcja wejścia `f_qualityBreakout` (A/B, lokalnie w pliku sygnałów)
- Plik: `variants/ETSB-ia_it12.pine` (1239 linii, 36 sygnałów)
- Nowa funkcja lokalna (nie w bibliotece):
  ```
  f_qualityBreakout(len, maxRangePct, minClosePos, volMult, trendLen):
    highest/lowest z poprzednich N barów, zakres <= maxRangePct   (ciasna baza)
    close > baza high                                             (wybicie z bazy)
    (close-low)/(high-low) >= minClosePos                         (silne zamknięcie)
    volume > volMult * SMA(volume, iVolMaLen)                     (popyt)
    close > SMA(close, trendLen)                                  (trend)
  ```
  Parametry: base 20 barów, max range 12%, close-pos 0,5, relVol 1,5, trend MA 50.
- **4 warianty A/B bez `plotshape` (0 plotów):** `ai-mtsbq`, `ai-mtc3q`, `ai-et4q`, `ai-obvq` —
  te same warunki sygnału z `qBreakout` zamiast `strongBreakout`.
- Smoke (3 spółki): 36 sygnałów; warianty selektywniejsze: `mtsb` 19 → `mtsbq` 6, `mtc3` 9 → 5,
  `obvdiv` 4 → 1, `et4` 4 → 0.
- Scrape: GPW_NC_IT12 (434/434) + US_BIG_IT12 (843/843, 36 sygnałów); `db_verify` 0 niezgodności
- **Wynik A/B: `qBreakout` wyraźnie gorszy na obu rynkach.**
  | para | GPW avgR (base → q) | PF | US avgR | PF |
  |---|---|---|---|---|
  | ai-mtsb vs ai-mtsbq | 0,48 → **0,14** | 1,77 → 1,23 | 0,51 → 0,37 | 1,80 → 1,71 |
  | ai-mtc3 vs ai-mtc3q | 0,50 → **0,14** | 1,82 → 1,24 | 0,55 → 0,35 | 1,92 → 1,68 |
  | ai-et4 vs ai-et4q | 0,49 → **0,22** | 1,78 → 1,41 | 0,36 → 0,32 | 1,56 → 1,64 |
  | ai-obvdiv vs ai-obvq | 0,38 → 0,31 | 1,62 → 1,59 | 0,44 → 0,37 | 1,63 → 1,68 |
  - Warianty `q` mają **wyższy win%** (36–45% vs 32–33%), ale **2–4× niższy avgR** — ciasna baza
    + silne zamknięcie wybiera „bezpieczne, małe" wybicia i **odcina grube ogony**, które są źródłem edge'a.
  - Wniosek: obecny `strongBreakout` (świeże wybicie + wolumen + AVWAP) jest lepszy; **nie adoptowano**.
    Kolejne eksperymenty wejść kierować w *siłę wybicia* (wolumen, rozmiar świecy vs ADR), nie w ciasne wzory.

## Analiza profilu spółki (na pomiarach IT0–IT12) — bez nowych iteracji
- Narzędzia: `scripts/company_profile_analysis.py`, `scripts/profile_deep_dive.py`
- Raport: **`analysis/PROFILE_ANALYSIS_REPORT.md`** (+ `analysis/company_profile_analysis.md`,
  `analysis/profile_deep_dive.md`, CSV)
- Najważniejsze ustalenia:
  1. **ADR (zmienność) to najsilniejszy wymiar profilu**, silniejszy niż MCap i płynność:
     GPW `ADR≥5%` → avgR 0,49 → **1,65** (PF 1,78 → **3,44**), 13,5% zdarzeń;
     US `ADR≥5% & MCap≥200M` → 0,44 → **0,89** (PF 1,69 → **2,23**), 22% zdarzeń.
  2. MCap to proxy ADR — w każdym koszyku MCap na GPW ADR≥5% daje 2–8× lepszy avgR;
     na US wysokie ADR **szkodzi** spółkom <200M (pułapka: −0,17).
  3. Płynność ma odwrotną rolę: GPW sweet spot 2–10M obrotu, ≥50M najgorsze (0,09);
     US — edge jest w ≥50M (0,48), 0,5–2M ujemne.
  4. Wysokie ADR nie podnosi win% (26% vs 31%), tylko wielkość wygranych — to filtr „grubych ogonów".
  5. 24/28 sygnałów na GPW woli wysoką zmienność; „quiet" wyjątki: `htf`, `htftight`, `ragpb`, `vcp2c`,
     `vcp3c`; na US `htf`/`htftight` przełączają się na wysoką → **preferencja jest rynkowo-specyficzna**.
  6. Rekomendacje: bramka profilu **per sygnał i per rynek**, tryb **rankingowy** (ADR jako mnożnik siły)
     obok filtra, płynność rynkowo-specyficzna, sektor jako tilt; szczegóły w raporcie (R1–R6).

## IT13 — wybicie normalizowane ADR (`f_breakoutV2`, warianty ai-mtsbv2a…e)
- Plik: `variants/ETSB-ia_it13.pine` (1287 linii, **41 sygnałów**: 36 + 5 wariantów)
- Nowa funkcja lokalna (tylko do pomiaru, bez `plotshape`):
  ```
  f_breakoutV2(lookback, volMult, vwapLen, minClrAdr, maxExtAdr, useExt):
    close > highest(high, lookback)[1]                       (przebicie sufitu bazy)
    (close - sufit) >= minClrAdr * ADR * close               (minimalny zapas ponad sufit w ADR)
    volume > volMult * SMA(volume, iVolMaLen)                (potwierdzenie wolumenem)
    close > anchored VWAP(vwapLen)                           (potwierdzenie AVWAP)
    close <= SMA50 * (1 + maxExtAdr * ADR)                   (cap na rozciągnięcie, opcjonalny)
  ```
- Warianty A/B (wszystkie z `ai-mtsb` = `mtTrendFresh`):
  | wariant | min. clearance | cap rozciągnięcia | AVWAP |
  |---|---|---|---|
  | ai-mtsbv2a | 0,25 ADR | 6 ADR | 100 |
  | ai-mtsbv2b | 0,50 ADR | 6 ADR | 100 |
  | ai-mtsbv2c | 1,00 ADR | 6 ADR | 100 |
  | ai-mtsbv2d | 0,50 ADR | **3 ADR** | 100 |
  | ai-mtsbv2e | 0,50 ADR | 6 ADR | **50** |
- Uzasadnienie: profil spółki pokazał, że edge rodziny `mtsb` jest w **ekspansji** (wysokie ADR,
  grube ogony), a `strongBreakout` dopuszcza przebicie sufitu o jeden tick.
- `pine check`: 0 błędów, 0 ostrzeżeń; źródło zsynchronizowane z TradingView (hash zgodny).
- Scrape: GPW_NC_IT13 (434/434) + US_BIG_IT13 (843/843), import + `db_verify` 0 niezgodności.
- **Wynik (pooled, oba rynki): żaden wariant nie poprawia `avgR`; IT13 = iteracja bez poprawy (1/4).**
  | sygnał | GPW avgR / PF / n | US avgR / PF / n | pooled avgR / PF | score GPW/US |
  |---|---|---|---|---|
  | ai-mtsb (baza) | 0,481 / 1,77 / 3031 | 0,515 / 1,80 / 6143 | **0,504 / 1,79** | −0,17 / −0,04 |
  | ai-mtsbv2a | 0,465 / 1,79 / 2702 | 0,456 / 1,73 / 4950 | 0,459 / 1,75 | −0,13 / +0,08 |
  | ai-mtsbv2b | 0,449 / 1,77 / 2094 | 0,460 / 1,75 / 3646 | 0,456 / 1,76 | +0,04 / +0,09 |
  | ai-mtsbv2c | 0,392 / 1,68 / 1096 | 0,471 / 1,80 / 1771 | 0,441 / 1,76 | +0,14 / +0,06 |
  | ai-mtsbv2d | 0,281 / 1,48 / 735 | **0,654 / 2,05 / 880** | 0,484 / 1,80 | −0,06 / +0,39 |
  | ai-mtsbv2e | 0,351 / 1,58 / 2613 | 0,368 / 1,58 / 4475 | 0,362 / 1,58 | −0,20 / −0,11 |
  - V2 podnosi win% (GPW +2–3 pp) i score, ale **ścina avgR** — ten sam mechanizm co IT12 `q`:
    normalizacja clearancu do ADR preferuje mniejsze, „bezpieczniejsze" wybicia.
  - `v2d` (cap 3 ADR) jest jedynym wyjątkiem na US (avgR 0,654, PF 2,05), ale na GPW spada do 0,281,
    a pooled avgR 0,484 < 0,504 przy 82% mniej zdarzeń → **nie adoptowano**.
- Wniosek: ADR-normalizacja samego wybicia nie jest właściwym kierunkiem. Następny krok (IT14) to
  **bramka profilu ADR** na istniejącej rodzinie `mtsb` (bez zmiany definicji wybicia i bez nowych sygnałów).

## IT14 — bramka profilu ADR na rodzinie `mtsb` (walidacja point-in-time)
- Plik: `variants/ETSB-ia_it14.pine` (1294 linie, 41 sygnałów — bez nowych sygnałów)
- Zmiana: `profileAdrOk = not iProfileGateOn or adrPct >= iProfileMinAdrPct` (domyślnie 5%),
  dołożone do `aiMtsb`, `aiMtsbQ` i `aiMtsbV2a…e`. ADR liczony na barze sygnału (bez lookahead).
- `pine check`: 0 błędów, 0 ostrzeżeń; SHA repo = SHA TV (`f5f820b9…19970c8`).
- Scrape: GPW_NC_IT14 (434/434) + US_BIG_IT14 (843/843), import + `db_verify` 0 niezgodności.
- **Wynik: bramka ADR działa — 6 sygnałów poprawionych, licznik „4 z rzędu" = 0/4.**
  | sygnał | GPW avgR / PF / n | US avgR / PF / n | pooled avgR / PF / n | win% pooled |
  |---|---|---|---|---|
  | ai-mtsb | **1,289 / 2,78 / 463** | **0,807 / 2,07 / 2571** | **0,881 / 2,17 / 3034** | 24,1 |
  | ai-mtsbv2a | 1,676 / 3,36 / 413 | 0,758 / 2,04 / 1988 | 0,916 / 2,26 / 2401 | 26,6 |
  | ai-mtsbv2b | 1,521 / 3,10 / 316 | 0,774 / 2,06 / 1417 | 0,910 / 2,25 / 1733 | 26,0 |
  | ai-mtsbv2c | 1,702 / 3,34 / 146 | 1,080 / 2,48 / 612 | **1,199 / 2,65 / 758** | 26,4 |
  | ai-mtsbv2d | 0,311 / 1,42 / 105 | 0,922 / 2,32 / 385 | 0,792 / 2,11 / 490 | 27,9 |
  | ai-mtsbv2e | 1,166 / 2,55 / 390 | 0,592 / 1,78 / 1934 | 0,688 / 1,91 / 2324 | 23,8 |
  - Baza `mtsb`: avgR **0,504 → 0,881**, PF **1,79 → 2,17** przy n **9174 → 3034** (−67%).
    Win% spada 33,0 → 24,1, ale to zgodne z tezą profilu: ADR nie podnosi trafności, tylko grube ogony.
  - Pod bramką warianty V2 wreszcie mają sens: `v2c` (clearance 1,0 ADR) daje pooled avgR **1,199**,
    PF **2,65**, score **+0,56** przy n 758; `v2a` (0,25 ADR) daje 0,916 / 2,26 przy n 2401.
  - `ai-mtsbq` (tight-base q) pod bramką nadal słaby: pooled avgR 0,17, PF 1,23, n 66 → pozostaje
    w tabeli jako eksperyment, bez wpływu na decyzję.
- Wniosek: **bramka ADR jest pierwszym od IT1 dużym krokiem jakościowym.** IT15 rozszerza ją na pozostałe
  rodziny ekspansyjne (rmv, mtc, et/etc, obvdiv, vwaptag, flatb, caplow, wonhp, wonturn), bez nowych sygnałów.

## IT15 — bramka ADR na pozostałych rodzinach ekspansyjnych
- Plik: `variants/ETSB-ia_it15.pine` (1297 linii, 41 sygnałów — bez nowych sygnałów)
- Zmiana: `profileAdrOk` dołożone do `aiEt3sb`, `aiEt4sb`, `aiEt1yh`, `aiRmv1…3`, `aiObvDiv`, `aiMtc1…3`,
  `aiVwapTag`, `aiCapLow`, `aiFlatB`, `aiWonHp`, `aiWonTurn` oraz wariantów q. `aiEtc1…3` dziedziczą bramkę
  przez `aiEt3sb`/`aiEt4sb`. Rodziny „quiet" (htf, vcp, ragpb, vip, ep) celowo bez bramki.
- `pine check`: 0 błędów, 0 ostrzeżeń; SHA repo = SHA TV (`d02e6014…583e94`).
- Scrape: GPW_NC_IT15 (434/434) + US_BIG_IT15 (843/843), import + `db_verify` 0 niezgodności
  (przy okazji naprawiony `score_sum` w widoku: `COALESCE(...,0.0)` dla sygnałów z n=0).
- **Wynik: 17 sygnałów poprawionych — licznik „4 z rzędu" = 0/4.** Pooled (GPW+US):
  | sygnał | avgR IT14→IT15 | PF IT14→IT15 | n IT14→IT15 |
  |---|---|---|---|
  | ai-et3 | 0,72 → **1,51** | 2,16 → **3,04** | 2119 → 528 |
  | ai-et4 | 0,40 → **0,70** | 1,62 → **1,92** | 6456 → 2300 |
  | ai-etc1 | 0,53 → **1,02** | 1,83 → **2,38** | 3873 → 1070 |
  | ai-etc2 | 0,54 → **0,95** | 1,87 → **2,29** | 3482 → 946 |
  | ai-etc3 | 0,49 → **1,01** | 1,82 → **2,42** | 3347 → 930 |
  | ai-rmv1 | 0,44 → **0,74** | 1,67 → **1,99** | 20168 → 6707 |
  | ai-rmv2 | 0,47 → **0,77** | 1,73 → **2,03** | 15830 → 5191 |
  | ai-rmv3 | 0,37 → **0,54** | 1,58 → **1,70** | 9183 → 3123 |
  | ai-mtc1 | 0,54 → **1,15** | 1,86 → **2,58** | 4220 → 1168 |
  | ai-mtc2 | 0,58 → **1,05** | 1,93 → **2,45** | 3850 → 1050 |
  | ai-mtc3 | 0,54 → **1,02** | 1,89 → **2,44** | 3848 → 1094 |
  | ai-vwaptag | 0,57 → **1,13** | 1,80 → **2,49** | 1461 → 483 |
  | ai-obvdiv | 0,42 → **0,71** | 1,63 → **1,89** | 1430 → 532 |
  | ai-flatb | 0,62 → **1,22** | 2,11 → **2,70** | 1020 → 227 |
  | ai-caplow | 0,18 → **0,61** | 1,24 → **1,76** | 471 → 184 |
  | ai-wonhp | 0,47 → **0,91** | 1,78 → **2,22** | 1677 → 546 |
  | ai-wonturn | 0,36 → **0,64** | 1,51 → **1,83** | 1925 → 871 |
  - Win% spada o 5–13 pp, n o 30–80% — znowu „mniej, ale lepiej"; pooled avgR i PF rosną wszędzie.
  - **Bez poprawy:** `ai-et1yh` (avgR −0,01, PF −0,23), `ai-mtsbq` (−0,03), `ai-mtc3q` (−0,02),
    `ai-et4q` (−0,90), `ai-obvq` (−0,88) — bramka im nie pomaga, więc w IT16 zostanie z nich zdjęta.
- Wniosek: bramka ADR działa szeroko, ale nie uniwersalnie. IT16: **(a)** podniesienie progu 5% → 6%
  (profil US: optimum 5–8%, GPW monotonicznie w górę), **(b)** zdjęcie bramki z et1yh i wariantów q.

## IT16 — próg ADR 6% + zdjęcie bramki z sygnałów, którym nie służyła
- Plik: `variants/ETSB-ia_it16.pine` (1297 linii, 41 sygnałów — bez nowych sygnałów)
- Zmiany:
  1. `iProfileMinAdrPct` 5,0 → **6,0**,
  2. zdjęta bramka z `aiEt1yh`, `aiMtsbQ`, `aiMtc3Q`, `aiEt4Q`, `aiObvQ` (w IT15 nie poprawiały się).
- `pine check`: 0 błędów, 0 ostrzeżeń; SHA repo = SHA TV (`ad2e09d7…4322e7`).
- Scrape: GPW_NC_IT16 (434/434) + US_BIG_IT16 (843/843), import + `db_verify` 0 niezgodności.
- **Wynik: 25 sygnałów poprawionych — licznik „4 z rzędu" = 0/4.** Pooled (GPW+US):
  | sygnał | avgR IT15→IT16 | PF IT15→IT16 | n IT15→IT16 |
  |---|---|---|---|
  | ai-mtsb | 0,88 → **1,04** | 2,17 → **2,34** | 3034 → 2209 |
  | ai-mtsbv2a | 0,92 → **1,06** | 2,26 → **2,41** | 2401 → 1723 |
  | ai-mtsbv2c | 1,20 → **1,34** | 2,65 → **2,78** | 758 → 507 |
  | ai-rmv1 | 0,74 → **0,87** | 1,99 → **2,14** | 6707 → 4768 |
  | ai-rmv2 | 0,77 → **0,90** | 2,03 → **2,18** | 5191 → 3744 |
  | ai-rmv3 | 0,54 → **0,62** | 1,70 → **1,77** | 3123 → 2281 |
  | ai-mtc1 | 1,15 → **1,33** | 2,58 → **2,77** | 1168 → 804 |
  | ai-mtc2 | 1,05 → **1,25** | 2,45 → **2,65** | 1050 → 702 |
  | ai-mtc3 | 1,02 → **1,20** | 2,44 → **2,63** | 1094 → 766 |
  | ai-etc1 | 1,02 → **1,20** | 2,38 → **2,59** | 1070 → 746 |
  | ai-etc2 | 0,95 → **1,19** | 2,29 → **2,55** | 946 → 639 |
  | ai-etc3 | 1,01 → **1,19** | 2,42 → **2,60** | 930 → 654 |
  | ai-et3 | 1,51 → **2,05** | 3,04 → **3,66** | 528 → 383 |
  | ai-et4 | 0,70 → **0,78** | 1,92 → **1,99** | 2300 → 1690 |
  | ai-vwaptag | 1,13 → **1,54** | 2,49 → **3,01** | 483 → 336 |
  | ai-obvdiv | 0,71 → **0,85** | 1,89 → **2,04** | 532 → 414 |
  | ai-flatb | 1,22 → **1,34** | 2,70 → **2,76** | 227 → 155 |
  | ai-caplow | 0,61 → **0,83** | 1,76 → **2,04** | 184 → 132 |
  | ai-wonhp | 0,91 → **1,18** | 2,22 → **2,55** | 546 → 368 |
  | ai-wonturn | 0,64 → **0,72** | 1,83 → **1,90** | 871 → 635 |
  - Zdjęcie bramki przywróciło pełne próbki i wyniki `et1yh` (avgR 0,81, PF 2,24, n 1540) oraz
    wariantów q (`et4q` 0,28; `mtsbq` 0,25; `obvq` 0,34; `mtc3q` 0,24).
  - Sygnały bez bramki (`ep*`, `htf*`, `vcp*`, `ragpb`, `vip`) są w granicach szumu ±0,02–0,10.
- Wniosek: **6% jest lepsze od 5%** na większości rodzin (avgR +0,08…+0,53 przy n −15…−40%).
  IT17 testuje dwie niezależne hipotezy: bramkę „quiet" dla htf/htftight/ragpb oraz **ADR 30-dniowy**
  (zamiast 100-dniowego) na rodzinie rmv.

## IT17 — bramka „quiet" + ADR 30-dniowy na rmv (A/B)
- Plik: `variants/ETSB-ia_it17.pine` (1307 linii, 41 sygnałów — bez nowych sygnałów)
- Zmiany:
  1. `profileQuietOk`: GPW → `ADR < 6%`, US → `ADR ≥ 6%` dla `aiHtf`, `aiHtf100`, `aiHtfTight`;
  2. `profileLowAdrOk` (ADR < 6%) dla `aiRagPb`;
  3. `profileAdr30Ok` (SMA(high/low, 30)) zamiast 100-dniowego ADR na `aiRmv1…3`.
- `pine check`: 0 błędów, 0 ostrzeżeń; SHA repo = SHA TV (`06cf2f82…887f4f`).
- Scrape: GPW_NC_IT17 (434/434) + US_BIG_IT17 (843/843), import + `db_verify` 0 niezgodności.
- **Wynik: 1 sygnał poprawiony (marginalnie) — licznik „4 z rzędu" = 0/4.**
  | sygnał | avgR IT16→IT17 | PF IT16→IT17 | n IT16→IT17 | uwaga |
  |---|---|---|---|---|
  | ai-htf | 0,27 → **0,53** | 1,43 → **1,87** | 665 → 155 | **jedyna poprawa** (n 155) |
  | ai-htf100 | 0,57 → 1,30 | 1,86 → 3,47 | 41 → 17 | za mała próbka |
  | ai-htftight | 0,22 → 0,29 | 1,35 → 1,45 | 611 → 132 | poniżej progu n=150 |
  | ai-ragpb | 0,61 → **0,33** | 1,81 → **1,44** | 1516 → 1296 | **regresja** |
  | ai-rmv1 | 0,87 → 0,89 | 2,14 → 2,17 | 4768 → 4552 | +0,02 (bez progu) |
  | ai-rmv2 | 0,90 → 0,89 | 2,18 → 2,16 | 3744 → 3511 | −0,01 |
  | ai-rmv3 | 0,62 → 0,61 | 1,77 → 1,75 | 2281 → 1930 | GPW +0,72, US −0,26 |
  - ADR 30-dniowy jest **rynkowo-niestabilny**: na GPW rmv1/2/3 rosną (1,56→1,84; 1,67→1,73;
    2,51→3,23), ale na US rmv3 spada 0,62→0,36. Pooled bez poprawy → **wracamy do 100-dniowego ADR**.
  - Bramka quiet: `htf` działa, `htftight`/`htf100` zabijają próbkę, `ragpb` wyraźnie szkodzi.
- Wniosek: IT18 = **(a)** revert 30-dniowego ADR na rmv, **(b)** revert bramki na ragpb/htftight/htf100,
  **(c)** nowy test: filtr „dnia ekspansji" (range ≥ 0,8×ADR, close w górnych 40% świecy) na `aiMtsb`.

## IT18 — revert bramek + filtr dnia ekspansji na `aiMtsb`
- Plik: `variants/ETSB-ia_it18.pine` (1318 linii, 41 sygnałów — bez nowych sygnałów)
- Zmiany:
  1. `aiRmv1…3` wracają do 100-dniowego `profileAdrOk`,
  2. zdjęta bramka z `aiRagPb`, `aiHtfTight`, `aiHtf100` (zostaje tylko `aiHtf`),
  3. nowy lokalny filtr `expansionDayOk` na `aiMtsb`: `(high-low)/close ≥ 0,8×ADR` i
     `(close-low)/(high-low) ≥ 0,6`.
- `pine check`: 0 błędów, 0 ostrzeżeń; SHA repo = SHA TV (`529614f2…ad68939`).
- Scrape: GPW_NC_IT18 (434/434) + US_BIG_IT18 (843/843), import + `db_verify` 0 niezgodności.
- **Wynik: brak nowego historycznego maksimum — licznik „4 z rzędu" = 1/4.**
  | sygnał | avgR IT17→IT18 | PF IT17→IT18 | n IT17→IT18 | uwaga |
  |---|---|---|---|---|
  | ai-mtsb | 1,04 → **0,98** | 2,34 → 2,24 | 2209 → 1810 | filtr ekspansji **szkodzi** |
  | ai-ragpb | 0,33 → **0,61** | 1,44 → **1,81** | 1296 → 1516 | tylko powrót do poziomu IT16 |
  | ai-rmv1 | 0,89 → 0,87 | 2,17 → 2,14 | 4552 → 4768 | powrót do IT16 |
  | ai-htftight | 0,29 → 0,22 | 1,45 → 1,35 | 132 → 611 | powrót próbki, avgR niżej |
  - Filtr ekspansji obniżył avgR zarówno na GPW (1,89→1,57), jak i US (0,927→0,897) — **odrzucony**.
  - `ragpb` wrócił do 0,61 / PF 1,81 / n 1516, ale to **nie jest nowy szczyt** (IT16 = 0,61).
  - **Zmiana kryterium licznika (od IT18):** poprawa = nowy historyczny szczyt pooled `avgR`
    (≥ +0,05 vs najlepszy wcześniejszy wynik, PF nie gorszy niż −0,02, n ≥ 150). Powrót do
    wcześniejszego poziomu (revert) **nie resetuje** licznika.
- Wniosek: IT19 = **(a)** revert filtra ekspansji, **(b)** test ADR **percentyla** (top 30% z 252 dni)
  zamiast progu absolutnego na `aiMtsb`, **(c)** test bramki płynności (GPW ≥2M, US ≥50M) na `aiRmv1`.

## IT19 — percentyl ADR na `aiMtsb` + bramka płynności na `aiRmv1`
- Plik: `variants/ETSB-ia_it19.pine` (1330 linii, 41 sygnałów — bez nowych sygnałów)
- Zmiany:
  1. `aiMtsb`: `profileAdrPctileOk` = percentyl ADR (252 dni) ≥ 70 zamiast progu 6%,
  2. `aiRmv1`: dodatkowo `profileLiqOk` (GPW ≥2M, US ≥50M średniego obrotu),
  3. zdjęty filtr ekspansji z `aiMtsb`.
- `pine check`: 0 błędów (jeden warning o `ta.percentrank` w wyrażeniu warunkowym poprawiony przez przypisanie do zmiennej).
- Scrape: GPW_NC_IT19 (434/434) + US_BIG_IT19 (843/843), import + `db_verify` 0 niezgodności.
- **Wynik: brak poprawy zmienionych sygnałów — licznik „4 z rzędu" = 2/4.**
  | sygnał | avgR IT18→IT19 | PF | n | uwaga |
  |---|---|---|---|---|
  | ai-mtsb | 0,98 → **0,52** | 2,24 → **1,62** | 1810 → 2798 | percentyl za luźny |
  | ai-rmv1 | 0,87 → **0,76** | 2,14 → **2,01** | 4768 → 1206 | płynność za ostra |
  - Percentyl 70% wciąga zbyt wiele „średnich" spółek: GPW n 255→842, avgR 1,89→1,00;
    US n 1954→1956, avgR 0,93→0,32. **Odrzucony.**
  - Płynność: GPW n 567→31 (avgR 6,95, ale n << 150), US n 4201→1175, avgR 0,78→0,60. **Odrzucona.**
  - `ai-obvdiv` +0,05 to szum niezmienionego sygnału — **nie liczy się** jako poprawa.
    Licznik liczy wyłącznie sygnały, których definicję/parametry zmieniono w danej iteracji.
- Wniosek: IT20 = powrót do **progu absolutnego** i test **7%** (GPW monotonicznie w górę, US optimum 5–8%).

## IT20 — test progu 7% (przerwany: za mało sygnałów)
- Plik: `variants/ETSB-ia_it20.pine` (7% na wszystkich bramkowanych sygnałach)
- GPW_NC_IT20: 434/434; jakość bardzo wysoka, ale liczby za niskie:
  | sygnał | n GPW | avgR | PF |
  |---|---|---|---|
  | ai-mtsb | 145 | 3,07 | 5,23 |
  | ai-rmv1 | 329 | 2,30 | 4,03 |
  | ai-rmv3 | 146 | 4,22 | 6,45 |
  | ai-mtc1 | 66 | 3,21 | 5,41 |
  | ai-etc1 | 59 | 3,27 | 5,39 |
  | ai-et3 | 27 | 2,17 | 3,66 |
  | ai-flatb | 10 | 7,63 | 16,28 |
  | ai-wonhp | 0 | – | – |
- US_BIG_IT20 przerwany na 131/843 po decyzji użytkownika: 7% schodzi poniżej minimumów
  (120 GPW / 240 US). **Iteracja diagnostyczna, bez importu do bazy.**

## IT21 — powrót do 5% + audyt minimumów 120/240
- Plik: `variants/ETSB-ia_it21.pine` (1331 linii, 41 sygnałów)
- Scrape: GPW_NC_IT21 (434/434) + US_BIG_IT21 (843/843), import + `db_verify` 0 niezgodności.
- Skala: **GPW 12 647 zdarzeń / 415 spółek; US 39 950 / 794** (vs 6%: 10 124 / 32 329).
- Jakość (pooled, 5%): `mtsb` 0,88 / PF 2,17 / n 3034; `rmv1` 0,74 / 1,99 / 6707;
  `mtc1` 1,15 / 2,58 / 1168; `etc1` 1,02 / 2,38 / 1070.
- **Audyt minimumów (120 GPW / 240 US):**
  - poniżej progu **już bez bramki**: `caplow` (GPW 91), `wonhp` (GPW 25), `ep` (10/14),
    `ep20` (7/9), `ep20u` (54/40), `epu` (91/104), `htf100` (10/31), `vcp3` (68/47),
    `vcp3c` (82/100), `obvq` (US 230), `vcp2` (US 193);
  - powyżej progu bez bramki, ale **bramka 5% zbiła poniżej**: `et3` (GPW 98), `obvdiv` (GPW 94),
    `wonturn` (GPW 88), `mtsbv2d` (GPW 105), `flatb` (GPW 42 / US 185), `caplow` (US 169),
    `htf` (US 65).
- **Nowa zasada (od IT22):** dla żadnego sygnału nie schodzimy poniżej 120 (GPW) / 240 (US).
  Sygnały już poniżej progu bez bramki → bez bramki ADR + próba ratowania parametrami/algorytmem.
  Sygnały zbite przez bramkę → niższy próg per sygnał (4% / 3% / off).
- Licznik „4 z rzędu” **wstrzymany** do spełnienia minimumów.

## IT22 — per-sygnłowe progi: powrót do minimumów 120/240
- Plik: `variants/ETSB-ia_it22.pine` (1332 linie, 41 sygnałów)
- Zmiany:
  1. próg **4%** dla `aiEt3sb` (→ też `aiEtc1…3`), `aiObvDiv`, `aiWonTurn`, `aiMtsbV2d`,
  2. **bez bramki** dla `aiFlatB`, `aiCapLow`, `aiWonHp`, `aiHtf`,
  3. reszta bez zmian (5%).
- `pine check`: 0 błędów, 0 ostrzeżeń; SHA repo = SHA TV (`06c151d8…`).
- Scrape: GPW_NC_IT22 (434/434) + US_BIG_IT22 (843/843), import + `db_verify` 0 niezgodności.
- **Wynik: wszystkie sygnały „zbite przez bramkę” wróciły powyżej minimum.**
  | sygnał | GPW n / avgR / PF | US n / avgR / PF | status |
  |---|---|---|---|
  | ai-et3 (4%) | 194 / 0,33 / 1,44 | 566 / 1,32 / 2,80 | OK |
  | ai-obvdiv (4%) | 172 / 0,71 / 1,99 | 542 / 0,58 / 1,77 | OK |
  | ai-wonturn (4%) | 153 / 0,55 / 1,73 | 1027 / 0,56 / 1,74 | OK |
  | ai-mtsbv2d (4%) | 191 / 0,69 / 2,01 | 492 / 0,80 / 2,16 | OK |
  | ai-flatb (off) | 328 / 1,01 / 2,88 | 692 / 0,43 / 1,76 | OK |
  | ai-caplow (off) | 91 / −0,08 / 0,89 | 380 / 0,18 / 1,24 | GPW < 120 |
  | ai-wonhp (off) | 25 / 0,04 / 1,08 | 1652 / 0,47 / 1,78 | GPW < 120 |
  | ai-htf (off) | 142 / 0,39 / 1,63 | 523 / 0,24 / 1,38 | OK |
- Pozostałe poniżej minimum to wyłącznie sygnały, które były poniżej **już bez bramki**:
  `ep` (10/14), `ep20` (7/9), `ep20u` (54/25), `epu` (91/90), `htf100` (10/31),
  `obvq` (415/238), `vcp2` (216/196), `vcp3` (68/48), `vcp3c` (82/102), `caplow` (91/380),
  `wonhp` (25/1652).
- Wniosek: IT23 = pakiet ratunkowy parametrów dla rzadkich (VCP, EP, wonhp EPS-aware, caplow,
  obvdiv/obvq, htf100), bez ruszania bramek sygnałów, które już spełniają minimum.

## IT23 — pakiet ratunkowy rzadkich sygnałów
- Plik: `variants/ETSB-ia_it23.pine` (1334 linie, 41 sygnałów)
- Zmiany:
  1. `caplow`: min. volume percentile 95 → **90**,
  2. `wonhp`: `hpAvg` EPS-aware (gdy brak EPS, średnia z OBV/RS) + min. EPS updates 9 → **3**,
  3. VCP: min. contraction depth 3 → **2%**, depth ratio 0,85 → **0,90**, max. distance from high 25 → **30%**,
  4. `obvdiv`/`obvq`: min. divergence bars 30 → **28**,
  5. EP: gap 15 → **12%**, ep20 gap 20 → **16%**, debounce 10 → **5**,
  6. `htf100`: min. pole gain 100 → **80%**.
- `pine check`: 0 błędów, 0 ostrzeżeń; SHA repo = SHA TV (`7acb9301…`).
- Scrape: GPW_NC_IT23 (434/434) + US_BIG_IT23 (843/843), import + `db_verify` 0 niezgodności.
- **Wynik ratunku (n GPW / n US, avgR GPW / US, PF GPW / US):**
  | sygnał | GPW n / avgR / PF | US n / avgR / PF | status |
  |---|---|---|---|
  | ai-caplow | 145 / 0,21 / 1,30 | 636 / 0,23 / 1,29 | **OK** |
  | ai-wonhp | 662 / 0,79 / 2,35 | 1752 / 0,37 / 1,61 | **OK** |
  | ai-vcp2 | 298 / 1,55 / 3,47 | 254 / 0,24 / 1,41 | **OK** |
  | ai-vcp3 | 113 / 0,25 / 1,41 | 84 / 0,14 / 1,22 | GPW −7, US −156 |
  | ai-vcp3c | 130 / 0,30 / 1,44 | 168 / 0,26 / 1,40 | GPW OK, US −72 |
  | ai-obvq | 449 / 0,26 / 1,49 | 258 / 0,32 / 1,57 | **OK** |
  | ai-obvdiv | 179 / 0,64 / 1,88 | 597 / 0,53 / 1,69 | **OK** |
  | ai-epu | 153 / 0,22 / 1,34 | 219 / 0,45 / 2,00 | GPW OK, US −21 |
  | ai-ep20u | 84 / 0,48 / 1,75 | 81 / 0,96 / 3,32 | za mało |
  | ai-ep / ai-ep20 | 27 / 9 | 56 / 13 | za mało (duplikaty `epu`/`ep20u`) |
  | ai-htf100 | 24 / 0,51 / 1,78 | 75 / 0,36 / 1,55 | za mało |
- **Spełniły minimum:** caplow, wonhp, vcp2, vcp3c (GPW), obvq, obvdiv; `epu` prawie (US 219/240).
- **Wciąż poniżej:** vcp3, vcp3c (US), ep, ep20, ep20u, epu (US), htf100.
  `ep`/`ep20` to duplikaty `epu`/`ep20u` z bramką rynkową; `htf100` to rzadki wariant `htf`.
- Wniosek: IT24 = ostatnia próba dla `epu`/`ep20u`/`vcp3c` (niższy gap/debounce, VCP debounce 5)
  oraz rekomendacja wycofania `ep`, `ep20`, `htf100` i ewentualnie `vcp3`, jeśli nadal nie osiągną minimum
  bez psucia jakości.

## IT24 — ostatnia próba dla EP i VCP
- Plik: `variants/ETSB-ia_it24.pine` (1334 linie, 41 sygnałów)
- Zmiany: EP gap 12 → **11%**, ep20 gap 16 → **14%**, debounce 5 → **3**;
  VCP debounce 10 → **5**, cheat max depth 12 → **14%**.
- `pine check`: 0 błędów, 0 ostrzeżeń; SHA repo = SHA TV (`05bbfd23…`).
- Scrape: GPW_NC_IT24 (434/434) + US_BIG_IT24 (843/843), import + `db_verify` 0 niezgodności.
- **Wynik (n GPW / n US, avgR GPW / US, PF GPW / US):**
  | sygnał | GPW | US | status |
  |---|---|---|---|
  | ai-epu | 199 / 0,23 / 1,35 | **250** / 0,20 / 1,42 | **OK** (jakość US na granicy) |
  | ai-vcp2 | 304 / 1,55 / 3,47 | **257** / 0,20 / 1,34 | **OK** (jakość US na granicy) |
  | ai-vcp3c | 135 / 0,27 / 1,39 | 182 / 0,22 / 1,32 | US −58 |
  | ai-vcp3 | 117 / 0,36 / 1,57 | 87 / 0,13 / 1,22 | **odrzucony** (US jakość + próbka) |
  | ai-ep20u | 112 / 0,37 / 1,60 | 123 / 0,28 / 1,63 | za mało (GPW −8, US −117) |
  | ai-ep / ai-ep20 | 34 / 12 | 68 / 21 | **do wycofania** (duplikaty `epu`/`ep20u`) |
  | ai-htf100 | 24 / 0,51 / 1,78 | 76 / 0,37 / 1,58 | **do wycofania** (rzadki wariant `htf`) |
- Wniosek: dalsze luźnienie `ep20u`/`vcp3`/`vcp3c` pogarsza jakość szybciej niż przyrost próbki.
  IT25 = **(a)** optymalne per-sygnłowe progi dla rdzenia (6% tam, gdzie próbka pozwala),
  **(b)** ostatnia mikro-korekta `vcp3c` (debounce 4), **(c)** rekomendacja wycofania
  `ep`, `ep20`, `ep20u`, `vcp3`, `htf100`.

## IT25 — optymalne per-sygnłowe progi (maks. jakość przy min. 120/240)
- Plik: `variants/ETSB-ia_it25.pine` (1336 linii, 41 sygnałów)
- Progi:
  - **6%**: `aiMtsb`, `aiRmv1…3`, `aiEt4sb`, `aiMtsbV2a/b/e`,
  - **5%**: `aiEtc1…3` (bezpośrednio), `aiMtc1…3`, `aiMtsbV2c`, `aiVwapTag`,
  - **4%**: `aiEt3sb`, `aiObvDiv`, `aiWonTurn`, `aiMtsbV2d`,
  - **off**: `flatb`, `caplow`, `wonhp`, `htf`, `et1yh`, rzadkie.
- `pine check`: 0 błędów, 0 ostrzeżeń; SHA repo = SHA TV (`8eee7733…`).
- Scrape: GPW_NC_IT25 (434/434) + US_BIG_IT25 (843/843), import + `db_verify` 0 niezgodności.
- **Wynik: jakość rdzenia wróciła do poziomu 6%.**
  | sygnał | GPW n / avgR / PF | US n / avgR / PF |
  |---|---|---|
  | ai-mtsb | 255 / 1,89 / 3,55 | 1955 / 0,93 / 2,19 |
  | ai-rmv1 | 566 / 1,57 / 3,08 | 4201 / 0,78 / 2,01 |
  | ai-rmv3 | 251 / 2,51 / 4,18 | 2030 / 0,62 / 1,77 |
  | ai-et4 | 183 / 2,26 / 4,10 | 1507 / 0,60 / 1,75 |
  | ai-v2a | 241 / 2,49 / 4,43 | 1482 / 0,83 / 2,10 |
- Pozostałe braki: `etc2` 116, `vcp3` 119, `ep20u` 112, `ep`/`ep20`/`htf100`,
  `vcp3c` US 182. IT26 = mikro-korekty (`etc2` 4%, VCP debounce 3, EP20 gap 13).

## IT26 — domknięcie minimumów
- Plik: `variants/ETSB-ia_it26.pine` (1336 linii, 41 sygnałów)
- Zmiany: `aiEtc2` → 4%, VCP debounce 4 → **3**, EP20 gap 14 → **13%**.
- Scrape: GPW_NC_IT26 (434/434) + US_BIG_IT26 (843/843), import + `db_verify` 0 niezgodności.
- **Wynik: 35/41 sygnałów spełnia minimum 120/240.**
  - `etc2` i `ep20u` (GPW) wróciły powyżej 120.
  - **Poniżej minimum (6):** `ep` (34/67, GPW avgR −0,23), `ep20` (19/27, GPW −0,05),
    `ep20u` (135/148, US < 240), `htf100` (24/76), `vcp3` (119/90, US avgR 0,12),
    `vcp3c` (137/183, US < 240).
  - `ep`/`ep20` to duplikaty `epu`/`ep20u`; `htf100` to rzadki wariant `htf`;
    `vcp3`/`vcp3c` nie osiągają 240 na US bez dalszego psucia jakości.
- **Rekomendacja:** soft-retire 6 sygnałów (znikają z tabeli, plotów i alertów; definicje i archiwum
  pozostają w kodzie). Aktywny zestaw = **35 sygnałów**, wszystkie z n ≥ 120 GPW / 240 US.

## IT27 — Qullamaggie wg dokumentacji: EP light + EPq strict + wierny HTF
- Plik: `variants/ETSB-ia_it27.pine` (1376 linii, 41 sygnałów w tabeli)
- **EP light (wdrożone na `ai-ep`/`epu`):** gap 8%, volume 2,5×, RS rising, baza 126/45%,
  bez trendu 10/50 i higher lows. Efekt: więcej sygnałów i lepsza jakość.
- **EPq strict (`ai-epq`, nowy):** gap 10%, volume 4×, trend 10/50 + close > 50 + RS,
  higher lows 20/60, mocne zamknięcie. Zastąpił `ai-ep20` w tabeli (ep20 usunięty z tabeli,
  pomiary historyczne w bazie zachowane).
- **HTF wierny:** htf100 pole 100%, flag depth 20/10%, VDU 0,8, breakout vol 1,5×,
  10>20 + rosnące 20 + close > 50, higher lows.
- `pine check`: 0 błędów, 0 ostrzeżeń; SHA repo = SHA TV (`7052940c…`).
- Scrape: GPW_NC_IT27 (434/434) + US_BIG_IT27 (843/843), import + `db_verify` 0 niezgodności.
- **Wynik:**
  | sygnał | GPW n / avgR / PF | US n / avgR / PF | ocena |
  |---|---|---|---|
  | ai-epu (light) | 293 / 0,263 / 1,44 | 453 / 0,225 / 1,54 | **lepiej** (było 200/248) |
  | ai-ep (light, gated) | 45 / 0,136 / 1,23 | 129 / 0,344 / 1,97 | OK jakościowo |
  | ai-epq (strict) | 4 / −1,00 / 0,00 | 13 / −0,17 / 0,72 | **za mało / słabo** |
  | ai-ep20u | 45 / 0,63 / 2,11 | 25 / 0,20 / 1,35 | poniżej minimum |
  | ai-htf (wierny) | 64 / 0,328 / 1,56 | 131 / 0,171 / 1,27 | **regresja** (142/523) |
  | ai-htftight (wierny) | 27 / −0,11 / 0,85 | 49 / 0,144 / 1,23 | **regresja** |
  | ai-htf100 (wierny) | 6 / 0,93 / 3,85 | 5 / 1,07 / 2,80 | za mało |
- **Wnioski:**
  1. Lekkie filtry EP z dokumentu **działają**: `epu` 200/248 → 293/453, avgR i PF w górę.
  2. Pełny strict EP jest na naszych danych zbyt rzadki i jakościowo zły (4/13 zdarzeń).
  3. Wierny HTF **nie działa** w naszej dziennej formule: ścina próbkę 2–10× i nie poprawia
     avgR/PF. Reguły „tight flag/VDU/10>20/higher lows” są zbyt restrykcyjne dla naszego
     pomiaru (close entry, stały stop/30 barów).
- Wniosek: IT28 = **(a)** revert HTF do wersji IT26 (luźniejszej), **(b)** EPq poluzować
  (gap 9%, volume 3×, trend/RS, bez higher lows/strong close) albo wycofać, **(c)** decyzja
  o `ep20u` i `htf100` (poniżej minimum).

## IT28 — revert HTF, EPq light, soft-retire 5
- Plik: `variants/ETSB-ia_it28.pine` (1354 linie, 36 sygnałów w tabeli)
- Zmiany:
  1. HTF wraca do parametrów IT26 (flag 30/15%, VDU 1,0, breakout 1,2×, bez 10>20/higher lows),
  2. `ai-epq` poluzowany: gap 9%, volume 3×, trend/RS, bez higher lows i strong close,
  3. soft-retire: `ai-ep`, `ai-ep20u`, `ai-htf100`, `ai-vcp3`, `ai-vcp3c`.
- `pine check`: 0 błędów; dodatkowo `table.clear()` i `iShowSigPerfTable=true`, żeby scraper
  nie czytał starych komórek po zmianie liczby wierszy.
- Scrape: GPW_NC_IT28 (434/434) + US_BIG_IT28 (843/843), import + `db_verify` 0 niezgodności.
- **Wynik: 35/36 sygnałów spełnia minimum; jedyny wyjątek to `ai-epq`.**
  | sygnał | GPW n / avgR / PF | US n / avgR / PF |
  |---|---|---|
  | ai-epu | 288 / 0,269 / 1,45 | 452 / 0,221 / 1,53 |
  | ai-epq | 18 / 0,238 / 1,36 | 45 / 0,151 / 1,30 |
  | ai-htf | 140 / 0,403 / 1,65 | 523 / 0,240 / 1,38 |
  | ai-htftight | 128 / 0,324 / 1,51 | 481 / 0,199 / 1,32 |
  | ai-mtsb | 255 / 1,892 / 3,55 | 1954 / 0,927 / 2,19 |
- Wniosek: EP light i HTF w wersji IT26 zostają; EPq nie spełnia nawet progu 60/120,
  więc w IT29 wypada z tabeli (zostaje w kodzie/archiwum jako research).

## IT29 — finalna konsolidacja do 22 sygnałów (stop)
- Plik: `variants/ETSB-ia_it29.pine` (1300 linii, **22 sygnały**)
- Wybór per rodzina (1–2 wersje, wszystkie ≥120 GPW / ≥240 US):
  - ET: `et3`, `et4`; ETC: `etc1`, `etc3`; RMV: `rmv1`, `rmv3`;
  - MTSB: `mtsb`, `mtsbv2c`; MTC: `mtc1`, `mtc3`; HTF: `htf`, `htftight`;
  - pojedyncze: `obvdiv`, `vcp2`, `epu`, `ragpb`, `wonhp`, `wonturn`, `vwaptag`, `caplow`,
    `flatb`, `vip`.
- Poza tabelą (kod/archiwum/historia DB): `ep`, `ep20`, `ep20u`, `htf100`, `vcp3`, `vcp3c`,
  `epq`, `et1yh`, `etc2`, `rmv2`, `mtc2`, `mtsbv2a/b/d/e`, `mtsbq`, `mtc3q`, `et4q`, `obvq`,
  `vcp2c`.
- Scrape: GPW_NC_IT29 (434/434) + US_BIG_IT29 (843/843), import + `db_verify` 0 niezgodności.
- **Wynik finalny:** 22/22 sygnałów spełnia minimum; raport w `analysis/FINAL_SELECTION.md`
  i `analysis/FINAL_SELECTION.csv`.
- **Stop:** po IT29 przerwano iteracje w dotychczasowej formie (decyzja użytkownika).

## IT30 (post-IT29) — General Filter dla wszystkich sygnałów
- Plik: `variants/ETSB-ia_it30.pine` (1325 linii, 22 sygnały w tabeli)
- Dodana sekcja **General filter for signal** wzorowana na `ETSB_earlyTrendStrongBreakout.pine`:
  - `Turnover/median len` (30), `Min. turnover [M]` (0,20), `Min. ADR [pct]` (3,0),
    `Min. price` (1,0), `Max. price` (1750), `Max. distance from LoD [pct]` (67),
  - logika: średni **i** medianowy turnover > próg (pojedynczy spike nie kwalifikuje cienkiej spółki),
    ADR > próg, cena w przedziale, `syminfo.type == 'stock'`, odległość od LoD w normie
    (z korektą reżimu `regimeMod`).
- `generalFilterMask` jest częścią `sigMask`, więc `f_gate` blokuje **ploty, alerty i statystyki tabeli**
  dla spółek niespełniających kryteriów. `ai-epu` (celowo bez bramki rynkowej) używa
  `aiEp and generalFilterMask`.
- Inputy General Filter są **na samym początku** skryptu (pierwsza grupa w UI), jak w `ETSB_earlyTrendStrongBreakout.pine`.
- `pine check`: 0 błędów, 0 ostrzeżeń; SHA repo = SHA TV (`aafa20cd…`).
- Weryfikacja działania: podniesienie `Min. turnover` do 1000 wyzerowało sygnały w tabeli;
  powrót do 0,20 przywrócił je.
- Uwaga: to zmiana po zamknięciu iteracji IT29 — nie robiono ponownego pełnego scrape’a;
  filtr jest domyślnie ON i można go wyłączyć inputem `General filter ON`.

## IT31 (post-IT29) — EffOk na win rate zamiast legacy success rate
- Plik: `variants/ETSB-ia_it31.pine` (1334 linie, 22 sygnały)
- `XEffOk` nie używa już `SuccRateOk`/`QualityOk` z DREPerf. Nowa bramka lokalna:
  ```pine
  f_effOk(winRate, avgReturn, sigCount, wilsonLb) =>
      winRate > iMinSigSuccessRate and avgReturn > adrCond
      and (not iUseQualityGate or (sigCount >= iMinSigCount and wilsonLb >= iMinSigWilsonLb))
  ```
  czyli **win% > `iMinSigSuccessRate`** zamiast legacy „no stop-hit” success rate.
- `iMinSigSuccessRate` title zmieniony na `Min. win rate [pct]`.
- `avgReturn` (mixed % return) i próg `1,2 × ADR` zostają bez zmian.
- `iUseQualityGate` nadal dokłada `n ≥ iMinSigCount` i Wilson LB win rate.
- `pine check`: 0 błędów, 0 ostrzeżeń; SHA repo = SHA TV (`6c241f18…`).
- Weryfikacja: `Min. win rate = 99` + „show only good sigs.” ukrywa wszystkie wiersze;
  powrót do 46 przywraca 22 sygnały.
- Uwaga: DREPerf nadal **liczy** legacy `SuccRateOk`/`QualityOk` wewnątrz `signalQualityFull`,
  ale ETSB-ia ich nie używa. Całkowite usunięcie wymagałoby nowej wersji biblioteki DREPerf
  (wpłynęłoby też na inne skrypty).

## Podsumowanie ścieżki optymalizacji
| iteracja | główna zmiana | efekt |
|---|---|---|
| IT0 | baseline (EP + market timing, bramka OFF) | 30 sygnałów, `ai-ep20` score +0.47 |
| IT1 | **bramka distribution days + FTD ON** | **23/30 poprawionych** — największy skok jakości |
| IT2 | reguła MA zamiast dystrybucji | gorsza (22 sygnały niżej) → odrzucona |
| IT3 | wolumen wybicia 1.25→1.5, flatb ext 90→80 | 7 poprawionych, 2 pogorszone |
| IT4 | rmv vol 1.15→1.3, mt below-high 20→15, mt rise 25→28 | neutralne (3/2) |
| IT5 | rmv vol → 1.15 + walidacja obu rynków | finał + dream team |
