# swcast

Space weather forecast: tägliche Vorhersagen von Flares (GOES/XRS) und Kp, eingefroren vor
Eintreten und nachträglich öffentlich ausgewertet. Details siehe [PRD.md](PRD.md).

## Setup

```bash
conda env create -f environment.yml
conda activate swcast
```

Konfiguration in `config.yaml` (Datenpfad, Zeiträume, Lauf-Uhrzeit).

## Status

Meilenstein 0 (Benchmark) und Meilenstein 1 (Kp-Baseline live) in Arbeit — siehe PRD Abschnitt 9
für die Aufgabenreihenfolge.
