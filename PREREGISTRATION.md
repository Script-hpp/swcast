# swcast: Preregistration (Entwurf)

Dieses Dokument friert das Regelwerk und die genaue Definition der Benchmarks (M0) sowie des zukünftigen Live-Betriebs (M1) ein. Nach dem finalen Commit (und OpenTimestamps-Verifizierung) dürfen keine Änderungen mehr an den Validierungsregeln vorgenommen werden.

## 1. Fenster und Labels (PRD §3)
- **Zeitfenster:** Vorhersagen beziehen sich auf exakte Zeitfenster (z. B. 24h ab 00:00 UTC).
- **Grenzen:** Fenster sind halboffen: `[window_start, window_end)`. Die `peak_time` eines Flares muss `>= start` und `< end` sein.
- **Klassen:** Die Kategorien sind kumulativ: C+ (C, M, X), M+ (M, X), X (nur X).
- **ODER-Regel:** Sobald mindestens ein Flare der entsprechenden Klasse im Fenster auftritt, ist das Label `1` (True). Es erfolgt keine Doppelzählung und keine komplexe Deduplizierung überlappender Flares.
- **Wahrheits-Label:** Historische und finale Flare-Zuweisung erfolgt maßgeblich über die NOAA NCEI GOES-R XRS Flare Summary. Kp-Labels erfolgen maßgeblich über die GFZ Potsdam Nowcast-API (definitive Daten werden nur nachträglich als Kontrolle genutzt).
- **Sturm-Definition:** Ein geomagnetischer Sturm gilt als eingetreten, wenn der GFZ Kp-Index im entsprechenden 24h-Tagesfenster (UTC) den Wert $Kp \ge 5.0$ erreicht. Ein Wert von $4,667$ ($5-$) ist *nicht* ausreichend.

## 2. Lückenerkennung
- Ein Fenster wird von der Auswertung ausgeschlossen, wenn **> 10% (144 Minuten bei 24h)** der 1-Minuten-Röntgenflussdaten fehlen oder ungültig sind.
- **Ungültig:** Eine Minute gilt nur dann als ungültig, wenn für **alle** verfügbaren Satelliten (kombinierte Maske aus G18 und G19) ein Fehlen (`NaN`), ein Fehlerflag (`(flag & 2) != 0`) oder eine Verdeckung (Eclipse, `(flag & 1) != 0`) vorliegt. Interpolierte Daten (`(flag & 4) != 0`) bleiben gültig. Fehlt eine Zeile im Datensatz komplett, zählt sie als `NaN` (ungültig).
- **Datenende:** Der Auswertungszeitraum wird automatisch vor der Leaderboard-Berechnung auf das Ende der gemeinsamen Datenabdeckung gekappt (Minimum aus Flare-Peak-Times und der 1-Minuten-Gaps-Serie).

## 3. Fensterkonvention
- Es gilt **Konvention b**: Jedes Modell wird auf seinem eigenen, nativen Fenster-Raster bewertet. 
- Es erfolgt keine künstliche Umrechnung auf gemeinsame Fenster.
- Die Vergleichbarkeit zwischen Modellen entsteht ausschließlich über den Brier Skill Score (BSS) gegen eine Klimatologie-Baseline, die auf **exakt demselben Raster** wie das jeweilige Modell berechnet wird.

