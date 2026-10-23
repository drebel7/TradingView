# VCP Minervini — dziennik iteracji

Cel: zaimplementować sygnał VCP (Volatility Contraction Pattern) wg
`yt/docs/trading/Minevrini/Minervini-strategy.md` (sekcje 6 i 10) i znaleźć zestaw
parametrów o najlepszej relacji jakości do liczby sygnałów.

Wzorzec kodu: `src/indicators/ETSB_earlyTrendStrongBreakout.pine` (sekcje, DRELib,
DREPerf, tabela 9 kolumn). Bez `plot`/`plotshape`/alertów — tylko tabela wyników.

- Wskaźnik: `src/indicators/VCP_Minervini.pine` (nazwa na wykresie: `Minervini VCP (perf sweep)`)
- Archiwa: `variants/VCP_it0.pine`, `variants/VCP_it1.pine`, `variants/VCP_it2_loose.pine`,
  `variants/VCP_it3.pine`, `variants/VCP_final_shortlist.pine`
- Scrape: `scripts/tv_table_scraper.py` → `analysis/{PL,US}_VCP_itN_*.csv` → `scripts/summarize_signals.py`
- Model wyniku (DREPerf): wejście = close bara sygnału, stop strukturalny (final contraction low,
  min 3%, max 8%), okno 30 barów; sukces = stop nietknięty; metryki: win%, N, avgR, PF, maxDD,
  score (sample-aware), suma R wygranych/przegranych.

Kryteria oceny: pooled `score`, `avgR`, `PF`, `win%`, `score_pos_pct` (powtarzalność na symbolach)
oraz N. Próbki < 30 zdarzeń traktowane jako szum.

---

## IT0 — siatka kanoniczna + perturbacje (40 wariantów)

Wiersz 1 = wersja kanoniczna wg dokumentu: Trend Template 8/8, prior advance ≥30%,
baza 15–90 sesji, 2–6 kontrakcji, monotoniczne zmniejszanie, final ≤10%, baza ≤40%,
higher lows ≥60%, VDU ≤0.65, last-10d range ≤10%, ATR5/ATR20 ≤0.70, overhead ≤3%,
RS ≥70, wybicie pivot+1%, volume ≥1.4×ADV50, stop strukturalny.

Pozostałe 39 wierszy: po jednej zmianie parametru + uproszczenia (flat base, czysta
kontrakcja zakresu) i alternatywne wejścia (cheat, failed breakout, potwierdzenie 2-dniowe).

Scrape: PL 434/434, US 802/802.

### Wyniki (PL+US, pooled)

| Wariant | N | win% | avgR | PF | score | sc>0 |
|---|---:|---:|---:|---:|---:|---:|
| vcpConfirm (potwierdzenie 2D) | 185 | 48.1 | 0.39 | 1.84 | **0.39** | 52% |
| vcpC3 (3 kontrakcje) | 62 | 48.4 | 0.34 | 1.71 | 0.35 | 51% |
| vcpDry65 (VDU ≤0.65) | 94 | 43.6 | 0.31 | 1.63 | 0.35 | 44% |
| vcpVol20 (vol ≥2.0×) | 65 | 49.2 | 0.28 | 1.65 | 0.35 | 55% |
| vcpVol15 (vol ≥1.5×) | 148 | 43.9 | 0.26 | 1.52 | 0.28 | 45% |
| vcpTtHouse (trend DRELib) | 200 | 47.0 | 0.26 | 1.54 | 0.26 | 48% |
| vcpRsLine (RS vs SMA100) | 241 | 45.6 | 0.25 | 1.52 | 0.25 | 47% |
| **vcpCanon** | **0** | – | – | – | – | – |

Najgorsze: `vcpOh3` (0.11 na PL), `vcpCheat` (win 38%, score 0.22), `vcpChase3` (0.25 ze spadkiem N),
`vcpTtOff` (0.16), `vcpDryOff` (725 zdarzeń, 0.18), `vcpFlat` (705, 0.16),
`vcpRange` (8746, score **−0.13**, win 35.3%).

