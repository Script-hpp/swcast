import logging
import json
import subprocess
from pathlib import Path

from swcast.config import load_config
from swcast.training.dataset import build_training_dataset
from swcast.training.train import perform_cv, train_final_model
from swcast.training.swpc_recal import platt_scale_swpc

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def run_pipeline():
    cfg = load_config()
    reports_dir = Path(cfg["paths"]["reports_dir"])
    reports_dir.mkdir(parents=True, exist_ok=True)
    models_dir = cfg["data_dir"] / "models" / "swcast-kp-baseline-v0"
    models_dir.mkdir(parents=True, exist_ok=True)
    
    logger.info("Building training dataset...")
    df = build_training_dataset(2005, 2025)
    
    # Save dataset to compute SHA256 later
    dataset_path = models_dir / "training_data.parquet"
    df.to_parquet(dataset_path, index=False)
    
    # Compute SHA256
    import hashlib
    with open(dataset_path, "rb") as f:
        ds_hash = hashlib.sha256(f.read()).hexdigest()
        
    git_commit = subprocess.check_output(["git", "rev-parse", "HEAD"]).decode().strip()
    
    logger.info("Running CV and training models...")
    
    features_main = ["persistence", "recurrence", "climatology", "l1_bz_gsm", "l1_by_gsm", "l1_speed", "l1_dyn_pressure", "l1_newell"]
    features_fallback = ["persistence", "recurrence", "climatology"]
    
    report_lines = []
    report_lines.append("# Training Report (swcast-kp-baseline-v0)\n")
    
    report_lines.append("## Implementierungsentscheidungen\n")
    report_lines.append("- **Solver**: `lbfgs` für LogisticRegression, `svd` für Ridge (beide deterministisch, `random_state=42`).")
    report_lines.append("- **BSS Klimatologie-Referenz**: In der CV wird der BSS mit dem `climatology`-Feature (Rate der letzten 365 Tage) als Referenz auf dem Validierungsjahr berechnet.")
    report_lines.append("- **Platt-Skalierung**: `LogisticRegression(penalty=None, solver='lbfgs')` ohne Regularisierung auf den Intervallen $[0.005, 0.995]$.")
    report_lines.append("\n")
    
    artifacts = {
        "dataset_sha256": ds_hash,
        "git_commit": git_commit,
        "models": {}
    }
    
    c_list = [0.01, 0.1, 1, 10]
    
    for i in range(1, 4):
        logger.info(f"Training day +{i} models...")
        report_lines.append(f"## Vorlauftag +{i}\n")
        
        df_day = df[df["target_day_ahead"] == i].copy()
        df_main = df_day[df_day["l1_valid"] == True].copy()
        
        report_lines.append(f"Anteil der Läufe mit gültigem L1 (Hauptmodell): {len(df_main)} / {len(df_day)} ({len(df_main)/len(df_day)*100:.1f}%)\n")
        
        artifacts["models"][str(i)] = {}
        
        # p_storm Main
        best_c, fold_metrics = perform_cv(df_main, features_main, "target_storm", is_prob=True, C_or_alpha_list=c_list)
        art_main_p = train_final_model(df_main, features_main, "target_storm", True, best_c)
        artifacts["models"][str(i)]["p_storm_main"] = art_main_p
        
        avg_brier = sum([m["score"] for m in fold_metrics]) / len(fold_metrics)
        avg_bss = sum([m["bss_clim"] for m in fold_metrics if pd.notna(m["bss_clim"])]) / len(fold_metrics)
        report_lines.append(f"### p_storm (Hauptmodell)\n- Gewähltes C: {best_c}")
        report_lines.append("- **CV per Fold (Brier | BSS vs Clim)**:")
        for m in fold_metrics:
            report_lines.append(f"  - {m['val_year']}: {m['score']:.4f} | {m['bss_clim']:.4f}")
        report_lines.append(f"- Mean: Brier {avg_brier:.4f}, BSS {avg_bss:.4f}\n")
        
        # p_storm Fallback
        best_c_fb, fold_metrics_fb = perform_cv(df_day, features_fallback, "target_storm", is_prob=True, C_or_alpha_list=c_list)
        art_fb_p = train_final_model(df_day, features_fallback, "target_storm", True, best_c_fb)
        artifacts["models"][str(i)]["p_storm_fallback"] = art_fb_p
        
        # kp_max Main
        best_a, fold_metrics_kp = perform_cv(df_main, features_main, "target_kp_max", is_prob=False, C_or_alpha_list=c_list)
        art_main_k = train_final_model(df_main, features_main, "target_kp_max", False, best_a)
        artifacts["models"][str(i)]["kp_max_main"] = art_main_k
        
        avg_rmse = sum([m["score"] for m in fold_metrics_kp]) / len(fold_metrics_kp)
        report_lines.append(f"### kp_max (Hauptmodell)\n- Gewähltes alpha: {best_a}")
        report_lines.append("- **CV per Fold (RMSE)**:")
        for m in fold_metrics_kp:
            report_lines.append(f"  - {m['val_year']}: {m['score']:.4f}")
        report_lines.append(f"- Mean RMSE: {avg_rmse:.4f}\n")
        
        # kp_max Fallback
        best_a_fb, fold_metrics_kp_fb = perform_cv(df_day, features_fallback, "target_kp_max", is_prob=False, C_or_alpha_list=c_list)
        art_fb_k = train_final_model(df_day, features_fallback, "target_kp_max", False, best_a_fb)
        artifacts["models"][str(i)]["kp_max_fallback"] = art_fb_k
        
    logger.info("Running SWPC recalibration...")
    recal_results = platt_scale_swpc()
    artifacts["swpc_recalibration"] = recal_results
    
    report_lines.append("## SWPC Rekalibrierung (2010-2025)\n")
    for i in range(1, 4):
        rr = recal_results[str(i)]
        report_lines.append(f"**Tag +{i}**: Nutze {'Rekalibriert' if rr['use_calib'] else 'Rohwerte'}.")
        report_lines.append(f"BSS roh: {rr['bss_raw']:.4f}, BSS rekalibriert: {rr['bss_calib']:.4f}\n")
        
    # Save artifacts
    with open(models_dir / "model_artifacts.json", "w") as f:
        json.dump(artifacts, f, indent=2)
        
    # Save report
    with open(reports_dir / "training_v0.md", "w") as f:
        f.write("\n".join(report_lines))
        
    logger.info("Done.")

if __name__ == "__main__":
    run_pipeline()
