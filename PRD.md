# PRD: swcast – Start (Meilensteine 0 und 1)

*Arbeitstitel „swcast" (space weather forecast), angelehnt an dr4cast. Stand: 27.09.2026.*

## 1. Kontext und Ziel

swcast erstellt täglich Weltraumwetter-Vorhersagen (Flares, Kp), friert sie vor ihrem Eintreten
nachweisbar ein und wertet sie nach vorab festgelegten Regeln öffentlich aus. Langfristiges Ziel:
mit NOAA SWPC mithalten und Flare-Vorhersagen beim CCMC Flare Scoreboard einreichen.

Dieses PRD beschreibt nur den Start:

- **Meilenstein 0 – Benchmark:** Wie gut sind die bestehenden Modelle auf dem Scoreboard wirklich?
  Ergebnis ist ein Leaderboard, das die Latte für swcast festlegt.
- **Meilenstein 1 – Kp-Baseline live:** Erste eigene tägliche Vorhersage (nur Baselines, noch kein
  ML), inklusive Einfrieren, Zeitstempel und automatischer Auswertung.

Beide laufen auf dem Laptop, ohne GPU, mit unter 5 GB Daten.

## 2. Nicht-Ziele (für diese Phase)

- Keine Sonnenbilder, keine SDO-Pipeline, kein CNN.
- Kein eigenes ML-Modell für Flares (kommt in Meilenstein 2 mit SHARP-Kennzahlen).
- Keine Einreichung bei CCMC.

## 3. Definitionen (vor Start einfrieren)

