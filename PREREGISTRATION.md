# swcast: Preregistration (Entwurf)

Dieses Dokument friert das Regelwerk und die genaue Definition der Benchmarks (M0) sowie des zukünftigen Live-Betriebs (M1) ein. Nach dem finalen Commit (und OpenTimestamps-Verifizierung) dürfen keine Änderungen mehr an den Validierungsregeln vorgenommen werden.

## 1. Fenster und Labels (PRD §3)
- **Zeitfenster:** Vorhersagen beziehen sich auf exakte Zeitfenster (z. B. 24h ab 00:00 UTC).
- **Grenzen:** Fenster sind halboffen: `[window_start, window_end)`. Die `peak_time` eines Flares muss `>= start` und `< end` sein.
- **Klassen:** Die Kategorien sind kumulativ: C+ (C, M, X), M+ (M, X), X (nur X).
- **ODER-Regel:** Sobald mindestens ein Flare der entsprechenden Klasse im Fenster auftritt, ist das Label `1` (True). Es erfolgt keine Doppelzählung und keine komplexe Deduplizierung überlappender Flares.
- **Wahrheits-Label:** Historische und finale Flare-Zuweisung erfolgt maßgeblich über die NOAA NCEI GOES-R XRS Flare Summary. Kp-Labels erfolgen maßgeblich über die GFZ Potsdam Nowcast-API (definitive Daten werden nur nachträglich als Kontrolle genutzt).
- **Sturm-Definition:** Ein geomagnetischer Sturm gilt als eingetreten, wenn der GFZ Kp-Index im entsprechenden 24h-Tagesfenster (UTC) den Wert $Kp \ge 5.0$ erreicht. Ein Wert von $4,667$ ($5-$) ist *nicht* ausreichend. Zur Einordnung: Dies entspricht der NOAA G1-Minor-Sturmskala, welche explizit bei $Kp=5$ beginnt (siehe SWPC Space Weather Scales).

## 2. Lückenerkennung
- Ein Fenster wird von der Auswertung ausgeschlossen, wenn **> 10% (144 Minuten bei 24h)** der 1-Minuten-Röntgenflussdaten fehlen oder ungültig sind.
- **Ungültig:** Eine Minute gilt nur dann als ungültig, wenn für **alle** verfügbaren Satelliten (kombinierte Maske aus G18 und G19) ein Fehlen (`NaN`), ein Fehlerflag (`(flag & 2) != 0`) oder eine Verdeckung (Eclipse, `(flag & 1) != 0`) vorliegt. Interpolierte Daten (`(flag & 4) != 0`) bleiben gültig. Fehlt eine Zeile im Datensatz komplett, zählt sie als `NaN` (ungültig).
- **Datenende:** Der Auswertungszeitraum wird automatisch vor der Leaderboard-Berechnung auf das Ende der gemeinsamen Datenabdeckung gekappt. Das Datenende der Flareliste wird dabei direkt aus dem Dateinamen/den Metadaten der bereitgestellten NCEI-Datei ermittelt, *nicht* anhand des Zeitpunkts des letzten dokumentierten Flares.

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
  - Für Kp: Der Anteil der Sturmtage ($Kp \ge 5.0$) in den exakt 365 Tagen bis einschließlich des letzten vollständigen UTC-Tags VOR dem Lauftag (basierend auf GFZ).
  - Für Flares: Die Ereignisrate der Klasse in den exakt 365 Tagen bis einschließlich des letzten vollständigen UTC-Tags VOR dem Lauftag.

## 5. Erfolgskriterium (M1)
**Wichtig:** Das Kriterium für die Modellversion `v0` bezieht sich **ausschließlich** auf die Vorhersage $Kp \ge 5$ für Tag +1/+2/+3. Das Kriterium für Flares (C+, M+) greift erst bei einer zukünftigen Modellversion, die auch Flares vorhersagt (verbunden mit einer eigenen Preregistration).

Für die Zielgröße Kp $\ge 5$ (Tag +1/+2/+3) wird das Erfolgskriterium **je Vorlauftag getrennt ausgewertet und berichtet** (es gibt keine zusammengefasste Gesamtaussage). Die Zählung $N = 365$ Tage beginnt ab dem Zieltag +1 der ersten Vorhersage, deren RFC-3161 TSA-Beleg gültig vor 00:00 UTC des Zieltags liegt. Das konkrete Datum wird später in einer separaten Log-Datei (z. B. `forecasts/START.md`) dokumentiert, nicht hier.
- Evaluierung der Differenz $\Delta \text{BSS} = \text{BSS}(\text{swcast}) - \text{BSS}(\text{SWPC})$ per 95-%-Block-Bootstrap-KI (27-Tage-Blöcke) im gepaarten Vergleich:
  - Tage, an denen das SWPC-Produkt fehlt, werden aus dem gepaarten $\Delta\text{BSS}$ ausgeschlossen (die Anzahl wird berichtet).
  - Tage ohne `swcast`-Vorhersage erhalten den Brier-Score der Klimatologie.
  - Tage, an denen im GFZ-Nowcast Lücken herrschen, werden von der Auswertung ausgeschlossen (die Anzahl wird berichtet).
