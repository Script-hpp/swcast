# Training Report (swcast-kp-baseline-v0)

## Implementierungsentscheidungen

- **Solver**: `lbfgs` für LogisticRegression, `svd` für Ridge (beide deterministisch, `random_state=42`).
- **BSS Klimatologie-Referenz**: In der CV wird der BSS mit dem `climatology`-Feature (Rate der letzten 365 Tage) als Referenz auf dem Validierungsjahr berechnet.
- **Platt-Skalierung**: `LogisticRegression(penalty=None, solver='lbfgs')` ohne Regularisierung auf den Intervallen $[0.005, 0.995]$.


## Vorlauftag +1

Anteil der Läufe mit gültigem L1 (Hauptmodell): 7175 / 7669 (93.6%)

### p_storm (Hauptmodell)
- Gewähltes C: 0.1
- **CV per Fold (Brier | BSS vs Clim)**:
  - 2015: 0.1067 | 0.2366
  - 2016: 0.0915 | 0.1460
  - 2017: 0.0766 | 0.2153
  - 2018: 0.0344 | 0.0964
  - 2019: 0.0306 | 0.1143
  - 2020: 0.0076 | 0.1673
  - 2021: 0.0482 | 0.0154
  - 2022: 0.0888 | 0.0405
  - 2023: 0.0811 | 0.2427
  - 2024: 0.0738 | 0.2260
  - 2025: 0.1053 | 0.2830
- Mean: Brier 0.0677, BSS 0.1621

### kp_max (Hauptmodell)
- Gewähltes alpha: 10
- **CV per Fold (RMSE)**:
  - 2015: 1.1672
  - 2016: 1.0970
  - 2017: 1.1105
  - 2018: 1.0222
  - 2019: 0.8908
  - 2020: 0.8770
  - 2021: 1.0692
  - 2022: 1.1236
  - 2023: 1.1356
  - 2024: 1.3228
  - 2025: 1.0741
- Mean RMSE: 1.0809

## Vorlauftag +2

Anteil der Läufe mit gültigem L1 (Hauptmodell): 7174 / 7668 (93.6%)

### p_storm (Hauptmodell)
- Gewähltes C: 0.1
- **CV per Fold (Brier | BSS vs Clim)**:
  - 2015: 0.1304 | 0.0328
  - 2016: 0.0987 | 0.0617
  - 2017: 0.0891 | 0.0433
  - 2018: 0.0368 | 0.0343
  - 2019: 0.0341 | 0.0109
  - 2020: 0.0093 | -0.0204
  - 2021: 0.0450 | 0.0255
  - 2022: 0.0911 | 0.0160
  - 2023: 0.0974 | 0.0236
  - 2024: 0.0972 | 0.0056
  - 2025: 0.1359 | 0.0475
- Mean: Brier 0.0786, BSS 0.0255

### kp_max (Hauptmodell)
- Gewähltes alpha: 10
- **CV per Fold (RMSE)**:
  - 2015: 1.3927
  - 2016: 1.2358
  - 2017: 1.3054
  - 2018: 1.1765
  - 2019: 1.0254
  - 2020: 0.9861
  - 2021: 1.2146
  - 2022: 1.2567
  - 2023: 1.3687
  - 2024: 1.4246
  - 2025: 1.3189
- Mean RMSE: 1.2459

## Vorlauftag +3

Anteil der Läufe mit gültigem L1 (Hauptmodell): 7174 / 7667 (93.6%)

### p_storm (Hauptmodell)
- Gewähltes C: 10
- **CV per Fold (Brier | BSS vs Clim)**:
  - 2015: 0.1316 | 0.0082
  - 2016: 0.1029 | 0.0602
  - 2017: 0.0871 | 0.0406
  - 2018: 0.0369 | 0.0295
  - 2019: 0.0337 | 0.0241
  - 2020: 0.0068 | -0.0866
  - 2021: 0.0397 | 0.0183
  - 2022: 0.0906 | 0.0188
  - 2023: 0.1012 | -0.0125
  - 2024: 0.0909 | -0.0066
  - 2025: 0.1391 | 0.0250
- Mean: Brier 0.0782, BSS 0.0108

### kp_max (Hauptmodell)
- Gewähltes alpha: 10
- **CV per Fold (RMSE)**:
  - 2015: 1.4463
  - 2016: 1.2667
  - 2017: 1.2968
  - 2018: 1.1792
  - 2019: 1.0314
  - 2020: 0.9867
  - 2021: 1.2133
  - 2022: 1.2750
  - 2023: 1.3897
  - 2024: 1.4292
  - 2025: 1.3395
- Mean RMSE: 1.2594

## SWPC Rekalibrierung (2010-2025)

**Tag +1**: Nutze Rekalibriert.
BSS roh: 0.0902, BSS rekalibriert: 0.1234

**Tag +2**: Nutze Rekalibriert.
BSS roh: 0.0641, BSS rekalibriert: 0.0908

**Tag +3**: Nutze Rekalibriert.
BSS roh: 0.0564, BSS rekalibriert: 0.0677
