# ETSB-ia — finalny zestaw sygnałów (po IT29)

**Data:** 2026-10-18 · **runy:** GPW_NC_IT29 / US_BIG_IT29 · **22 sygnały**

Wszystkie 22 sygnały spełniają minimum **120 wystąpień GPW_NC** i **240 US_BIG**.
Zestaw wybrany per rodzina: 1 wersja bazowa lub 2 wersje o istotnie różnych parametrach.

| rodzina | sygnał | GPW n | GPW win% | GPW avgR | GPW PF | US n | US win% | US avgR | US PF |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| ET (early trend) | `ai-et3` | 194 | 24.2 | 0.325 | 1.44 | 563 | 26.3 | 1.283 | 2.75 |
| ET (early trend) | `ai-et4` | 183 | 26.8 | 2.26 | 4.1 | 1498 | 20.6 | 0.592 | 1.75 |
| ETC (trend + contraction) | `ai-etc1` | 133 | 25.6 | 1.709 | 3.29 | 670 | 24.3 | 0.993 | 2.31 |
| ETC (trend + contraction) | `ai-etc3` | 131 | 29.0 | 1.946 | 3.76 | 597 | 25.8 | 0.892 | 2.2 |
| RMV (range expansion) | `ai-rmv1` | 567 | 23.1 | 1.564 | 3.07 | 4187 | 22.5 | 0.762 | 1.99 |
| RMV (range expansion) | `ai-rmv3` | 251 | 20.3 | 2.51 | 4.18 | 2022 | 18.9 | 0.37 | 1.46 |
| MTSB (trend + strong breakout) | `ai-mtsb` | 255 | 25.5 | 1.892 | 3.55 | 1943 | 21.6 | 0.915 | 2.17 |
| MTSB (ADR-clearance variant) | `ai-mtsbv2c` | 146 | 26.7 | 1.702 | 3.34 | 607 | 26.2 | 1.073 | 2.47 |
| MTC (trend + contraction) | `ai-mtc1` | 218 | 30.3 | 1.832 | 3.66 | 943 | 26.4 | 0.983 | 2.35 |
| MTC (trend + contraction) | `ai-mtc3` | 199 | 29.7 | 1.506 | 3.18 | 892 | 28.1 | 0.894 | 2.26 |
| OBV divergence | `ai-obvdiv` | 179 | 24.6 | 0.64 | 1.88 | 595 | 22.9 | 0.536 | 1.7 |
| VCP (Minervini) | `ai-vcp2` | 310 | 32.6 | 1.519 | 3.41 | 258 | 36.8 | 0.242 | 1.41 |
| HTF (Qullamaggie) | `ai-htf` | 142 | 35.9 | 0.387 | 1.63 | 522 | 35.8 | 0.376 | 1.61 |
| HTF tight (Qullamaggie) | `ai-htftight` | 130 | 33.8 | 0.308 | 1.48 | 480 | 35.6 | 0.347 | 1.56 |
| EP light (Qullamaggie) | `ai-epu` | 293 | 33.2 | 0.263 | 1.44 | 458 | 51.1 | 0.318 | 1.77 |
| Runaway gap pullback | `ai-ragpb` | 442 | 18.6 | 1.131 | 2.43 | 1072 | 22.9 | 0.307 | 1.41 |
| WON hybrid | `ai-wonhp` | 665 | 37.3 | 0.779 | 2.32 | 1804 | 35.1 | 0.458 | 1.74 |
| WON turnaround | `ai-wonturn` | 153 | 22.2 | 0.551 | 1.73 | 1024 | 23.3 | 0.564 | 1.75 |
| VWAP reclaim | `ai-vwaptag` | 138 | 27.5 | 1.178 | 2.65 | 344 | 21.5 | 1.116 | 2.44 |
| Capitulation low | `ai-caplow` | 144 | 26.4 | 0.206 | 1.29 | 636 | 21.5 | 0.227 | 1.29 |
| Flat base | `ai-flatb` | 328 | 42.1 | 1.012 | 2.88 | 674 | 38.0 | 0.422 | 1.74 |
| Volume institutional push | `ai-vip` | 206 | 32.5 | 0.999 | 2.65 | 778 | 25.3 | 0.203 | 1.28 |

## Wybór wersji per rodzina
- **ET:** `et3` (score 3, szerszy) + `et4` (score 4, ostrzejszy).
- **ETC:** `etc1` + `etc3` (krótki i długi horyzont kontrakcji).
- **RMV:** `rmv1` + `rmv3` (krótki i długi horyzont ekspansji).
- **MTSB:** `mtsb` (strongBreakout) + `mtsbv2c` (wymóg clearancu 1,0 ADR — inna populacja wybić).
- **MTC:** `mtc1` + `mtc3` (krótki i długi horyzont).
- **HTF:** `htf` (baza) + `htftight` (ciaśniejsza flaga).
- **EP:** `epu` (lekkie filtry Qullamaggiego; `ep`/`epq` poza tabelą).
- **Pojedyncze:** `obvdiv`, `vcp2`, `ragpb`, `wonhp`, `wonturn`, `vwaptag`, `caplow`, `flatb`, `vip`.

## Poza aktywną tabelą (kod/archiwum/historia w DB)
- poniżej minimum: `ep`, `ep20`, `ep20u`, `htf100`, `vcp3`, `vcp3c`, `epq`;
- redundantne/warianty q: `et1yh`, `etc2`, `rmv2`, `mtc2`, `mtsbv2a`, `mtsbv2b`, `mtsbv2d`, `mtsbv2e`, `mtsbq`, `mtc3q`, `et4q`, `obvq`, `vcp2c`.

## Qullamaggie — co zastosowano
- EP light: gap 8%, volume 2,5×, rosnące RS; bez trendu 10/50 i higher lows (te zabijały próbkę).
- HTF: reguły flagi/VDU/10>20/higher lows testowane w IT27 — odrzucone (spadek próbki i jakości); został wariant IT26.
- Pełny strict EP (`epq`) i wierny HTF nie spełniają minimumów; pozostają jako research/archiwum.
- Wyjścia/partiale/trailing/LOD są zamrożone — dokument Qullamaggiego służy jako benchmark jakości, nie do zmiany SL/checkTime.

## Pliki
- kod: `src/indicators/ETSB-ia.pine` (IT29)
- archiwum: `variants/ETSB-ia_it29.pine`
- baza: `db/analysis.db` (runy IT29)
- CSV: `analysis/FINAL_SELECTION.csv`