### Wnioski IT0

1. **Kanoniczna wersja nie generuje sygnałów.** `ATR5/ATR20 ≤ 0.70` mierzone przed barem
   wybicia przepuszcza ~0.03% barów — 0 sygnałów na 1236 symbolach. To bramka „quality”,
   nie hard gate; w praktyce czyni VCP nieużywalnym.
2. **Potwierdzenie 2-dniowe** (close w górnych 40% świecy i powyżej high poprzedniego dnia)
   to najlepszy pojedynczy manewr: +0.18 score, +0.15 avgR, PF 1.84 vs 1.45.
3. **VDU 0.65 zostaje** — wyłączenie podwaja próbkę, ale avgR spada 0.31→0.16.
4. **Wolumen wybicia 1.5–2.0×** działa; 1.2× to za mało.
5. **Więcej kontrakcji = lepsza jakość, mniej sygnałów** (3 kontrakcje: 0.35 przy N=62).
6. **Overhead ≤3% jest rynkowo-zależny**: PL 0.11, US 0.33.
7. **Wejście antycypacyjne (cheat) jest gorsze** od wybicia (win 38% vs 48%).
8. **Mniejszy chase = gorzej** — edge jest w akcjach, które po wybiciu uciekają.
9. **Bez trend template’a jakość spada** (0.16 vs 0.24); wystarcza lekki stack MA.

**Błąd metodologiczny IT0:** wiersz `vcpBase80` został wygenerowany z parametrami
kanonicznymi (błąd generatora), więc jego N=0 jest artefaktem — poprawione w IT1.

---

## IT1 — wokół potwierdzenia + ablacje (40 wariantów)

Baza: luźniejsza kanoniczna (final 12%, ratio 1.00, ATR 1.0, VDU 0.80, volume 1.2×,
overhead 5%, zakres 12%, trend light, RS off, regime off), wejście potwierdzone.
Wiersze: po jednej zmianie + ablacje kombinacji + warianty finalne.

Scrape: PL 434/434, US 802/802.

### Wyniki (PL+US, N ≥ 100)

| Wariant | N | win% | avgR | PF | score | sc>0 |
|---|---:|---:|---:|---:|---:|---:|
| **vcpCfmOh3** (potwierdzenie + overhead ≤3%) | 117 | **50.4** | **0.46** | **2.06** | **0.51** | 53% |
| vcpCfmRegime1 | 127 | 47.2 | 0.44 | 1.95 | 0.46 | 50% |
| vcpCfmMargin0 (bez bufora) | 204 | 49.5 | 0.40 | 1.89 | 0.43 | 54% |
| vcpCfmPrior50 | 113 | 44.2 | 0.39 | 1.77 | 0.42 | 47% |
| vcpCfmHl80 | 175 | 48.6 | 0.41 | 1.90 | 0.42 | 51% |
| vcpCfmVol15 | 107 | 46.7 | 0.40 | 1.83 | 0.41 | 48% |
| vcpCfmTtHouse | 145 | 50.3 | 0.42 | 1.98 | 0.41 | 52% |
| vcpCfmRsLine | 179 | 48.6 | 0.41 | 1.89 | 0.40 | 51% |
| vcpConfirm (IT0) | 185 | 48.1 | 0.39 | 1.84 | 0.39 | 52% |
| vcpCfmAtrOff | 222 | 46.8 | 0.32 | 1.68 | 0.28 | 49% |

Małe próbki (30–70), wysoki score: `vcpCorePrior50` 0.78, `vcpCoreTtHouse` 0.77,
`vcpCoreRsLine` 0.72, `vcpCfmDry65` 0.60 — kierunkowo zgodne, ale zbyt małe, by wybrać.

### Wnioski IT1

1. **Potwierdzenie + ciasny pivot (overhead ≤3%)** to najlepsza kombinacja o N ≥ 100:
   score 0.51, PF 2.06, win 50.4%.
