# swcast-kp-baseline-v0 – Live-Status

**Vorläufig – maßgeblich erst bei N = 365 Tagen (PREREGISTRATION §5).**

Noch keine gültige Vorhersage seit Live-Start (kein `forecasts/START.md`).

| Vorlauftag | n (gepaart) | SWPC fehlt | GFZ-Lücke | BSS swcast | BSS SWPC | ΔBSS [95%-KI] | Einordnung |
| --- | --- | --- | --- | --- | --- | --- | --- |
| +1 | 0 | 0 | 0 | nan | nan | +nan [+nan, +nan] | zu wenig Daten |
| +2 | 0 | 0 | 0 | nan | nan | +nan [+nan, +nan] | zu wenig Daten |
| +3 | 0 | 0 | 0 | nan | nan | +nan [+nan, +nan] | zu wenig Daten |

## Eingangsdrift (nur beschreibend, kein Erfolgskriterium)

Mittelwert der Tag+1-Hauptmodell-Merkmale über alle Live-Läufe mit gültigem L1 gegen `scaler_mean`/`scaler_scale` aus dem Training (PREREGISTRATION §9: rein beobachtend, ändert `swcast-kp-baseline-v0` nicht). Großes |z| kann z. B. auf eine anders kalibrierte aktive rtsw-Sonde hindeuten (siehe `l1_source` je Lauf).

| Merkmal | n | Mittelwert live | scaler_mean | scaler_scale | z |
| --- | --- | --- | --- | --- | --- |
| `persistence` | 2 | 4.3330 | 2.7849 | 1.3618 | +1.1368 |
| `recurrence` | 2 | 2.3330 | 2.7779 | 1.3658 | -0.3258 |
| `climatology` | 2 | 0.1589 | 0.0737 | 0.0407 | +2.0954 |
| `l1_bz_gsm` | 2 | -1.4837 | -0.0376 | 2.6466 | -0.5464 |
| `l1_by_gsm` | 2 | 1.5338 | -0.0680 | 3.4846 | +0.4597 |
| `l1_speed` | 2 | 398.5566 | 423.6772 | 98.2150 | -0.2558 |
| `l1_dyn_pressure` | 2 | 230587.7760 | 1027266.9654 | 815463.5142 | -0.9770 |
| `l1_newell` | 2 | 3922.7910 | 3585.9968 | 3161.7895 | +0.1065 |
