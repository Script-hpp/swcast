# Training Report (swcast-kp-baseline-v0)

Erzeugt von `src/swcast/training/generate_report.py` aus `models/swcast-kp-baseline-v0/model_artifacts.json` (Datensatz-SHA-256 `a14ed83cae82d3da72a03cd93ac79b482443baa0537961aecfac8ee7b4f24150`, Trainings-Commit `c9b7382ac3896ef46237d69b926e021af40f9b60`).

## Implementierungsentscheidungen

- Solver: `lbfgs` für LogisticRegression, `svd` für Ridge (deterministisch).
- CV-Split nach `target_date`; BSS in der CV gegen das Merkmal `climatology` (Sturmtag-Rate der 365 Tage bis D−1).
- Platt-Skalierung der SWPC-Proxys: `LogisticRegression(penalty=None)` auf logit(clip(p, 0.005, 0.995)).
- Out-of-sample-Vorhersagen: Hauptmodell, wenn der simulierte Lauf gültige L1-Daten hatte (60/120-Regel), sonst Rückfallmodell – wie im Live-Betrieb.

## Vorlauftag +1

Läufe mit gültigem L1 (Hauptmodell): 7175 / 7669 (93.6%)

#### p_storm – Hauptmodell

- Gewählter Parameter (C): 0.1
- Intercept: -3.0056
- Koeffizienten (standardisierte Merkmale):
  - `persistence`: +0.3244
  - `recurrence`: +0.3360
  - `climatology`: +0.2187
  - `l1_bz_gsm`: +0.2138
  - `l1_by_gsm`: +0.0637
  - `l1_speed`: -0.4156
  - `l1_dyn_pressure`: +0.4745
  - `l1_newell`: +0.7734

| Validierungsjahr | Brier | BSS vs. Klimatologie |
| --- | --- | --- |
| 2015 | 0.1067 | 0.2366 |
| 2016 | 0.0915 | 0.1460 |
| 2017 | 0.0766 | 0.2153 |
| 2018 | 0.0344 | 0.0964 |
| 2019 | 0.0306 | 0.1143 |
| 2020 | 0.0076 | 0.1673 |
| 2021 | 0.0482 | 0.0154 |
| 2022 | 0.0888 | 0.0405 |
| 2023 | 0.0811 | 0.2427 |
| 2024 | 0.0738 | 0.2260 |
| 2025 | 0.1053 | 0.2830 |
| **Mittel** | 0.0677 | 0.1621 |

#### p_storm – Rückfallmodell

- Gewählter Parameter (C): 10
- Intercept: -2.8491
- Koeffizienten (standardisierte Merkmale):
  - `persistence`: +0.6186
  - `recurrence`: +0.3616
  - `climatology`: +0.2311

| Validierungsjahr | Brier | BSS vs. Klimatologie |
| --- | --- | --- |
| 2015 | 0.1246 | 0.0779 |
| 2016 | 0.0950 | 0.0903 |
| 2017 | 0.0841 | 0.0835 |
| 2018 | 0.0341 | 0.0613 |
| 2019 | 0.0306 | 0.0417 |
| 2020 | 0.0077 | 0.0912 |
| 2021 | 0.0437 | 0.0297 |
| 2022 | 0.0867 | 0.0395 |
| 2023 | 0.0947 | 0.0579 |
| 2024 | 0.0836 | 0.0619 |
| 2025 | 0.1286 | 0.1000 |
| **Mittel** | 0.0739 | 0.0668 |

#### kp_max – Hauptmodell

- Gewählter Parameter (alpha): 10
- Intercept: 2.7903
- Koeffizienten (standardisierte Merkmale):
  - `persistence`: +0.2242
  - `recurrence`: +0.2113
  - `climatology`: +0.1154
  - `l1_bz_gsm`: +0.1814
  - `l1_by_gsm`: +0.0473
  - `l1_speed`: -0.0100
  - `l1_dyn_pressure`: +0.3281
  - `l1_newell`: +0.5001

| Validierungsjahr | RMSE |
| --- | --- |
| 2015 | 1.1672 |
| 2016 | 1.0970 |
| 2017 | 1.1105 |
| 2018 | 1.0222 |
| 2019 | 0.8908 |
| 2020 | 0.8770 |
| 2021 | 1.0692 |
| 2022 | 1.1236 |
| 2023 | 1.1356 |
| 2024 | 1.3228 |
| 2025 | 1.0741 |
| **Mittel** | 1.0809 |