## 4. Metriken
- **Brier Score:** Mittlerer quadratischer Fehler der Wahrscheinlichkeit.
- **Brier Skill Score (BSS):** Relative Verbesserung gegenüber der Klimatologie auf demselben Raster.
- **True Skill Statistic (TSS):** Bei optimaler Schwelle (Youden's J) und bei fixer 50-%-Schwelle.
- **Reliability:** Reliability-Diagramm zur Kalibrierungsprüfung.
- **Punktvorhersage (nur beschreibend):** Für die $Kp_{max}$-Punktvorhersage werden zusätzlich RMSE und MAE berechnet (ohne Relevanz für das Erfolgskriterium).
- **Konfidenzintervalle (KI):** 95-%-KI berechnet über Block-Bootstrap mit exakt 10.000 Resamples, Perzentilmethode und dem festen Seed `2026`. Blocklänge = 27 Tage.
- **Klimatologie-Definition (Referenz für BSS):**
  - Für Kp: Der Anteil der Sturmtage ($Kp \ge 5.0$) in den exakt 365 Tagen vor dem Zieltag (basierend auf GFZ).
  - Für Flares: Die Ereignisrate der Klasse in den exakt 365 Tagen vor Fensterbeginn.

## 5. Erfolgskriterium (M1)
**Wichtig:** Das Kriterium für die Modellversion `v0` bezieht sich **ausschließlich** auf die Vorhersage $Kp \ge 5$ für Tag +1/+2/+3. Das Kriterium für Flares (C+, M+) greift erst bei einer zukünftigen Modellversion, die auch Flares vorhersagt (verbunden mit einer eigenen Preregistration).

Für die Zielgröße Kp $\ge 5$ (Tag +1/+2/+3) über einen Evaluierungszeitraum von **$N = 365$ Tagen**:
- Evaluierung der Differenz $\Delta \text{BSS} = \text{BSS}(\text{swcast}) - \text{BSS}(\text{SWPC})$ per 95-%-Block-Bootstrap-KI (27-Tage-Blöcke) im gepaarten Vergleich (Tage, an denen das SWPC-Produkt fehlt, werden ausgeschlossen und die Anzahl berichtet; Tage ohne swcast-Vorhersage erhalten den Brier-Score der Klimatologie).
- **"Mithalten":** Die untere Grenze des KI liegt über $-0,05$.
- **"Übertreffen":** Die untere Grenze des KI liegt über $0$.
(Zwischenstände nach 90 und 180 Tagen dienen nur der beschreibenden Beobachtung). Maßgeblich für das Kriterium sind die GFZ Nowcast-Daten.

## 6. Betrieb und Issue Time
- Der tägliche Vorhersagelauf findet vollautomatisch um **22:30 UTC** statt.
- **Issue Time:** Maßgeblich für die `issue_time` ist *ausschließlich* der Zeitstempel der OpenTimestamps-Verankerung des Hashes, nicht ein lokal generierter Zeitstempel.
- Liegt dieser OTS-Beleg auf oder nach 00:00 UTC des Zieltags, gilt die Vorhersage als "verpasst" und wird in der Auswertung hart mit der Vorhersage der Klimatologie ersetzt.

## 7. Modellspezifikation (`swcast-kp-baseline-v0`)
- **Ziel:** Tägliche Vorhersage des maximalen Kp für Tag +1 bis +3 (inkl. Wahrscheinlichkeit $Kp \ge 5$).
- **Eingaben:**
  1. **Persistenz:** Das Maximum des GFZ-Kp im letzten vollständigen UTC-Tag vor der `issue_time`.
  2. **Rekurrenz:** Das Kp-Maximum exakt 27 Tage vor dem Zieltag.
  3. **Klimatologie:** Die Rate für $Kp \ge 5$ in den 365 Tagen vor der `issue_time`.
  4. **L1-Sonnenwind:** Durchschnittswerte über die letzten 2 Stunden vor `issue_time` für $B_z$ (nT), $V$ (km/s), dynamischen Druck ($Dichte \times V^2$) und die Newell-Kopplungsfunktion (sofern live verfügbar).
- **Mischungsform:** 
  - Für $p\_storm$ ($P(Kp \ge 5)$): Logistische Regression auf alle oben genannten Merkmale.
  - Für $kp_{max}$ (deterministisch): Lineare Regression auf dieselben Merkmale.
- **Trainingszeitraum:** Fester Zeitraum von 2005-01-01 bis 2025-12-31, unter Nutzung von OMNI (historischer Sonnenwind) und GFZ (definitive Kp-Daten). Die Modellgewichte dürfen erst in Schritt 7 (nach dem Einfrieren) berechnet werden, das Verfahren ist jedoch hiermit fixiert.
- **Validierungsverfahren:** Rolling-Origin-Cross-Validation nach Jahren (von 2015 bis 2025). Als Verlustfunktion dient der Brier-Score für $p\_storm$ und der RMSE für $kp_{max}$.
- **Rückfallregel:** Sollten beim automatischen Lauf um 22:30 UTC aktuelle L1-Daten ausfallen oder fehlen, fällt das System auf ein separates Backup-Modell zurück, das *ausschließlich* auf Persistenz, Rekurrenz und Klimatologie (ohne L1-Merkmale) trainiert wurde.

## 8. SWPC-Vergleich
- Für **Flares** (sofern zukünftig relevant): SWPC `m_class_1_day` in `solar_probabilities.json` steht für M+ ($M \ge 1.0$) und `x_class_1_day` für X. Eine zusätzliche Sensitivitätsanalyse mit $P(M+) = \min(1, P(M) + P(X))$ wird *nur* beschreibend berichtet.
- Für **Kp**:
  - Determinismus ($Kp_{max}$): `noaa-planetary-k-index-forecast.json` (wird über RMSE/MAE beschreibend verglichen).
  - Wahrscheinlichkeit ($P(Kp \ge 5)$): **OFFENER PUNKT FÜR DEN REVIEWER**: Das Produkt `3-day-solar-geomag-predictions.txt` liefert keine Vorhersage `:Prob_Planetary:`, sondern nur `:Prob_Mid:` und `:Prob_High:`. Sollte für $P(Kp \ge 5_{planetary})$ die Wahrscheinlichkeit der `:Prob_High:`-Stationen als Proxy verwendet werden, oder das Maximum aus Mid und High? (jeweils die Summe aus *Minor_Storm* und *Major-Severe_Storm*). Da keine explizite planetare Wahrscheinlichkeit existiert, bitte ich hier um Festlegung!
  - Maßgeblich ist jeweils das SWPC-Produkt, das um 22:00 UTC ausgegeben wurde (vor unserem 22:30-Lauf).

## 9. Versionierungsregel
- **Unveränderbarkeit:** Nach dem Einfrieren dieses Dokuments wird das Modell `swcast-kp-baseline-v0` niemals aufgrund von Live-Ergebnissen oder im laufenden Betrieb angepasst.
- Jede methodische Verbesserung erhält eine neue Modellversion (z. B. `swcast-kp-baseline-v1`) mit eigenem Zeitstempel, eigener Preregistration und eigener paralleler Wertung.
