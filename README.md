# swcast

Space weather forecast: tägliche Vorhersagen von Flares (GOES/XRS) und Kp, eingefroren vor
Eintreten und nachträglich öffentlich ausgewertet. Details siehe [PRD.md](PRD.md).

## Setup

```bash
# Optional: uv installieren, falls nicht vorhanden
pip install --user uv

# Pinned Environment (Python 3.12) ohne Conda erstellen
uv venv -p 3.12 .venv
source .venv/bin/activate

# Abhängigkeiten installieren (siehe environment.yml)
uv pip install pandas==2.2.* numpy==1.26.* scipy==1.13.* scikit-learn==1.5.* pyarrow==16.* requests==2.32.* pyyaml==6.0.* matplotlib==3.9.* pytest==8.* xarray==2024.* netcdf4==1.6.* opentimestamps-client==0.7.1
```

Konfiguration in `config.yaml` (Datenpfad, Zeiträume, Lauf-Uhrzeit).

## Status

Meilenstein 0 (Benchmark) und Meilenstein 1 (Kp-Baseline live) in Arbeit — siehe PRD Abschnitt 9
für die Aufgabenreihenfolge.
