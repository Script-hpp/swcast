# swcast-kp-baseline-v0 – Live-Status

**Vorläufig – maßgeblich erst bei N = 365 Tagen (PREREGISTRATION §5).**

Auswahlregel je Lauftag (§6): Es zählt die früheste ERFOLGREICH erzeugte Vorhersage mit `run_start` ≥ 22:00 UTC und gültigem TSA-Beleg vor der Frist. Ein Fehlschlag (MISSED) verbraucht den Tag nicht — ein gelungener Wiederholungslauf desselben Tages zählt dann; ein späterer erfolgreicher Wiederholungslauf NACH dem ersten Erfolg wird dagegen ignoriert.

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
| `persistence` | 92 | 3.0906 | 2.7849 | 1.3618 | +0.2244 |
| `recurrence` | 92 | 2.8515 | 2.7779 | 1.3658 | +0.0539 |
| `climatology` | 92 | 0.1465 | 0.0737 | 0.0407 | +1.7900 |
| `l1_bz_gsm` | 92 | 0.1996 | -0.0376 | 2.6466 | +0.0896 |
| `l1_by_gsm` | 92 | -0.5408 | -0.0680 | 3.4846 | -0.1357 |
| `l1_speed` | 92 | 426.4361 | 423.6772 | 98.2150 | +0.0281 |
| `l1_dyn_pressure` | 92 | 704713.5770 | 1027266.9654 | 815463.5142 | -0.3955 |
| `l1_newell` | 92 | 3216.6480 | 3585.9968 | 3161.7895 | -0.1168 |
