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
| `persistence` | 77 | 3.2337 | 2.7849 | 1.3618 | +0.3296 |
| `recurrence` | 77 | 2.8745 | 2.7779 | 1.3658 | +0.0707 |
| `climatology` | 77 | 0.1487 | 0.0737 | 0.0407 | +1.8434 |
| `l1_bz_gsm` | 77 | 0.3014 | -0.0376 | 2.6466 | +0.1281 |
| `l1_by_gsm` | 77 | -0.6193 | -0.0680 | 3.4846 | -0.1582 |
| `l1_speed` | 77 | 432.9681 | 423.6772 | 98.2150 | +0.0946 |
| `l1_dyn_pressure` | 77 | 789722.3239 | 1027266.9654 | 815463.5142 | -0.2913 |
| `l1_newell` | 77 | 3222.7843 | 3585.9968 | 3161.7895 | -0.1149 |
