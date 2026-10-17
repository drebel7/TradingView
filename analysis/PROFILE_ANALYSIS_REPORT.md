# ETSB-ia — profil spółki a jakość sygnałów

**Raport z analizy przekrojowej wykonanej na pomiarach już zebranych w `db/analysis.db`**
(baza: 48 runów, 731 116 pomiarów; do analizy użyto ostatniego runu na rynek — IT12:
GPW_NC run 47, US_BIG run 48; konwencja pomiaru: wejście = zamknięcie, stop = max(lowest 3, close −8%),
horyzont 30 barów, bramka rynkowa włączona; 36 sygnałów).

> Wszystkie statystyki są **pooled** (ważone liczbą zdarzeń `n`), nie średnią ze średnich —
> przy 1–2 transakcjach na spółkę średnia per spółka to szum (patrz lekcja z `score_mean`).

---

## TL;DR — co wynika z danych

1. **Zmienność (ADR) jest najsilniejszym wymiarem profilu — silniejszym niż wielkość czy płynność.**
   - GPW: `ADR ≥5%` → avgR **1,65**, PF **3,44** vs `ADR <5%` → 0,31 / 1,50 (13,5% zdarzeń).
   - US: `ADR ≥5%` → 0,74 / 2,01; ale **tylko dla MCap ≥200M** → **0,89 / 2,23** (22% zdarzeń).
2. **MCap to głównie proxy ADR.** W *każdym* koszyku MCap na GPW spółki z ADR ≥5% mają 3–8× wyższy avgR.
   Na US zależność jest odwrotna dla małych spółek: `MCap <200M` + `ADR ≥5%` = **−0,17** (pułapka).
3. **Płynność ma odwrotną rolę na obu rynkach.** GPW: najlepiej 2–10M obrotu (0,69 / PF 2,22),
   najgorzej ≥50M (0,09). US: 80% zdarzeń i cały edge jest w ≥50M (0,48 / PF 1,80); 0,5–2M jest ujemne.
4. **Wysokie ADR nie podnosi win% — podnosi wielkość wygranych.** GPW: ADR<3% → win 31,5%, avgR 0,30;
   ADR≥8% → win 26,4%, avgR **5,03**. To filtr „grubych ogonów", nie „częstszego trafiania".
5. **Edge siedzi w ekspansji, nie w ciasnych bazach.** Eksperyment IT12 (`f_qualityBreakout`: ciasna baza
   + silne zamknięcie) podniósł win% (32→40%) ale **ściął avgR 2–4×** (0,48→0,14 na `mtsb`) — klasyczne
   „bezpieczne, małe" wybicia. Obecny `strongBreakout` (świeże wybicie + wolumen + AVWAP) jest lepszy.
6. **Profil jest rynkowo-specyficzny i per-sygnałowy.** 24/28 sygnałów na GPW woli wysoką zmienność,
   ale `htf`/`htftight`/`ragpb`/`vcp3c` wolą niską; na US `htf`/`htftight` **przełączają się** na wysoką.
   Jeden globalny próg profilu byłby więc błędem.

---

## 1. Baza i metoda

| element | wartość |
|---|---|
| Runy w analizie | 47 (GPW_NC), 48 (US_BIG) — konfiguracja IT12 |
| Zdarzenia | GPW 35 446 (423 spółki), US 73 257 (796 spółek) |
| Profil | `company_metric`: MCap, ADR%, ATR, avg turnover, price; `company_profile`: sektor, industry, lata na giełdzie |
| Pokrycie | GPW 434/434, US ~800/843 spółek z metrykami |