2. **Warstwy jakości dokładają po +0.05–0.15 score** (regime, prior50, higher lows,
   trend house, RS line), ale każda zabiera 30–45% sygnałów.
3. **Wszystkie „jakościowe” dodatki są spójne kierunkowo na PL i US**, choć na US
   efekty są 2–3× słabsze.
4. Próbki nadal małe (N 100–200) — potrzebna iteracja luźniejsza.

---

## IT2 — luźna / wolumenowa (40 wariantów)

Baza „loose”: 2–6 kontrakcji z tolerancją 15% na nogę, final ≤20%, baza ≤60%,
overhead ≤15%, zakres ≤20%, ATR off, VDU 1.0, volume 1.0×, bez bufora, chase ≤12%,
trend light, RS off, regime off, debounce 5, wejście potwierdzone.
Wiersze zaciskają po jednym parametrze — mapa frontu jakość/ilość.

Scrape: PL 434/434, US 802/802.

### Wyniki (PL+US, N ≥ 500)

| Wariant | N | win% | avgR | PF | score | sc>0 |
|---|---:|---:|---:|---:|---:|---:|
| **vcpLooseC3** (3 kontrakcje) | 654 | 46.2 | 0.24 | 1.49 | **0.24** | 45% |
| vcpLooseDry80 | 972 | 43.4 | 0.26 | 1.49 | 0.20 | 47% |
| vcpLooseC1 (1 kontrakcja) | 3968 | 45.4 | 0.23 | 1.48 | 0.18 | 50% |
| vcpLooseVol15 | 708 | 42.9 | 0.21 | 1.40 | 0.18 | 44% |
| vcpLooseR100 | 1757 | 45.0 | 0.24 | 1.48 | 0.16 | 49% |
| vcpLooseDryOff | 2811 | 44.3 | 0.21 | 1.43 | 0.12 | 52% |
| vcpLooseBase | 1996 | 44.3 | 0.23 | 1.45 | 0.13 | 48% |
| vcpLoosePlain (zwykłe wybicie) | 2893 | 43.2 | 0.20 | 1.39 | 0.12 | 49% |
| vcpLooseStopHouse | 1996 | 37.1 | 0.30 | 1.51 | 0.05 | 45% |

### Wnioski IT2

1. **Luźna baza daje 2000 zdarzeń** (vs 185 w IT1), ale score spada 0.39 → 0.13,
   PF 1.84 → 1.45, win 48% → 44%. Front jest stromy.
2. **Spośród luźnych wariantów najlepsze jest C3** (3 kontrakcje): N=654, score 0.24 —
   czyli wymóg trzech kontrakcji pozostaje najlepszym filtrem jakości również przy dużej próbce.
3. **VDU 0.80** utrzymuje N≈1000 przy score 0.20 — najlepszy kompromis „ilość za jakość”.
4. **Potwierdzenie 2D nadal bije zwykłe wybicie** (win 44.3% vs 43.2%, PF 1.45 vs 1.39)
   przy 30% mniejszej liczbie sygnałów.
5. **Dom house stop** podnosi avgR (0.30) ale obniża win% do 37% i score do 0.05 —
   model stopu strukturalnego jest lepszy dla tego sygnału.
6. **US jest trudniejszym rynkiem**: prawie wszystkie luźne warianty mają tam score
   0.10–0.28, a PL 0.19–0.46; filtr RS70/prior50, który wygrywa na PL, na US jest neutralny.

---

## IT3 — mutacje wokół trzech najlepszych „luźnych” wariantów (40 wariantów)

Rodzice (z IT2): `vcpLooseC3` (3 kontrakcje), `vcpLooseDry80` (VDU 0.80), `vcpLooseC1`
(1 kontrakcja). Każdy zachowany jako wiersz referencyjny i obudowany **lateralnymi**
modyfikacjami (final 16, ratio 1.05, minDepth 1.5, baseDepth 50, prior 10, overhead 5/10,
range 16, dry 0.70/0.90, volume 1.1/1.2, chase 10, trend 2/3, RS line, house stop,
debounce 3) — bez systematycznego luzowania ani zaciskania.

