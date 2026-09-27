# swcast-kp-baseline-v0 – Live-Status

**Vorläufig – maßgeblich erst bei N = 365 Tagen (PREREGISTRATION §5).**

Noch keine gültige Vorhersage seit Live-Start (kein `forecasts/START.md`).

| Vorlauftag | n (gepaart) | SWPC fehlt | GFZ-Lücke | BSS swcast | BSS SWPC | ΔBSS [95%-KI] | Einordnung |
| --- | --- | --- | --- | --- | --- | --- | --- |
| +1 | 0 | 1 | 1 | nan | nan | +nan [+nan, +nan] | nicht erreicht |
| +2 | 0 | 1 | 1 | nan | nan | +nan [+nan, +nan] | nicht erreicht |
| +3 | 0 | 1 | 1 | nan | nan | +nan [+nan, +nan] | nicht erreicht |

## Eingangsdrift (nur beschreibend, kein Erfolgskriterium)

Mittelwert der Tag+1-Hauptmodell-Merkmale über alle Live-Läufe mit gültigem L1 gegen `scaler_mean`/`scaler_scale` aus dem Training (PREREGISTRATION §9: rein beobachtend, ändert `swcast-kp-baseline-v0` nicht). Großes |z| kann z. B. auf eine anders kalibrierte aktive rtsw-Sonde hindeuten (siehe `l1_source` je Lauf).

| Merkmal | n | Mittelwert live | scaler_mean | scaler_scale | z |
| --- | --- | --- | --- | --- | --- |
| `persistence` | 1 | 4.3330 | 2.7849 | 1.3618 | +1.1368 |
| `recurrence` | 1 | 2.3330 | 2.7779 | 1.3658 | -0.3258 |
| `climatology` | 1 | 0.1589 | 0.0737 | 0.0407 | +2.0954 |
| `l1_bz_gsm` | 1 | -1.5804 | -0.0376 | 2.6466 | -0.5829 |
| `l1_by_gsm` | 1 | 1.5146 | -0.0680 | 3.4846 | +0.4542 |
| `l1_speed` | 1 | 398.5018 | 423.6772 | 98.2150 | -0.2563 |
| `l1_dyn_pressure` | 1 | 232562.9987 | 1027266.9654 | 815463.5142 | -0.9745 |
| `l1_newell` | 1 | 4054.7884 | 3585.9968 | 3161.7895 | +0.1483 |