Metryki: `win%` = odsetek transakcji z dodatnim wynikiem, `avgR` = średni wynik w jednostkach ryzyka
(ryzyko = odległość stopa od wejścia), `PF` = suma wygranych R / |suma przegranych R|, `suma R` = łączny
wynik systemu w R (miara „ile okazji × jakość").

**Zastrzeżenia:** analiza jest *in-sample* (buckety wybrane po obejrzeniu danych); delty < ~5% to szum
między-runowy; wąskie komórki (np. `ADR≥5 & turnover 2–50M` = 622 zdarzenia / 6 spółek) są przeuczone;
klasyfikacja sektorowa TradingView bywa nieprecyzyjna.

---

## 2. ADR — główny driver

**GPW (system: 35 446 zdarzeń, win 32,1%, avgR 0,49, PF 1,78):**

| ADR | spółek | zdarzeń | win% | avgR | PF | suma R |
|---|---|---|---|---|---|---|
| <3% | 220 | 18 717 | 31,5 | 0,30 | 1,48 | 5 663 |
| 3–5% | 138 | 11 948 | 34,0 | 0,33 | 1,53 | 3 915 |
| 5–8% | 50 | 3 887 | 30,8 | **0,87** | **2,31** | 3 385 |
| ≥8% | 15 | 894 | 26,4 | **5,03** | **7,96** | 4 497 |

**US (system: 73 257 zdarzeń, win 33,2%, avgR 0,44, PF 1,69):**

| ADR | spółek | zdarzeń | win% | avgR | PF | suma R |
|---|---|---|---|---|---|---|
| <3% | 248 | 24 901 | 37,1 | 0,15 | 1,25 | 3 627 |
| 3–5% | 312 | 29 587 | 35,0 | 0,50 | 1,81 | 14 939 |
| 5–8% | 203 | 16 893 | 26,2 | **0,78** | **2,07** | 13 188 |
| ≥8% | 33 | 1 876 | 18,0 | 0,42 | 1,52 | 791 |

Wniosek: na GPW jakość rośnie monotonicznie z ADR; na US optimum to **5–8%** (≥8% już nie pomaga —
zbyt spekulacyjne, win tylko 18%).

### Kontrola „czy to nie są po prostu małe spółki?" (MCap × ADR)

**GPW — avgR (n):**

| MCap | ADR <5% | ADR ≥5% |
|---|---|---|
| <50M | 0,37 (5 611) | **2,90** (1 464) |
| 50–200M | 0,27 (6 663) | **0,99** (1 706) |
| 200M–1B | 0,48 (8 528) | **1,49** (867) |
| 1–10B | 0,19 (5 881) | **1,09** (375) |
| >10B | 0,14 (3 499) | – |

W **każdym** koszyku MCap wysokie ADR daje 2–8× lepszy avgR → to ADR jest zmienną, a MCap tylko ją
częściowo proxy'uje.

**US — avgR (n):**

| MCap | ADR <5% | ADR ≥5% |
|---|---|---|
| <50M | 1,98 (267) | **−0,17** (715) |
| 50–200M | 0,08 (737) | **−0,16** (1 593) |
| 200M–1B | 0,51 (3 763) | **0,78** (5 002) |
| 1–10B | 0,36 (15 416) | **1,00** (7 839) |
| >10B | 0,32 (31 146) | **0,78** (3 353) |

Na US reguła musi być warunkowana wielkością: **ADR ≥5% dopiero od MCap ≥200M**; w małych spółkach
wysoka zmienność to pułapka (−0,17).

---

## 3. Płynność (turnover) — odwrotna rola na rynkach

**GPW:**

| turnover | spółek | zdarzeń | win% | avgR | PF |
|---|---|---|---|---|---|
| <0,5M | 319 | 25 217 | 29,5 | 0,49 | 1,74 |
| 0,5–2M | 47 | 4 262 | 38,1 | 0,54 | 1,94 |
| 2–10M | 27 | 2 703 | 38,3 | **0,69** | **2,22** |
| 10–50M | 17 | 1 920 | 42,1 | 0,42 | 1,77 |
| ≥50M | 13 | 1 344 | 35,6 | 0,09 | 1,16 |

**US:**

| turnover | spółek | zdarzeń | win% | avgR | PF |
|---|---|---|---|---|---|
| <0,5M | 15 | 829 | 12,4 | 0,35 | 1,40 |
| 0,5–2M | 27 | 1 764 | 20,1 | **−0,07** | 0,91 |
| 2–10M | 77 | 6 544 | 22,5 | 0,52 | 1,67 |
| 10–50M | 148 | 12 442 | 27,1 | 0,33 | 1,47 |
| ≥50M | 529 | 51 678 | 36,9 | 0,48 | 1,80 |

GPW: sweet spot **2–10M** (średnie obroty), mega-płynne ≥50M są najsłabsze (duże spółki = mało ruchu).
US: masa i edge są w **≥50M**; filtry „2–50M" (przeniesione z GPW) **pogarszają** US.

---

## 4. Sektory (tilt, nie filtr)

**GPW (top wg sumy R):** Finance 0,84 / PF 2,23 (5 344 zd.); Process Industries 0,54 / 1,89;
Consumer Non-Durables 0,60 / 1,95; Energy Minerals 1,36 / 3,28 (**tylko 8 spółek** — ostrożnie);
Technology Services 0,33 / 1,53. Słabe: Retail Trade 0,10, Utilities 0,15.

**US (top):** Electronic Technology 0,81 / 2,40 (10 626 zd.); Technology Services 0,86 / 2,37 (9 843);
Producer Manufacturing 0,71 / 2,10; Finance 0,47 / 1,76. Słabe: Health Technology 0,19 / 1,30;
Industrial Services 0,18 / 1,29; Non-Energy Minerals 0,24 / 1,33.

Sektor jest silnie skorelowany z ADR (energetyka, elektronika = wysokie ADR), więc **nie należy go
traktować jako niezależnego filtra** — raczej jako tilt do wielkości pozycji.

---

## 5. Per-sygnał: dwie klasy zachowań

**GPW — 24/28 sygnałów preferuje wysoką zmienność** (ADR ≥5%), m.in.:
`etc2` (ADR<5: 0,30 → ≥8%: 3,79), `mtsb` (0,17 → 1,45), `rmv1` (0,19 → 2,62), `vwaptag` (−0,10 → 1,80),
`et3` (0,15 → 3,57), `flatb` (1,18 → 6,86).

**Wyjątki „quiet" (GPW):** `htf` (ADR<5: 0,72 vs ≥5: −0,54), `htftight` (0,70 vs −0,54),
`ragpb` (najlepiej 3–5%), `vcp3c`, `vcp2c`. To sygnały zbudowane na *spokoju* (flaga, pullback),
więc wysokie ADR im szkodzi.

**Na US częściowo odwrotnie:** `htf`/`htftight` wolą wysoką zmienność (0,26–0,47 vs ~0,1),
a `ragpb`, `vcp3`, `vcp3c`, `epu` wolą niską. **Preferencja profilu jest więc funkcją rynku i sygnału,
nie cechą sygnału.**

---

## 6. Symulacja: ile daje filtr profilowy (cały system)

**GPW:**

| filtr | spółek | zdarzeń | win% | avgR | PF | ΔavgR | ΔPF |
|---|---|---|---|---|---|---|---|
| bez filtra | 423 | 35 446 | 32,1 | 0,49 | 1,78 | – | – |
| **ADR ≥5%** | 65 | 4 781 | 30,0 | **1,65** | **3,44** | **+1,16** | **+1,66** |
| ADR ≥3% | 203 | 16 729 | 32,8 | 0,71 | 2,11 | +0,21 | +0,33 |
| ADR <5% | 358 | 30 665 | 32,5 | 0,31 | 1,50 | −0,18 | −0,28 |
| turnover 2–50M | 44 | 4 623 | 39,9 | 0,58 | 2,04 | +0,08 | +0,26 |
| MCap ≥50M | 299 | 27 519 | 34,4 | 0,39 | 1,65 | −0,10 | −0,13 |

**US:**

| filtr | spółek | zdarzeń | win% | avgR | PF | ΔavgR | ΔPF |
|---|---|---|---|---|---|---|---|
| bez filtra | 796 | 73 257 | 33,2 | 0,44 | 1,69 | – | – |
| ADR ≥5% | 236 | 18 769 | 25,4 | 0,74 | 2,01 | +0,30 | +0,31 |
| **ADR ≥5% & MCap ≥200M** | 191 | 16 194 | 27,2 | **0,89** | **2,23** | **+0,44** | **+0,54** |
| turnover 2–50M | 225 | 18 986 | 25,5 | 0,40 | 1,55 | −0,05 | −0,15 |
| MCap ≥50M | 744 | 68 849 | 33,6 | 0,46 | 1,72 | +0,01 | +0,03 |

**Cena:** filtr `ADR≥5` zostawia 13,5% zdarzeń na GPW i 22% na US. To nie jest darmowa poprawa —
to wybór „mniej, ale lepiej". Dlatego w rekomendacjach niżej proponuję **tryb rankingowy** obok filtra.

---

## 7. Wnioski → jak zbudować lepsze sygnały

### R1. Bramka profilu **per sygnał i per rynek** (nie globalna)
- GPW: rodziny breakout/expansion (`et*`, `etc*`, `mt*`, `mtsb`, `rmv*`, `obvdiv`, `vwaptag`, `flatb`,
  `caplow`, `ep*`) → wymagaj **ADR ≥5%**; rodziny „quiet" (`htf`, `htftight`, `ragpb`, `vcp2c`, `vcp3c`)
  → **ADR <5%** (u nich wysoka zmienność szkodzi).
- US: dla wszystkich rodzin poza „quiet" → **ADR ≥5% i MCap ≥200M**; małe spółki z ADR ≥5% odrzucaj.
- Implementacja: `iProfileMinAdrPct` / `iProfileMaxAdrPct` **na grupę sygnału** (inputy w grupach
  `Signal: ...`), domyślnie per rodzina, z możliwością wyłączenia.

### R2. **Tryb rankingowy** zamiast wyłącznie twardego filtra
Twardy filtr `ADR≥5` obcina 78–86% okazji. Zamiast tego (lub równolegle):
- licz **profilowy mnożnik siły** sygnału: np. `strength = 1 + k·(ADR − 3%)` dla ADR >3%, 0 poniżej,
- sortuj/priorytetyzuj alerty i **skaluj wielkość pozycji** (np. 0,5× dla ADR 3–5%, 1,5× dla 5–8%).
- Zaleta: zachowujesz rzadkie okazje i masz jawny kompromis jakość/ilość; wada: wymaga dyscypliny
  w egzekucji (nie każdy sygnał = ta sama pozycja).

### R3. Płynność **rynkowo-specyficzna**
- GPW: preferuj **2–10M** obrotu; nie handluj ≥50M (najgorszy avgR) i uważaj na <0,5M (poślizg).
- US: **≥50M**, unikaj 0,5–2M (ujemne!).
- To jest sprzeczne z jednym globalnym progiem — musi być warunkowane rynkiem.

### R4. Sektor jako **tilt**, nie filtr
- US: nadwaga Electronic Technology / Technology Services, podwaga Health Technology, Industrial Services.
- GPW: nadwaga Finance / Process Industries / Consumer Non-Durables, podwaga Retail Trade / Utilities.
- Ze względu na małe próbki i szum klasyfikacji — stosować jako korektę wielkości pozycji, nie wykluczenie.

### R5. Nie wracać do „ciasnych baz"
`f_qualityBreakout` (IT12) przegrał: wyższy win%, ale 2–4× niższy avgR. Edge systemu jest w **ekspansji
zmienności** (stąd `rmv*`, `et*`, `mtsb` działają lepiej na wysokim ADR). Kolejne eksperymenty wejść
należy kierować w stronę *siły wybicia* (wolumen, rozmiar świecy vs ADR, domknięcie), a nie w stronę
„bezpiecznych" wzorców.

### R6. Co jeszcze warto zbadać (na tych samych danych / kolejnych pomiarach)
- **Interakcja ADR × sygnał × horyzont**: na US horyzont 45–60 barów dawał +40% sumy R (IT11),
  a wysokie ADR daje grube ogony — sprawdzić, czy efekt ADR jest mocniejszy przy dłuższym horyzoncie.
- **ADR jako zmienna ciągła** (regresja/decile) zamiast koszyków — czy optimum na US to naprawdę 5–8%.
- **Sektor × ADR** (czy tilt sektorowy przetrwa kontrolę na ADR).
- **Ranking vs filtr w praktyce**: symulacja portfela (np. max 5 pozycji, wybór po `strength`).

---

## 8. Ograniczenia

1. **In-sample.** Reguły ADR/turnover wybrano po obejrzeniu tych samych danych → konieczna walidacja
   na innym okresie (np. tylko ostatnie 2 lata vs wcześniejsze) lub na innej liście.
2. **Ekstremalne komórki** (`ADR≥8%` GPW: 15 spółek, avgR 5,03; `ADR5-8 × turnover 2–10M`: 6 spółek,
   PF 5,89) są niestabilne — nie budować na nich reguł.
3. **Konwencja pomiaru** (stop 3-świecowy z capem 8%, horyzont 30 barów) wpływa na R;
   przy wysokim ADR cap 8% *zaniża* R (ich dołek bywa dalej niż 8%) → efekt ADR jest raczej niedoszacowany.
4. **Sektor** = klasyfikacja TradingView; część spółek ma „n/a".
5. Analiza obejmuje okres dostępny w TradingView dla tych list (kilka lat) — nie zawiera zmian reżimu
   poza tym oknem.

---

## 9. Aneks — tabele źródłowe

- `analysis/company_profile_analysis.md` — pełne tabele: system wg wymiarów, sygnały × ADR, sygnały × MCap,
  sygnały × turnover, symulacja filtrów (skrypt `scripts/company_profile_analysis.py`).
- `analysis/profile_deep_dive.md` — ADR × turnover 2D, sektory, per-sygnał split ADR<5/≥5,
  symulacja filtrów z regułą market-aware (skrypt `scripts/profile_deep_dive.py`).
- `analysis/company_profile_runs.csv`, `analysis/profile_deep_dive.csv` — dane maszynowe.