Scrape: PL 434/434, US 802/802.

### Wyniki (PL+US, posortowane po score)

| Wariant | PL N / score | US N / score | ALL N | win% | avgR | PF | score |
|---|---:|---:|---:|---:|---:|---:|---:|
| **vcpDry80Oh5** (VDU 0.80 + overhead ≤5%) | 91 / 0.36 | 465 / **0.31** | **556** | **46.6** | **0.33** | **1.68** | **0.32** |
| vcpC3R105 (3 kontr. + ratio 1.05) | 76 / 0.35 | 449 / 0.25 | 525 | 49.0 | 0.28 | 1.61 | 0.26 |
| vcpC3Chase10 | 91 / 0.34 | 549 / 0.23 | 640 | 46.4 | 0.25 | 1.51 | 0.25 |
| vcpC3ref (rodzic) | 92 / 0.31 | 562 / 0.23 | 654 | 46.2 | 0.24 | 1.49 | 0.24 |
| vcpC3MD15 / vcpC3BD50 | 92 / 0.31 | 562 / 0.23 | 654 | 46.2 | 0.24 | 1.49 | 0.24 |
| vcpC3Tt2 | 90 / 0.36 | 510 / 0.20 | 600 | 45.5 | 0.23 | 1.47 | 0.23 |
| vcpDry70 | 134 / 0.38 | 367 / 0.19 | 501 | 41.9 | 0.26 | 1.48 | 0.23 |
| vcpDry80R105 | 158 / 0.37 | 751 / 0.18 | 909 | 44.1 | 0.28 | 1.55 | 0.22 |
| vcpDry80Oh10 | 146 / 0.35 | 709 / 0.19 | 855 | 44.0 | 0.27 | 1.53 | 0.22 |
| vcpDry80Tt3 | 124 / **0.47** | 589 / 0.13 | 713 | 42.9 | 0.25 | 1.48 | 0.20 |
| vcpDry80ref (rodzic) | 169 / 0.25 | 803 / 0.18 | 972 | 43.4 | 0.26 | 1.49 | 0.20 |
| vcpC1Oh10 | 495 / 0.23 | 3273 / 0.19 | 3768 | 45.9 | 0.24 | 1.49 | 0.20 |
| vcpC1ref (rodzic) | 532 / 0.19 | 3436 / 0.18 | 3968 | 45.4 | 0.23 | 1.48 | 0.18 |
| vcpDry80Stop0 (house stop) | 169 / 0.19 | 803 / 0.05 | 972 | 35.8 | 0.27 | 1.44 | 0.08 |

### Wnioski IT3

1. **Overhead ≤5% to najlepsze pojedyncze zacisnienie w luźnej rodzinie.** `vcpDry80Oh5`
   bije rodzica (`vcpDry80`) o +0.12 score przy N 972→556, i — co ważne — poprawia **oba
   rynki** (PL 0.25→0.36, US 0.18→0.31). To jedyny wariant w całym badaniu z tak spójnym
   wynikiem PL/US przy N≥500.
2. **Ratio 1.05 (zamiast 1.15) na trójce kontrakcji** daje najlepszy win% w IT3 (49.0%)
   przy N=525 — warto trzymać ledwie zauważalną tolerancję na rozszerzanie.
3. **Chase 10 i range 16 są neutralne** (score ±0.01 vs rodzic) — nie warto ich ruszać.
4. **Trend house (vcpDry80Tt3) wygląda świetnie na PL (0.47), ale zabija US (0.13)** —
   klasyczny przykład przeuczenia na jednym rynku; odrzucony.
5. **House stop konsekwentnie psuje wynik** (US 0.05) — model stopu strukturalnego zostaje.
6. **C1 (1 kontrakcja) skaluje się najlepiej**: `vcpC1Oh10` daje N=3768 przy score 0.20,
   czyli 3× więcej sygnałów niż C3 za ~0.04 score.
