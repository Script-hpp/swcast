# swcast: Preregistration (Entwurf)

Dieses Dokument friert das Regelwerk und die genaue Definition der Benchmarks (M0) sowie des zukünftigen Live-Betriebs (M1) ein. Nach dem finalen Commit (und OpenTimestamps-Verifizierung) dürfen keine Änderungen mehr an den Validierungsregeln vorgenommen werden.

## 1. Fenster und Labels (PRD §3)
- **Zeitfenster:** Vorhersagen beziehen sich auf exakte Zeitfenster (z. B. 24h).
- **Grenzen:** Fenster sind halboffen: `[window_start, window_end)`. Die `peak_time` eines Flares muss `>= start` und `< end` sein.
- **Klassen:** Die Kategorien sind kumulativ: C+ (C, M, X), M+ (M, X), X (nur X).
- **ODER-Regel:** Sobald mindestens ein Flare der entsprechenden Klasse im Fenster auftritt, ist das Label `1` (True). Es erfolgt keine Doppelzählung und keine komplexe Deduplizierung überlappender Flares.
- **Wahrheits-Label:** Historische und finale Flare-Zuweisung erfolgt maßgeblich über die NOAA NCEI GOES-R XRS Flare Summary. Kp-Labels erfolgen maßgeblich über die GFZ Potsdam Nowcast/Definitive API. Für M1-Statusseiten dürfen vorläufige SWPC-Echtzeitlisten genutzt werden.
- **Sturm-Definition:** Ein geomagnetischer Sturm gilt als eingetreten, wenn $Kp \ge 5$ im entsprechenden 24h-Tagesfenster (UTC).

## 2. Lückenerkennung
- Ein Fenster wird von der Auswertung ausgeschlossen, wenn **> 10% (144 Minuten bei 24h)** der 1-Minuten-Röntgenflussdaten fehlen oder ungültig sind.
- **Ungültig:** Eine Minute gilt nur dann als ungültig, wenn für **alle** verfügbaren Satelliten (kombinierte Maske aus G18 und G19) ein Fehlen (`NaN`), ein Fehlerflag (`(flag & 2) != 0`) oder eine Verdeckung (Eclipse, `(flag & 1) != 0`) vorliegt. Interpolierte Daten (`(flag & 4) != 0`) bleiben gültig.
- **Datenende:** Wenn das abgefragte Fenster über die verfügbare Datenabdeckung (Flare-Liste UND Lückenmaske) hinausgeht, wird es verworfen.

## 3. Fensterkonvention
- Es gilt **Konvention b**: Jedes Modell wird auf seinem eigenen, nativen Fenster-Raster bewertet. 
- Es erfolgt keine künstliche Umrechnung auf gemeinsame Fenster.
- Die Vergleichbarkeit zwischen Modellen entsteht ausschließlich über den Brier Skill Score (BSS) gegen eine Klimatologie-Baseline, die auf **exakt demselben Raster** wie das jeweilige Modell berechnet wird.

## 4. Metriken
- **Brier Score:** Mittlerer quadratischer Fehler der Wahrscheinlichkeit.
- **Brier Skill Score (BSS):** Relative Verbesserung gegenüber der Klimatologie auf demselben Raster.
- **True Skill Statistic (TSS):** Bei optimaler Schwelle (Youden's J) und bei fixer 50-%-Schwelle.
- **Reliability:** Reliability-Diagramm zur Kalibrierungsprüfung.
- **Konfidenzintervalle (KI):** 95-%-KI berechnet über Block-Bootstrap mit 27-Tage-Blöcken.
- **Klimatologie-Definition:** Ereignisrate der exakt 365 Tage vor Fensterbeginn (dynamisch rollierend).

## 5. Erfolgskriterium (M1)
Für jede Zielgröße (Kp $\ge 5$ für Tag +1/+2/+3; Flares C+, M+) über einen Evaluierungszeitraum von **$N = 365$ Tagen**:
- Evaluierung der Differenz $\Delta \text{BSS} = \text{BSS}(\text{swcast}) - \text{BSS}(\text{SWPC})$ per 95-%-Block-Bootstrap-KI (27-Tage-Blöcke) auf denselben Tagen.
- **"Mithalten":** Die untere Grenze des KI liegt über $-0,05$.
- **"Übertreffen":** Die untere Grenze des KI liegt über $0$.
(Zwischenstände nach 90 und 180 Tagen dienen nur der beschreibenden Beobachtung).

## 6. Betrieb
- Der tägliche Vorhersagelauf findet vollautomatisch um **22:30 UTC** statt.
- Liegt die `issue_time` der Vorhersage auf oder nach 00:00 UTC des Zieltags, gilt sie als "verpasst" und wird in der Auswertung durch die Klimatologie ersetzt.

## 7. Modellspezifikation (`swcast-kp-baseline-v0`)
- **Ziel:** Tägliche Vorhersage des maximalen Kp für Tag +1 bis +3 (inkl. Wahrscheinlichkeit $Kp \ge 5$).
- **Eingaben:** Persistenz, 27-Tage-Rekurrenz, Klimatologie und L1-Sonnenwind.
- **Verfahren:** Eine Mischung der Eingaben (z. B. gewichtetes Mittel).
- **Training/Anpassung:** Die Anpassung der Gewichte, Rekalibrierung und Festlegung der Mischungsform erfolgt *ausschließlich* auf historischen Daten (Trainingszeitraum endet vor dem Einfrier-Datum dieses Dokuments). Das genaue Validierungsverfahren hierfür ist fester Bestandteil des Modells.

## 8. SWPC-Vergleich
- Für Kp nutzt SWPC den `noaa-planetary-k-index-forecast.json` und das FTP-Archiv für 3-Tage Vorhersagen.
- Für Flares nutzt SWPC `solar_probabilities.json` (`c_class_1_day`, `m_class_1_day`, `x_class_1_day`). 
- **OFFENER PUNKT AN REVIEWER:** Um die kumulierte Wahrscheinlichkeit M+ vorherzusagen, müssen wir klären, ob `m_class_1_day` in den SWPC-Daten bereits für "M und stärker" steht oder nur für exakt die M-Klasse. Falls letzteres: Reicht eine einfache Addition $P(M+) = P(M) + P(X)$ oder wie wird die kumulierte Wahrscheinlichkeit für den SWPC-Vergleich konstruiert?

## 9. Versionierungsregel
- **Unveränderbarkeit:** Nach dem Einfrieren dieses Dokuments wird das Modell (`swcast-kp-baseline-v0`) niemals aufgrund von Live-Ergebnissen oder im laufenden Betrieb angepasst.
- Jede methodische Verbesserung erhält eine neue Modellversion (z. B. `swcast-kp-baseline-v1`) mit eigenem Zeitstempel, eigener Preregistration und eigener paralleler Wertung.