| Begriff | Definition |
| --- | --- |
| Flare-Ereignis | Eintrag in der offiziellen GOES-Flareliste mit Spitzenfluss im Kanal 1–8 Å (0,1–0,8 nm) |
| C-Ereignis | Spitzenfluss ≥ 1e-6 W/m² (C1.0 oder stärker, „C+") |
| M-Ereignis | Spitzenfluss ≥ 1e-5 W/m² („M+") |
| Vorhersagefenster Flares | 24 h ab Fensterbeginn, volle Sonnenscheibe |
| Kp-Ziel | Maximaler Kp im UTC-Tag, für Tag +1, +2, +3 |
| Kp-Referenz | Primär: vorläufiger (nowcast) Kp des GFZ; Kontrolle: endgültiger GFZ-Kp |
| Ereignis „Sturm" | Kp ≥ 5 (G1 oder stärker) |

**Fenster-Zuordnungsregel (frozen 27.09.2026, vor Nutzung in PREREGISTRATION.md zu übernehmen):**
Ein Fenster ist positiv für eine Klasse, wenn irgendein Flare mit **Spitzenzeit** (`peak_time`,
nicht Beginnzeit) innerhalb des Fensters die Klassenschwelle erreicht. Spitzenzeit statt Beginnzeit,
weil die klassenbestimmende Spitzenflussstärke physikalisch an den Zeitpunkt der Spitze gebunden ist,
nicht an den Beginn — ein Flare kann in einem Fenster beginnen und im nächsten seine Spitze erreichen.
Fenster sind halboffen `[window_start, window_end)`: Ein Flare, dessen Spitze exakt auf eine
Fenstergrenze fällt, gehört zum Fenster, das an diesem Zeitpunkt **beginnt**, nicht zum vorherigen.

**Überlappende Flares:** Keine Sonderbehandlung nötig. Das Fenster-Label ist ein ODER über alle
Flares mit Spitze im Fenster (`any(peak_flux >= threshold)`), sodass mehrere oder überlappende
Flares automatisch korrekt in dieselbe Fensterprüfung einfließen, ohne Deduplizierung.

## 4. Datenquellen

| Daten | Quelle | Nutzung | Status |
| --- | --- | --- | --- |
| Vorhersagen aller Scoreboard-Modelle | CCMC Flare Scoreboard: statisches Dateiarchiv unter `iswa.gsfc.nasa.gov/iswa_data_tree/model/solar/flare-scoreboard/<MODELL>/<JJJJ>/<MM>/`, ein File pro Vorhersage (primär), HAPI-API unter `iswa.gsfc.nasa.gov/IswaSystemWebApp/flarescoreboard/hapi/` (Rückfalloption) | M0 Benchmark | Archiv-Pfad bestätigt und gegen `fetch/scoreboard.py` getestet für NOAA_1 (ISES-XML, day1/2/3-Files), SIDC_v2 (ISES-XML, abweichende Tag-Namen) und ASSA_1 (Klartext-Tabelle, kein XML) |
| GOES-Flareliste (historisch) | NOAA NCEI, GOES-R XRS Flare Summary (GOES-16 ff.), CSV/NetCDF unter `data.ngdc.noaa.gov/.../xrsf-l2-flrpt_science/` | M0 Labels | Format bestätigt; Umgang mit Überlappungen/Lücken noch offen |
| GOES-Flares (aktuell) | NOAA SWPC JSON-Dienste (`services.swpc.noaa.gov/json/goes/`) | M0/M1 laufend | Endpunkt prüfen |
| SWPC-Vorhersagen (M/X/C-Wahrscheinlichkeit, 3-Tage-Kp) | NOAA SWPC JSON (`services.swpc.noaa.gov/json/solar_probabilities.json`, `noaa-planetary-k-index-forecast.json`) **und** historisches FTP-Archiv `ftp.swpc.noaa.gov/pub/warehouse/<jahr>/` (Textprodukte, 1996 bis heute) | Baseline, auch rückwirkend aufbaubar | Bestätigt |
| Kp-Index | GFZ Potsdam (Web-API `kp.gfz.de/app/json/?start=...&end=...&index=Kp&status=now\|def`) | M1 Labels | API bestätigt (siehe Abschnitt 4a) |
| Sonnenwind L1 | NOAA SWPC (live, DSCOVR/ACE), NASA OMNI (historisch) | M1 Eingabe | Pflicht für M1 (Endpunkt live noch prüfen) |

**Hinweis GOES-Kalibrierung:** Ältere GOES-Satelliten (bis GOES-15) wurden operativ mit einem
Skalierungsfaktor veröffentlicht, der in den wissenschaftlichen Daten später entfernt wurde. Dadurch
verschieben sich Klassengrenzen in historischen Daten. Vor jeder Nutzung von Daten vor 2017 klären,
welche Skalierung vorliegt; im Zweifel nur GOES-16 und neuer verwenden. Der zusammengeführte
NCEI-Datensatz umfasst GOES 8–19 in derselben Tabelle — beim Einlesen zwingend nach Satellitennummer
filtern, nicht auf Vorfilterung verlassen.

**Hinweis Kp-Label:** `noaa-planetary-k-index.json` (SWPC JSON) ist SWPCs eigene Kp-Schätzung und
darf nie als Label/Referenz dienen — als Kp-Referenz gilt ausschließlich GFZ (Abschnitt 3).

**Hinweis Scoreboard-Inhalt:** Die NOAA-Datei im Scoreboard-Archiv bestätigt, dass NOAA für die
volle Sonnenscheibe (Full Disk) nur M- und X-Wahrscheinlichkeiten liefert (keine C-Wahrscheinlichkeit
auf Full-Disk-Ebene; C-Werte gibt es nur pro aktiver Region, nicht Full Disk). Das fehlende
C+-Full-Disk-Feld muss als "nicht vorhergesagt" markiert werden, nicht als Wahrscheinlichkeit 0. Für
den Vergleich mit SWPCs eigenen C-Wahrscheinlichkeiten (aus `solar_probabilities.json`/FTP-Archiv)
ist das getrennt zu behandeln.

**Hinweis Scoreboard-Dateiformate:** Die Modelle im Archiv teilen sich kein gemeinsames Dateiformat.
Bestätigt sind zwei Formen: ISES-Standard-XML (`NOAA_1`, `SIDC_v2` — mit unterschiedlichen Tag-Namen
für das Vorhersagefenster und Flussklassen-Schreibweisen) und eine Klartext-Spaltentabelle (`ASSA_1`,
kein XML). `fetch/scoreboard.py` benötigt daher einen Parser pro Format/Modell; nicht registrierte
Modelle schlagen absichtlich mit `NotImplementedError` fehl, statt stillschweigend leere Daten zu
liefern.

**Hinweis Wartungsfenster:** CCMC-Website, Webapps und API sind am 30.09.2026, 9:30–15:30 EDT wegen
geplanter Infrastrukturarbeiten offline — Scoreboard-Downloads nicht in dieses Fenster legen.

**Referenz für M0-Validierung:** Eine 2025 erschienene Studie verifiziert SWPCs eigene Flarevorhersagen
für 1998–2024 aus genau diesem FTP-Archiv und eignet sich als externe Kontrolle für die M0-Ergebnisse.

## 5. Funktionale Anforderungen

### Meilenstein 0 – Benchmark

- **FR-0.1** Skript lädt alle verfügbaren Full-Disk-24-h-Vorhersagen des Scoreboards für einen
  wählbaren Zeitraum (Ziel: mindestens die letzten 12 Monate) und speichert sie als Parquet
  (Spalten: model, class, issue_time, window_start, window_end, probability).
- **FR-0.2** Skript lädt die GOES-Flareliste für denselben Zeitraum und erzeugt pro Fenster ein Label
  (0/1) je Klasse (C+, M+, X).
- **FR-0.3** Zuordnung Vorhersage ↔ Label über exakte Fenstergrenzen. Vorhersagen, deren Fenster
  Datenlücken in GOES enthalten, werden markiert, nicht still verworfen.
- **FR-0.4** Eigene Referenz-Baselines für dieselben Fenster:
  Klimatologie (Rate der letzten 12 Monate vor Fensterbeginn), Persistenz (Ereignis in den letzten
  24 h → 1, sonst 0, geglättet auf z. B. 0,8/0,2), gleitende 27-Tage-Rate.
- **FR-0.5** Leaderboard je Klasse: Anzahl Vorhersagen, Brier Score, Brier Skill Score gegenüber
  Klimatologie, True Skill Statistic (bei optimaler und bei 50-%-Schwelle), Reliability-Diagramm.
- **FR-0.6** Vergleich jedes Modells auf seinem eigenen nativen Fenster-Raster (Fensterkonvention b). Keine künstliche Umrechnung auf gemeinsame Fenster. Vergleichbarkeit zwischen Modellen entsteht durch den Brier Skill Score (BSS) gegen eine Klimatologie-Baseline, die auf exakt demselben Raster berechnet wird. Konfidenzintervalle per Block-Bootstrap über Tage (Blocklänge 27 Tage).
- **FR-0.7** Ergebnis als Markdown-Bericht mit Tabellen und Diagrammen im Repository.

### Meilenstein 1 – Kp-Baseline live

- **FR-1.1** Tägliche Vorhersage des maximalen Kp für Tag +1 bis +3 aus: Persistenz, 27-Tage-Rekurrenz,
  Klimatologie und **L1-Sonnenwind**, zusammengeführt über eine einfache Mischung (z. B. gewichtetes Mittel). **Wichtig:** Mischungsgewichte und Rekalibrierung werden *ausschließlich* auf historischen Daten vor dem Einfrieren angepasst.
- **FR-1.2** Zusätzlich Wahrscheinlichkeit für Kp ≥ 5 je Tag.
- **FR-1.3** Täglicher Lauf per GitHub Actions zu fester Uhrzeit (UTC, vorab festgelegt).
- **FR-1.4** Jede Vorhersage wird als JSON-Datei gespeichert, per SHA-256 gehasht und der Hash über
  OpenTimestamps verankert. Die .ots-Datei wird mit committet.
- **FR-1.5** Derselbe Lauf archiviert die aktuellen SWPC-Vorhersagen (Kp und Flares) mit Hash und
  Zeitstempel.
- **FR-1.6** Auswertungsskript berechnet laufend Scores gegen vorläufigen und endgültigen Kp; verpasste
  Tage zählen als Klimatologie-Vorhersage.
- **FR-1.7** Automatisch erzeugte Statusseite (README-Abschnitt oder GitHub Pages) mit aktuellen Scores.

## 6. Ausgabeformat

Flare-Vorhersagen werden von Anfang an im Einreichungsformat des CCMC Flare Scoreboard 2.0
gespeichert (JSON, Dateiname `ModelShortName.PredictionWindowStartTime.IssueTime.json`, Klassen
C, C+, M, M+, X, Wahrscheinlichkeit 0–1, Feld `mode`). So ist später keine Umstellung nötig.
Das aktuelle Schema vor der Implementierung von der CCMC-Seite prüfen.

Kp-Vorhersagen verwenden ein eigenes, einfaches JSON-Format:

```json
{
  "model": "swcast-kp-baseline-v0",
  "issue_time": "2026-10-01T06:00:00Z",
  "targets": [
    {"date": "2026-10-02", "kp_max": 3.33, "p_storm": 0.08},
    {"date": "2026-10-03", "kp_max": 4.0,  "p_storm": 0.15},
    {"date": "2026-10-04", "kp_max": 3.67, "p_storm": 0.11}
  ],
  "inputs_last_data_time": "2026-10-01T05:45:00Z"
}
```

## 7. Repository-Struktur

```
swcast/
├── PRD.md
├── PREREGISTRATION.md      # eingefrorene Regeln (Abschnitt 3 + Metriken + Kriterien)
├── config.yaml             # DATA_DIR, Zeiträume, Uhrzeit des Laufs
├── environment.yml         # feste Versionen
├── src/swcast/
│   ├── fetch/              # scoreboard.py, goes.py, swpc.py, kp.py
│   ├── labels.py
│   ├── baselines.py
│   ├── metrics.py          # Brier, BSS, TSS, Reliability, Bootstrap
│   ├── freeze.py           # Hash + OpenTimestamps
│   └── report.py
├── forecasts/              # eingefrorene Vorhersagen (JSON + .ots)
├── archive/swpc/           # archivierte SWPC-Produkte
├── reports/                # Benchmark- und laufende Berichte
└── .github/workflows/daily.yml
```

Daten liegen außerhalb des Repositorys unter `DATA_DIR` und werden nur über Skripte erzeugt.

## 8. Akzeptanzkriterien

**M0 fertig, wenn:**
- Leaderboard für C+ und M+ über mindestens 6 Monate vorliegt, mit Konfidenzintervallen.
- Eigene Klimatologie- und Persistenz-Baseline im selben Leaderboard stehen.
- Ein Dritter kann den Bericht mit einem Befehl aus Rohdaten reproduzieren.

**M1 fertig, wenn:**
- `PREREGISTRATION.md` mit OpenTimestamps-Beleg eingefroren ist, bevor die erste Vorhersage läuft.
- Der tägliche Lauf 7 Tage in Folge ohne manuellen Eingriff funktioniert hat.
- Die Auswertung für diese 7 Tage automatisch erzeugt wurde.

**Langfristiges Erfolgskriterium (N = 365 Tage):**
Für jede Zielgröße (Kp ≥ 5 für Tag +1/+2/+3; Flares C+, M+) wird der Brier Skill Score (BSS) gegen die eigene Klimatologie berechnet. Die Differenz $\Delta \text{BSS} = \text{BSS}(\text{swcast}) - \text{BSS}(\text{SWPC})$ wird per 95-%-Block-Bootstrap-KI (27-Tage-Blöcke) auf exakt denselben Tagen ausgewertet:
- **"Mithalten":** Die untere Grenze des 95-%-KI von $\Delta \text{BSS}$ liegt über $-0,05$.
- **"Übertreffen":** Die untere Grenze des 95-%-KI von $\Delta \text{BSS}$ liegt über $0$.
(Zwischenstände nach 90 und 180 Tagen dienen nur der beschreibenden Beobachtung.)

## 9. Reihenfolge der Aufgaben

1. Repository, Umgebung, `config.yaml` anlegen.
2. Zugriffswege prüfen und dokumentieren: Scoreboard-Download, GOES-Flareliste, SWPC-JSON, GFZ-Kp.
3. `fetch/goes.py` + `labels.py` (Grundlage für alles andere).
4. `fetch/scoreboard.py`, dann `metrics.py` mit Tests an kleinen Hand-Beispielen.
5. Benchmark-Bericht M0 erzeugen.
6. `PREREGISTRATION.md` schreiben und einfrieren.
7. `fetch/kp.py`, `fetch/swpc.py`, `fetch/solarwind.py`, `baselines.py`, `freeze.py`.
8. GitHub-Actions-Workflow, 7-Tage-Testlauf.

## 10. Entscheidungen und Offene Fragen

- **Fensterkonvention:** Option b – Jedes Modell wird auf seinem eigenen Raster bewertet. Vergleichbarkeit entsteht über den BSS relativ zur auf demselben Raster berechneten Klimatologie.
- **Datenlücken-Erkennung:** Eine echte Lücke liegt vor, wenn >10% (144 Minuten) der 1-Minuten-XRS-Mittelwerte eines 24h-Fensters fehlen oder durch Flags als fehlerhaft markiert sind (`(flag & 2) != 0`). Solche Fenster werden von der Auswertung ausgeschlossen.
- **Flareliste für M1:** NCEI ist maßgeblich für die endgültige Bewertung. SWPC-Echtzeit wird nur vorläufig auf der Statusseite angezeigt.
- **Uhrzeit des täglichen Laufs:** 22:30 UTC (cron `30 22 * * *`). Wenn `issue_time >= 00:00 UTC` des Zieltags, gilt die Vorhersage als verpasst → Ersatz durch Klimatologie.
- **Länge N des Auswertungszeitraums:** N = 365 Tage für die harte Bewertung (siehe §8 Kriterien).
- **Grundregel Einfrieren:** Nach dem Einfrieren wird das Modell *niemals* aufgrund von Live-Ergebnissen geändert. Jede Verbesserung führt zu einer komplett neuen Modellversion (z. B. `swcast-kp-baseline-v1`) mit eigenem Zeitstempel und eigener paralleler Wertung. Der tägliche Lauf bleibt strikt vollautomatisch.

## 11. Risiken

| Risiko | Gegenmaßnahme |
| --- | --- |
| Scoreboard-Daten unvollständig oder schwer abrufbar | Frühzeitig prüfen (Aufgabe 2); notfalls Kontakt zu CCMC |
| GOES-Kalibrierungswechsel verfälscht Labels | Nur GOES-16+ für M0 |
| Datenquelle ändert Format | Schema-Checks im täglichen Lauf, Fehler schlägt laut fehl |
| GitHub-Actions-Ausfall | Verpasste-Tage-Regel; Monitoring per Benachrichtigung |
