"""Generate reports/training_v0.md from the frozen v0 training artifacts.

Purely descriptive. Nothing here changes the model: it re-runs the same
rolling-origin CV (PREREGISTRATION.md §7) with the already chosen
hyperparameters to obtain out-of-sample predictions, then reports
coefficients, CV scores, reliability and a paired historical comparison
against SWPC.

The SWPC comparison uses the same reference and the same bootstrap as the
live success criterion (PREREGISTRATION.md §4/§5): rolling 365-day
climatology, 27-day blocks, 10,000 resamples, seed 2026, percentile CI.
It does NOT count for the criterion. The SWPC recalibration used here is
in-sample over 2010-2025, which favours SWPC.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from swcast.config import load_config
from swcast.fetch.swpc import fetch_historical_rsga
from swcast.metrics import block_bootstrap_ci, brier_skill_score
from swcast.training.train import perform_cv

REPO_DIR = Path(__file__).resolve().parents[3]
MODELS_DIR = REPO_DIR / "models" / "swcast-kp-baseline-v0"

PLATT_CLIP = (0.005, 0.995)
BOOTSTRAP_ITERATIONS = 10_000
BOOTSTRAP_SEED = 2026
BLOCK_DAYS = 27
KEEP_UP_MARGIN = -0.05


def recalibrate_swpc(p_raw: np.ndarray, coef: float, intercept: float) -> np.ndarray:
    """Platt scaling as fitted in swpc_recal.py: sigmoid(coef * logit(clip(p)) + intercept)."""
    p = np.clip(p_raw, *PLATT_CLIP)
    logit = np.log(p / (1.0 - p))
    return 1.0 / (1.0 + np.exp(-(coef * logit + intercept)))


def oos_predictions(df_day: pd.DataFrame, art_main: dict, art_fb: dict) -> pd.DataFrame:
    """Out-of-sample p_storm per target date, choosing main or fallback model
    exactly as live: main model when the run had valid L1, else fallback."""
    df_main = df_day[df_day["l1_valid"]]
    _, folds_main = perform_cv(df_main, art_main["features"], "target_storm", True, [art_main["param"]])
    _, folds_fb = perform_cv(df_day, art_fb["features"], "target_storm", True, [art_fb["param"]])

    main = pd.concat(
        pd.DataFrame({"target_date": f["dates"], "p_main": f["preds"]}) for f in folds_main
    )
    fb = pd.concat(
        pd.DataFrame(
            {"target_date": f["dates"], "p_fb": f["preds"], "target": f["targets"], "clim": f["clim_val"]}
        )
        for f in folds_fb
    )
    out = fb.merge(main, on="target_date", how="left")
    out["p_swcast"] = out["p_main"].fillna(out["p_fb"])
    out["model_used"] = np.where(out["p_main"].notna(), "main", "fallback")
    out["target"] = out["target"].astype(float)
    return out.drop(columns=["p_main", "p_fb"]).reset_index(drop=True)


def format_model(title: str, art: dict, folds: list[dict], is_prob: bool) -> list[str]:
    lines = [f"#### {title}", "", f"- Gewählter Parameter ({'C' if is_prob else 'alpha'}): {art['param']}"]
    lines.append(f"- Intercept: {art['intercept']:.4f}")
    lines.append("- Koeffizienten (standardisierte Merkmale):")
    lines.extend(f"  - `{f}`: {c:+.4f}" for f, c in zip(art["features"], art["coef"]))
    lines.append("")
    if is_prob:
        lines += ["| Validierungsjahr | Brier | BSS vs. Klimatologie |", "| --- | --- | --- |"]
        lines += [f"| {m['val_year']} | {m['score']:.4f} | {m['bss_clim']:.4f} |" for m in folds]
        lines.append(
            f"| **Mittel** | {np.mean([m['score'] for m in folds]):.4f} | {np.mean([m['bss_clim'] for m in folds]):.4f} |"
        )
    else:
        lines += ["| Validierungsjahr | RMSE |", "| --- | --- |"]
        lines += [f"| {m['val_year']} | {m['score']:.4f} |" for m in folds]
        lines.append(f"| **Mittel** | {np.mean([m['score'] for m in folds]):.4f} |")
    lines.append("")
    return lines


def reliability_table(p: np.ndarray, y: np.ndarray) -> list[str]:
    lines = ["| Bin | mittlere Vorhersage | beobachtete Rate | n |", "| --- | --- | --- | --- |"]
    edges = np.linspace(0.0, 1.0, 11)
    bin_idx = np.clip(np.digitize(p, edges[1:-1]), 0, 9)
    for j in range(10):
        mask = bin_idx == j
        if mask.any():
            lines.append(
                f"| [{edges[j]:.1f}, {edges[j + 1]:.1f}) | {p[mask].mean():.3f} | {y[mask].mean():.3f} | {int(mask.sum())} |"
            )
    lines.append("")
    return lines


def classify(ci_low: float) -> str:
    if ci_low > 0:
        return "Übertreffen"
    if ci_low > KEEP_UP_MARGIN:
        return "Mithalten"
    return "nicht erreicht"


def paired_comparison(oos: pd.DataFrame, swpc_day: pd.DataFrame, recal: dict) -> tuple[dict, pd.DataFrame]:
    merged = oos.merge(swpc_day[["target_date", "p_storm"]], on="target_date", how="inner").dropna(
        subset=["p_storm"]
    )
    merged = merged.sort_values("target_date").reset_index(drop=True)
    merged["p_swpc_raw"] = merged["p_storm"].to_numpy()
    merged["p_swpc_recal"] = recalibrate_swpc(merged["p_swpc_raw"].to_numpy(), recal["coef"], recal["intercept"])

    day_index = pd.to_datetime(merged["target_date"]).map(pd.Timestamp.toordinal).to_numpy()
    y, clim, p_sw = (merged[c].to_numpy() for c in ("target", "clim", "p_swcast"))

    result = {"n": len(merged), "bss_swcast": brier_skill_score(y, p_sw, clim)}
    for variant in ("raw", "recal"):
        p_ref = merged[f"p_swpc_{variant}"].to_numpy()
        result[f"bss_swpc_{variant}"] = brier_skill_score(y, p_ref, clim)
        values = np.column_stack([y, p_sw, p_ref, clim])

        def delta_bss(v: np.ndarray) -> float:
            return brier_skill_score(v[:, 0], v[:, 1], v[:, 3]) - brier_skill_score(v[:, 0], v[:, 2], v[:, 3])

        point, lo, hi = block_bootstrap_ci(
            values, day_index, delta_bss, block_length_days=BLOCK_DAYS,
            n_iterations=BOOTSTRAP_ITERATIONS, ci=0.95, seed=BOOTSTRAP_SEED,
        )
        result[f"delta_{variant}"] = (point, lo, hi)
    return result, merged


def main() -> None:
    cfg = load_config()
    artifacts = json.loads((MODELS_DIR / "model_artifacts.json").read_text())
    df = pd.read_parquet(Path(cfg["data_dir"]) / "training_data_v0.parquet")

    swpc = fetch_historical_rsga(2010, 2025)
    issue_day = pd.to_datetime(swpc["issue_time"]).dt.tz_localize(None).dt.floor("D")
    swpc["target_date"] = pd.to_datetime(swpc["target_date"]).dt.date
    swpc["day_ahead"] = (pd.to_datetime(swpc["target_date"]) - issue_day).dt.days

    lines = [
        "# Training Report (swcast-kp-baseline-v0)",
        "",
        "Erzeugt von `src/swcast/training/generate_report.py` aus `models/swcast-kp-baseline-v0/model_artifacts.json` "
        f"(Datensatz-SHA-256 `{artifacts['dataset_sha256']}`, Trainings-Commit `{artifacts['git_commit']}`).",
        "",
        "## Implementierungsentscheidungen",
        "",
        "- Solver: `lbfgs` für LogisticRegression, `svd` für Ridge (deterministisch).",
        "- CV-Split nach `target_date`; BSS in der CV gegen das Merkmal `climatology` (Sturmtag-Rate der 365 Tage bis D−1).",
        "- Platt-Skalierung der SWPC-Proxys: `LogisticRegression(penalty=None)` auf logit(clip(p, 0.005, 0.995)).",
        "- Out-of-sample-Vorhersagen: Hauptmodell, wenn der simulierte Lauf gültige L1-Daten hatte (60/120-Regel), sonst Rückfallmodell – wie im Live-Betrieb.",
        "",
    ]
    comparison_lines = [
        "## Historischer Vorab-Vergleich mit SWPC (2015–2025)",
        "",
        "> **Nur beschreibend, zählt nicht für das Erfolgskriterium.** Gepaarte Out-of-Sample-Vorhersagen von swcast "
        "gegen SWPC (Middle-Latitude-Proxy, roh und rekalibriert) auf denselben Zieltagen. Referenz beider BSS: rollierende "
        "365-Tage-Klimatologie (PREREGISTRATION §4). ΔBSS = BSS(swcast) − BSS(SWPC), 95-%-KI per Block-Bootstrap "
        f"({BLOCK_DAYS}-Tage-Blöcke, {BOOTSTRAP_ITERATIONS} Resamples, Seed {BOOTSTRAP_SEED}, Perzentilmethode). "
        "Die SWPC-Rekalibrierung ist hier in-sample über 2010–2025 gefittet, was SWPC begünstigt.",
        "",
        "| Tag | n | BSS swcast | BSS SWPC roh | BSS SWPC rekal. | ΔBSS vs. roh [95-%-KI] | ΔBSS vs. rekal. [95-%-KI] | Einordnung (vs. Referenzvariante) |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]

    for lead in (1, 2, 3):
        df_day = df[df["target_day_ahead"] == lead]
        models = artifacts["models"][str(lead)]
        n_main = int(df_day["l1_valid"].sum())
        lines += [f"## Vorlauftag +{lead}", "", f"Läufe mit gültigem L1 (Hauptmodell): {n_main} / {len(df_day)} ({n_main / len(df_day):.1%})", ""]

        for key, title, target, is_prob, data in (
            ("p_storm_main", "p_storm – Hauptmodell", "target_storm", True, df_day[df_day["l1_valid"]]),
            ("p_storm_fallback", "p_storm – Rückfallmodell", "target_storm", True, df_day),
            ("kp_max_main", "kp_max – Hauptmodell", "target_kp_max", False, df_day[df_day["l1_valid"]]),
            ("kp_max_fallback", "kp_max – Rückfallmodell", "target_kp_max", False, df_day),
        ):
            art = models[key]
            _, folds = perform_cv(data, art["features"], target, is_prob, [art["param"]])
            lines += format_model(title, art, folds, is_prob)

        oos = oos_predictions(df_day, models["p_storm_main"], models["p_storm_fallback"])
        lines += [f"#### Reliability p_storm (out-of-sample 2015–2025, n = {len(oos)})", ""]
        lines += reliability_table(oos["p_swcast"].to_numpy(), oos["target"].to_numpy())

        recal = artifacts["swpc_recalibration"][str(lead)]
        res, _ = paired_comparison(oos, swpc[swpc["day_ahead"] == lead], recal)
        reference = "recal" if recal["use_calib"] else "raw"
        _, ref_lo, _ = res[f"delta_{reference}"]
        fmt = lambda d: f"{d[0]:+.4f} [{d[1]:+.4f}, {d[2]:+.4f}]"  # noqa: E731
        comparison_lines.append(
            f"| +{lead} | {res['n']} | {res['bss_swcast']:.4f} | {res['bss_swpc_raw']:.4f} | {res['bss_swpc_recal']:.4f} "
            f"| {fmt(res['delta_raw'])} | {fmt(res['delta_recal'])} | {classify(ref_lo)} ({'rekal.' if reference == 'recal' else 'roh'}) |"
        )

    comparison_lines += [
        "",
        "Referenzvariante je Tag nach PREREGISTRATION §8: die SWPC-Variante mit dem besseren historischen BSS (siehe `swpc_recalibration` in den Artefakten).",
        "",
    ]
    (REPO_DIR / "reports" / "training_v0.md").write_text("\n".join(lines + comparison_lines))


if __name__ == "__main__":
    main()