- **"Mithalten":** Die untere Grenze des KI liegt über $-0,05$.
- **"Übertreffen":** Die untere Grenze des KI liegt über $0$.
(Zwischenstände nach 90 und 180 Tagen dienen nur der beschreibenden Beobachtung). Maßgeblich für das Kriterium sind die GFZ Nowcast-Daten.

## 6. Betrieb, Datenstand und Issue Time
- Der tägliche Vorhersagelauf findet vollautomatisch um **22:30 UTC** statt.
- **Datenstand:** Alle Merkmale (z.B. L1-Mittel über 2h, Kp) beziehen sich auf den tatsächlichen Laufbeginn, da die exakte `issue_time` (Zeitstempel der Registrierung) zum Rechenzeitpunkt noch nicht feststeht. Der Datenstand wird als `inputs_last_data_time` mitgespeichert.
- **Issue Time:** Da OpenTimestamps teils mehrere Stunden für die Bitcoin-Verankerung benötigt, ist für die harte Deadline *ausschließlich* ein RFC-3161 Trusted Timestamp (TSA) maßgeblich. Der SHA-256-Hash der Vorhersagedatei wird in jedem Lauf bei **zwei unabhängigen TSAs** zertifiziert (beide `.tsr`-Tokens werden mitcommittet):
  1. `https://freetsa.org/tsr`
  2. `http://timestamp.digicert.com`
- Die `issue_time` entspricht dem **frühesten gültigen (signaturgeprüften)** TSA-Zeitpunkt aus diesen beiden Diensten.
- Liegen **beide** validen TSA-Belege auf oder nach 00:00 UTC des Zieltags (oder schlagen beide fehl), gilt die Vorhersage als "verpasst" und wird in der Auswertung hart mit der Vorhersage der Klimatologie ersetzt.
- OpenTimestamps (.ots) wird weiterhin als zusätzlicher dezentraler Langzeitbeweis mitgeneriert, ist für die Fristüberschreitung jedoch nicht maßgeblich.

## 7. Modellspezifikation (`swcast-kp-baseline-v0`)
- **Ziel:** Tägliche Vorhersage des maximalen Kp für Tag +1, +2 und +3 (inkl. Wahrscheinlichkeit $Kp \ge 5$). Es wird ein separates Modell (mit eigenen Gewichten) je Vorlauftag (+1, +2, +3) trainiert.
- **Eingaben:**
  1. **Persistenz:** Das Maximum des GFZ-Nowcast-Kp über die letzten 8 vollständigen 3-Stunden-Intervalle vor Laufbeginn. (Im Training wird dieselbe Definition auf GFZ-Definitiv angewendet; diese nowcast/definitiv Diskrepanz ist eine bekannte Einschränkung).
  2. **Rekurrenz:** Das Kp-Maximum exakt 27 Tage vor dem Zieltag.
  3. **Klimatologie:** Die Rate für $Kp \ge 5$ in den exakt 365 Tagen bis einschließlich des letzten vollständigen UTC-Tags VOR dem Lauftag.
  4. **L1-Sonnenwind:** Durchschnittswerte über die exakt 2 Stunden vor Laufbeginn für $B_z$ (nT, GSM-Koordinaten), $B_y$ (nT, GSM), $V$ (km/s), dynamischen Druck ($Dichte \times V^2$) und die Newell-Kopplungsfunktion ($V^{4/3} B_T^{2/3} \sin^{8/3}(\theta_c / 2)$). Für Live-L1-Daten im Gegensatz zu OMNI-Daten zur Bugstoßwelle wird bewusst *kein* weiterer Laufzeitversatz zur Erde angesetzt (bei 2-Stunden-Mitteln vertretbar).
- **Mischungsform & Architektur:** 
  - Für $p\_storm$ ($P(Kp \ge 5)$): Logistische Regression auf alle oben genannten Merkmale. **Regularisierung:** L2 mit Stärke $C \in \{0.01, 0.1, 1, 10\}$ (per Rolling-Origin-CV nach Brier-Score gewählt).
  - Für $kp_{max}$ (deterministisch): Lineare Regression (Ridge) auf dieselben Merkmale. **Regularisierung:** L2 mit Penalty $\alpha \in \{0.01, 0.1, 1, 10\}$ (per Rolling-Origin-CV nach RMSE gewählt).
  - Alle Merkmale werden anhand der Trainingsdaten standardisiert.