7. **Plateau wokół C3 jest płaski** (0.22–0.26 dla większości mutacji) — parametr jest
   stabilny, nie jest to pojedynczy optimum.

---

## IT4 — zacieśnianie `vcpLooseC1` (40 wariantów, cel N > 2200)

Rodzic: `vcpLooseC1` z IT2/IT3 (1 kontrakcja, luźna baza, N=3968, score 0.18).
Każdy wiersz zmienia **jeden** parametr o mały krok (nigdy w stronę luźniejszą),
plus 6 kombinacji dwuparametrowych i 1 potrójna.

Scrape: PL 434/434, US 802/802.

### Wyniki (PL+US, N > 2200, posortowane po score)

| Wariant | PL N / score | US N / score | ALL N | win% | avgR | PF | score |
|---|---:|---:|---:|---:|---:|---:|---:|
| **vcpC1Rng16** (zakres ≤16) | 521 / 0.23 | 3239 / 0.20 | **3760** | 45.9 | 0.23 | 1.49 | **0.21** |
| **vcpC1Vol105Dry90** (vol 1.05 + VDU 0.90) | 408 / 0.22 | 2162 / 0.20 | **2570** | 44.9 | **0.26** | **1.54** | **0.21** |
| vcpC1Oh10R105 (overhead 10 + ratio 1.05) | 481 / 0.26 | 3067 / 0.19 | 3548 | 46.1 | 0.24 | 1.51 | 0.21 |
| vcpC1Dry90 (VDU 0.90) | 431 / 0.24 | 2446 / 0.19 | 2877 | 44.9 | 0.25 | 1.51 | 0.20 |
| vcpC1Chase10 | 524 / 0.21 | 3292 / 0.20 | 3816 | 45.4 | 0.23 | 1.48 | 0.20 |
| vcpC1Atr10 (ATR ≤1.0) | 376 / 0.18 | 2438 / **0.21** | 2814 | 45.7 | 0.24 | 1.51 | 0.20 |
| vcpC1Oh5Dry90R105 | 325 / **0.32** | 1911 / 0.17 | 2236 | 45.8 | 0.25 | 1.53 | 0.20 |
| vcpC1Oh10 | 495 / 0.23 | 3182 / 0.19 | 3677 | 45.8 | 0.23 | 1.49 | 0.19 |
| vcpC1Oh10Dry90 | 399 / 0.29 | 2323 / 0.17 | 2722 | 45.1 | 0.25 | 1.51 | 0.19 |
| **vcpC1ref (rodzic)** | 532 / 0.19 | 3340 / 0.18 | 3872 | 45.3 | 0.23 | 1.48 | 0.18 |

Poza progiem N>2200 (ale wartościowe): `vcpC1Oh3` (2712, 0.17), `vcpC1Dry85` (2357, 0.16),
`vcpC1Tt2` (3615, 0.15), `vcpC1Reg1` (2627, 0.10), `vcpC1Rs70` (2867, 0.09 — RS percentyl
psuje US tak samo jak w IT3).

### Wnioski IT4

1. **Plateau C1 leży na score ≈ 0.20–0.21.** Najlepsze zacieśnienia podnoszą score tylko
   o +0.02–0.03 względem rodzica (0.18). Nie ma tu drugiego progu jakości — trzeba
   przejść do innej rodziny (C3 + overhead), żeby dostać 0.3+.
2. **`vcpC1Rng16` to najlepszy „ilościowy” kompromis:** N=3760 (niemal tyle co rodzic),
   score 0.21, i **równo na obu rynkach** (PL 0.23 / US 0.20). Ciasny zakres 10 dni ≤16%
   jest lepszy od domyślnego 20%.
3. **`vcpC1Vol105Dry90` ma najlepszą jakość na jednostkę sygnału w tej rodzinie:**
   N=2570, avgR 0.26, PF 1.54 — ale N spada poniżej 2600.