#### kp_max – Rückfallmodell

- Gewählter Parameter (alpha): 0.01
- Intercept: 2.7723
- Koeffizienten (standardisierte Merkmale):
  - `persistence`: +0.5282
  - `recurrence`: +0.2545
  - `climatology`: +0.1422

| Validierungsjahr | RMSE |
| --- | --- |
| 2015 | 1.2658 |
| 2016 | 1.1798 |
| 2017 | 1.2157 |
| 2018 | 1.0752 |
| 2019 | 0.9826 |
| 2020 | 0.9044 |
| 2021 | 1.1445 |
| 2022 | 1.1866 |
| 2023 | 1.2696 |
| 2024 | 1.3387 |
| 2025 | 1.2399 |
| **Mittel** | 1.1639 |

#### Reliability p_storm (out-of-sample 2015–2025, n = 4018)

| Bin | mittlere Vorhersage | beobachtete Rate | n |
| --- | --- | --- | --- |
| [0.0, 0.1) | 0.042 | 0.045 | 3068 |
| [0.1, 0.2) | 0.139 | 0.092 | 553 |
| [0.2, 0.3) | 0.242 | 0.270 | 163 |
| [0.3, 0.4) | 0.344 | 0.412 | 85 |
| [0.4, 0.5) | 0.458 | 0.442 | 43 |
| [0.5, 0.6) | 0.555 | 0.448 | 29 |
| [0.6, 0.7) | 0.640 | 0.552 | 29 |
| [0.7, 0.8) | 0.747 | 0.765 | 17 |
| [0.8, 0.9) | 0.849 | 0.867 | 15 |
| [0.9, 1.0) | 0.959 | 0.938 | 16 |

## Vorlauftag +2

Läufe mit gültigem L1 (Hauptmodell): 7174 / 7668 (93.6%)

#### p_storm – Hauptmodell

- Gewählter Parameter (C): 0.1
- Intercept: -2.7218
- Koeffizienten (standardisierte Merkmale):
  - `persistence`: +0.1364
  - `recurrence`: +0.4077
  - `climatology`: +0.3576
  - `l1_bz_gsm`: -0.0442
  - `l1_by_gsm`: +0.0190
  - `l1_speed`: -0.3726
  - `l1_dyn_pressure`: +0.1489
  - `l1_newell`: +0.1178

| Validierungsjahr | Brier | BSS vs. Klimatologie |
| --- | --- | --- |
| 2015 | 0.1304 | 0.0328 |
| 2016 | 0.0987 | 0.0617 |
| 2017 | 0.0891 | 0.0433 |
| 2018 | 0.0368 | 0.0343 |
| 2019 | 0.0341 | 0.0109 |
| 2020 | 0.0093 | -0.0204 |
| 2021 | 0.0450 | 0.0255 |
| 2022 | 0.0911 | 0.0160 |
| 2023 | 0.0974 | 0.0236 |
| 2024 | 0.0972 | 0.0056 |
| 2025 | 0.1359 | 0.0475 |
| **Mittel** | 0.0786 | 0.0255 |

#### p_storm – Rückfallmodell

- Gewählter Parameter (C): 10
- Intercept: -2.6845
- Koeffizienten (standardisierte Merkmale):
  - `persistence`: +0.0223
  - `recurrence`: +0.4406
  - `climatology`: +0.3489

| Validierungsjahr | Brier | BSS vs. Klimatologie |
| --- | --- | --- |
| 2015 | 0.1338 | 0.0098 |
| 2016 | 0.0981 | 0.0610 |
| 2017 | 0.0890 | 0.0311 |
| 2018 | 0.0354 | 0.0258 |
| 2019 | 0.0312 | 0.0253 |
| 2020 | 0.0085 | 0.0005 |
| 2021 | 0.0440 | 0.0224 |
| 2022 | 0.0883 | 0.0216 |
| 2023 | 0.1006 | -0.0008 |
| 2024 | 0.0895 | -0.0052 |
| 2025 | 0.1416 | 0.0090 |
| **Mittel** | 0.0782 | 0.0182 |

#### kp_max – Hauptmodell

- Gewählter Parameter (alpha): 10
- Intercept: 2.7774
- Koeffizienten (standardisierte Merkmale):
  - `persistence`: +0.1180
  - `recurrence`: +0.3252
  - `climatology`: +0.1954
  - `l1_bz_gsm`: +0.1198
  - `l1_by_gsm`: +0.0177
  - `l1_speed`: -0.1094
  - `l1_dyn_pressure`: +0.1176
  - `l1_newell`: +0.2422