- **Trainingszeitraum:** Der finale Endfit nach CV erfolgt auf dem festen Zeitraum von 2005-01-01 bis 2025-12-31, unter Nutzung von OMNI (historischer Sonnenwind) und GFZ (definitive Kp-Daten). 
- **Validierungsverfahren:** Rolling-Origin-Cross-Validation nach ganzen Kalenderjahren (von 2015 bis 2025). Als Verlustfunktion dient der Brier-Score für $p\_storm$ und der RMSE für $kp_{max}$.
- **Rückfallregel:** Sollte beim automatischen Lauf um 22:30 UTC irgendein L1-Merkmal fehlen, oder es liegen im 2-Stunden-Fenster weniger als 60 von 120 Minuten gültig vor, fällt das System hart auf ein separates Backup-Modell zurück. Dieses Modell wurde exakt analog trainiert, jedoch *ausschließlich* auf Persistenz, Rekurrenz und Klimatologie (ohne L1-Merkmale).

## 8. SWPC-Vergleich
- Für **Flares** (sofern zukünftig relevant): SWPC `m_class_1_day` in `solar_probabilities.json` steht für M+ ($M \ge 1.0$) und `x_class_1_day` für X+. Eine zusätzliche Sensitivitätsanalyse mit $P(M+) = \min(1, P(M) + P(X))$ wird *nur* beschreibend berichtet.
- Für **Kp**:
  - **Determinismus ($Kp_{max}$):** `noaa-planetary-k-index-forecast.json` (wird über RMSE/MAE beschreibend verglichen).
  - **Wahrscheinlichkeit ($P(Kp \ge 5)$):**
    - Da SWPC im Produkt `3-day-solar-geomag-predictions.txt` (bzw. dem korrespondierenden FTP-Produkt) keine planetare Sturmwahrscheinlichkeit vorhersagt, wird als Proxy **ausschließlich die Middle Latitude Wahrscheinlichkeit** genutzt, da subaurorale Stationen mittlerer Breite den planetaren Kp besser abbilden als High-Latitude-Stationen (welche Kp systematisch überschätzen würden).
    - $P_{SWPC}(Kp \ge 5) = Prob\_Mid(Minor\_Storm) + Prob\_Mid(Major\_Severe\_Storm)$.
    - **Fairness-Regel:** Da dieser Proxy nicht exakt das planetare Ereignis abbildet, wird vor der ersten Live-Vorhersage (aber nach dem Einfrieren der Preregistration) *vollautomatisch* eine Rekalibrierung des Mid-Proxys bestimmt: Über eine Platt-Skalierung (logistische Regression auf $logit(p)$) gegen GFZ-definitiv $Kp \ge 5.0$ auf historischen SWPC-Produkten (2010-01-01 bis 2025-12-31) je Tag +1/+2/+3. Dabei wird $p$ vor dem Logit fest auf das Intervall $[0.005, 0.995]$ begrenzt.
    - Als finale SWPC-Referenz für das harte Erfolgskriterium gilt diejenige Variante (Rohwert oder rekalibriert), die im historischen Zeitraum den besseren BSS (je Vorlauftag) aufweist. Diese Wahl trifft das Skript ohne jegliche Live-Daten. Die andere Variante wird rein beschreibend berichtet.
  - Maßgeblich ist stets das SWPC-Produkt, das um 22:00 UTC am selben Tag ausgegeben wurde und das wir in unserem Lauf mit archivieren.
  - Fehlende Werte im SWPC-Produkt werden als Vorhersagelücke gewertet und aus dem $\Delta\text{BSS}$ wie in §5 spezifiziert ausgeschlossen. Die exakte Abbildung der Tage auf +1/+2/+3 aus dem Produkt ist strikt: Tag +1 entspricht dem ersten UTC-Kalendertag nach dem Ausgabedatum des 22:00-UTC-Produkts (Zieltag), Tag +2 und Tag +3 entsprechend folgend.

## 9. Versionierungsregel
- **Unveränderbarkeit:** Nach dem Einfrieren dieses Dokuments wird das Modell `swcast-kp-baseline-v0` niemals aufgrund von Live-Ergebnissen oder im laufenden Betrieb angepasst.
- Jede methodische Verbesserung erhält eine neue Modellversion (z. B. `swcast-kp-baseline-v1`) mit eigenem Zeitstempel, eigener Preregistration und eigener paralleler Wertung.