4. **Kombinacje nie sumują się liniowo:** potrójne zacieśnienie (Oh5+Dry90+R105) daje
   PL 0.32, ale US 0.17 — czyli poprawia tylko rynek, który i tak był lepszy.
5. **US jest sufitem:** żadne zacieśnienie nie podniosło US powyżej 0.21. To ogranicza
   sens dalszego tuningu C1 — kolejne kroki to zmiana definicji sygnału, nie parametrów.
6. **Zacieśnienia, które nie działają:** prior 10/20 (0.16–0.18), trend pełny (0.15),
   margin 0.25 (0.15), volume 1.1 (0.14), regime 1 (0.10), RS70 (0.09).

---

## Front jakość/ilość (pooled, wszystkie iteracje)

| Klasa | Przykład | N | score | PF | win% |
|---|---|---:|---:|---:|---:|
| Kanoniczna (dokument) | vcpCanon | 0 | – | – | – |
| Wysoka jakość, mała próbka | vcpCfmDry65 | 70 | 0.60 | 2.23 | 50.0 |
| **Best balance (N≥100)** | **vcpCfmOh3** | **117** | **0.51** | **2.06** | **50.4** |
| **Best cross-market (N≥500)** | **vcpDry80Oh5** | **556** | **0.32** | **1.68** | **46.6** |
| Best at N≥2200 (C1 family) | vcpC1Rng16 | 3760 | 0.21 | 1.49 | 45.9 |
| Best balance (N≥500) | vcpLooseC3 | 654 | 0.24 | 1.49 | 46.2 |
| Duża próbka | vcpLooseDry80 | 972 | 0.20 | 1.49 | 43.4 |
| Bardzo duża próbka | vcpLooseC1 | 3968 | 0.18 | 1.48 | 45.4 |
| Czysty zakres (bez VCP) | vcpRange | 8746 | −0.13 | 1.51 | 35.3 |

## Rekomendacja

- **Jakość + akceptowalna liczność (domyślna):** `vcpCfmOh3` — potwierdzenie 2-dniowe,
  overhead ≤3%, baza 2 kontrakcje, final ≤12%, VDU ≤0.80, volume ≥1.2×, trend light.
  N≈117 pooled (≈0.1/symbol), score 0.51, PF 2.06.
- **Skala / skanowanie szerokie (rekomendacja IT3):** `vcpDry80Oh5` — luźna baza + VDU 0.80
  + overhead ≤5%, N≈556, score 0.32, PL 0.36 / US 0.31; alternatywnie `vcpC3R105` (N≈525, 0.26)
  lub `vcpC1Oh10` (N≈3768, 0.20) dla maksymalnej liczby sygnałów.
- **Kanoniczna wersja z dokumentu** pozostaje w wskaźniku jako wiersz referencyjny,
  ale nie jest użyteczna operacyjnie (N=0) — dokumentowa bramka ATR jest niespełnialna
  na dziennych danych.

## Zasady powtarzania

```bash
python3 scripts/tv_table_scraper.py --watchlist watchlist/.PL.txt --outdir analysis \
  --tag PL_VCP_itN --indicator "Minervini VCP (perf sweep)" --resolution D \
  --timeout 20 --settle 0.6
python3 scripts/tv_table_scraper.py --watchlist watchlist/.US.txt --outdir analysis \
  --tag US_VCP_itN --indicator "Minervini VCP (perf sweep)" --resolution D \
  --timeout 20 --settle 0.6
python3 scripts/summarize_signals.py --out analysis/PL_VCP_itN_SUMMARY.csv analysis/PL_VCP_itN_<data>.csv
python3 scripts/summarize_signals.py --out analysis/US_VCP_itN_SUMMARY.csv analysis/US_VCP_itN_<data>.csv
python3 scripts/summarize_signals.py --out analysis/VCP_itN_SUMMARY_ALL.csv analysis/PL_VCP_itN_<data>.csv analysis/US_VCP_itN_<data>.csv
```