| Validierungsjahr | RMSE |
| --- | --- |
| 2015 | 1.3927 |
| 2016 | 1.2358 |
| 2017 | 1.3054 |
| 2018 | 1.1765 |
| 2019 | 1.0254 |
| 2020 | 0.9861 |
| 2021 | 1.2146 |
| 2022 | 1.2567 |
| 2023 | 1.3687 |
| 2024 | 1.4246 |
| 2025 | 1.3189 |
| **Mittel** | 1.2459 |

#### kp_max – Rückfallmodell

- Gewählter Parameter (alpha): 0.01
- Intercept: 2.7719
- Koeffizienten (standardisierte Merkmale):
  - `persistence`: +0.1778
  - `recurrence`: +0.3425
  - `climatology`: +0.2084

| Validierungsjahr | RMSE |
| --- | --- |
| 2015 | 1.4157 |
| 2016 | 1.2702 |
| 2017 | 1.2968 |
| 2018 | 1.1634 |
| 2019 | 1.0257 |
| 2020 | 0.9812 |
| 2021 | 1.2154 |
| 2022 | 1.2485 |
| 2023 | 1.3896 |
| 2024 | 1.4321 |
| 2025 | 1.3632 |
| **Mittel** | 1.2547 |

#### Reliability p_storm (out-of-sample 2015–2025, n = 4018)

| Bin | mittlere Vorhersage | beobachtete Rate | n |
| --- | --- | --- | --- |
| [0.0, 0.1) | 0.055 | 0.059 | 2916 |
| [0.1, 0.2) | 0.135 | 0.147 | 902 |
| [0.2, 0.3) | 0.237 | 0.229 | 153 |
| [0.3, 0.4) | 0.336 | 0.389 | 36 |
| [0.4, 0.5) | 0.441 | 0.167 | 6 |
| [0.5, 0.6) | 0.534 | 0.500 | 2 |
| [0.7, 0.8) | 0.720 | 0.000 | 1 |
| [0.8, 0.9) | 0.852 | 0.500 | 2 |

## Vorlauftag +3

Läufe mit gültigem L1 (Hauptmodell): 7174 / 7667 (93.6%)

#### p_storm – Hauptmodell

- Gewählter Parameter (C): 10
- Intercept: -2.6986
- Koeffizienten (standardisierte Merkmale):
  - `persistence`: +0.1742
  - `recurrence`: +0.4059
  - `climatology`: +0.3668
  - `l1_bz_gsm`: +0.0103
  - `l1_by_gsm`: +0.0621
  - `l1_speed`: -0.2798
  - `l1_dyn_pressure`: +0.0086
  - `l1_newell`: +0.0145

| Validierungsjahr | Brier | BSS vs. Klimatologie |
| --- | --- | --- |
| 2015 | 0.1316 | 0.0082 |
| 2016 | 0.1029 | 0.0602 |
| 2017 | 0.0871 | 0.0406 |
| 2018 | 0.0369 | 0.0295 |
| 2019 | 0.0337 | 0.0241 |
| 2020 | 0.0068 | -0.0866 |
| 2021 | 0.0397 | 0.0183 |
| 2022 | 0.0906 | 0.0188 |
| 2023 | 0.1012 | -0.0125 |
| 2024 | 0.0909 | -0.0066 |
| 2025 | 0.1391 | 0.0250 |
| **Mittel** | 0.0782 | 0.0108 |

#### p_storm – Rückfallmodell

- Gewählter Parameter (C): 10
- Intercept: -2.6838
- Koeffizienten (standardisierte Merkmale):
  - `persistence`: +0.0142
  - `recurrence`: +0.4419
  - `climatology`: +0.3495

| Validierungsjahr | Brier | BSS vs. Klimatologie |
| --- | --- | --- |
| 2015 | 0.1335 | 0.0122 |
| 2016 | 0.0982 | 0.0609 |
| 2017 | 0.0890 | 0.0311 |
| 2018 | 0.0354 | 0.0260 |
| 2019 | 0.0312 | 0.0256 |
| 2020 | 0.0085 | 0.0005 |
| 2021 | 0.0440 | 0.0225 |
| 2022 | 0.0883 | 0.0212 |
| 2023 | 0.1005 | -0.0006 |
| 2024 | 0.0897 | -0.0064 |
| 2025 | 0.1417 | 0.0089 |
| **Mittel** | 0.0782 | 0.0184 |

#### kp_max – Hauptmodell

- Gewählter Parameter (alpha): 10
- Intercept: 2.7723
- Koeffizienten (standardisierte Merkmale):
  - `persistence`: +0.1014
  - `recurrence`: +0.3481
  - `climatology`: +0.2243
  - `l1_bz_gsm`: +0.0599
  - `l1_by_gsm`: +0.0039
  - `l1_speed`: -0.1049
  - `l1_dyn_pressure`: +0.0400
  - `l1_newell`: +0.0901

| Validierungsjahr | RMSE |
| --- | --- |
| 2015 | 1.4463 |
| 2016 | 1.2667 |
| 2017 | 1.2968 |
| 2018 | 1.1792 |
| 2019 | 1.0314 |
| 2020 | 0.9867 |
| 2021 | 1.2133 |
| 2022 | 1.2750 |
| 2023 | 1.3897 |
| 2024 | 1.4292 |
| 2025 | 1.3395 |
| **Mittel** | 1.2594 |

#### kp_max – Rückfallmodell

- Gewählter Parameter (alpha): 0.01
- Intercept: 2.7717
- Koeffizienten (standardisierte Merkmale):
  - `persistence`: +0.0843
  - `recurrence`: +0.3590
  - `climatology`: +0.2269

| Validierungsjahr | RMSE |
| --- | --- |
| 2015 | 1.4445 |
| 2016 | 1.2707 |
| 2017 | 1.3081 |
| 2018 | 1.1721 |
| 2019 | 1.0301 |
| 2020 | 0.9996 |
| 2021 | 1.2214 |
| 2022 | 1.2628 |
| 2023 | 1.3950 |
| 2024 | 1.4429 |
| 2025 | 1.3761 |
| **Mittel** | 1.2657 |

#### Reliability p_storm (out-of-sample 2015–2025, n = 4018)

| Bin | mittlere Vorhersage | beobachtete Rate | n |
| --- | --- | --- | --- |
| [0.0, 0.1) | 0.056 | 0.064 | 2958 |
| [0.1, 0.2) | 0.134 | 0.143 | 939 |
| [0.2, 0.3) | 0.235 | 0.275 | 102 |
| [0.3, 0.4) | 0.340 | 0.250 | 16 |
| [0.4, 0.5) | 0.428 | 0.333 | 3 |

## Historischer Vorab-Vergleich mit SWPC (2015–2025)

> **Nur beschreibend, zählt nicht für das Erfolgskriterium.** Gepaarte Out-of-Sample-Vorhersagen von swcast gegen SWPC (Middle-Latitude-Proxy, roh und rekalibriert) auf denselben Zieltagen. Referenz beider BSS: rollierende 365-Tage-Klimatologie (PREREGISTRATION §4). ΔBSS = BSS(swcast) − BSS(SWPC), 95-%-KI per Block-Bootstrap (27-Tage-Blöcke, 10000 Resamples, Seed 2026, Perzentilmethode). Die SWPC-Rekalibrierung ist hier in-sample über 2010–2025 gefittet, was SWPC begünstigt.

| Tag | n | BSS swcast | BSS SWPC roh | BSS SWPC rekal. | ΔBSS vs. roh [95-%-KI] | ΔBSS vs. rekal. [95-%-KI] | Einordnung (vs. Referenzvariante) |
| --- | --- | --- | --- | --- | --- | --- | --- |
| +1 | 3982 | 0.1853 | 0.0938 | 0.1288 | +0.0916 [+0.0446, +0.1449] | +0.0566 [+0.0167, +0.0999] | Übertreffen (rekal.) |
| +2 | 3982 | 0.0334 | 0.0624 | 0.0893 | -0.0290 [-0.0721, +0.0159] | -0.0558 [-0.0868, -0.0248] | nicht erreicht (rekal.) |
| +3 | 3982 | 0.0213 | 0.0507 | 0.0625 | -0.0294 [-0.0661, +0.0100] | -0.0412 [-0.0671, -0.0138] | nicht erreicht (rekal.) |

Referenzvariante je Tag nach PREREGISTRATION §8: die SWPC-Variante mit dem besseren historischen BSS (siehe `swpc_recalibration` in den Artefakten).
