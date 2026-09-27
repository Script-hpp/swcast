import logging
import pandas as pd
import numpy as np
from sklearn.linear_model import LogisticRegression, Ridge
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import brier_score_loss, mean_squared_error
import json
from pathlib import Path

logger = logging.getLogger(__name__)

def perform_cv(df: pd.DataFrame, features: list[str], target: str, is_prob: bool, C_or_alpha_list: list[float]) -> tuple[float, dict, list]:
    """
    Rolling-Origin-CV from Y=2015 to 2025.
    Returns: best_param, cv_metrics_per_fold, final_coefs (dummy, just structure)
    """
    best_score = float('inf')
    best_param = None
    all_metrics = {}
    
    for param in C_or_alpha_list:
        scores = []
        for val_year in range(2015, 2026):
            # Train: 2005 to val_year - 1
            train_mask = df['run_date'].apply(lambda d: d.year < val_year)
            val_mask = df['run_date'].apply(lambda d: d.year == val_year)
            
            df_train = df[train_mask].dropna(subset=features + [target]).copy()
            df_val = df[val_mask].dropna(subset=features + [target]).copy()
            
            if df_train.empty or df_val.empty:
                continue
                
            X_train = df_train[features].values
            y_train = df_train[target].values
            X_val = df_val[features].values
            y_val = df_val[target].values
            
            scaler = StandardScaler()
            X_train_s = scaler.fit_transform(X_train)
            X_val_s = scaler.transform(X_val)
            
            if is_prob:
                model = LogisticRegression(C=param, solver='lbfgs', random_state=42, max_iter=1000)
                # target is bool but we need int for sklearn
                model.fit(X_train_s, y_train.astype(int))
                preds = model.predict_proba(X_val_s)[:, 1]
                score = brier_score_loss(y_val.astype(int), preds)
            else:
                model = Ridge(alpha=param, solver='svd', random_state=42)
                model.fit(X_train_s, y_train)
                preds = model.predict(X_val_s)
                score = np.sqrt(mean_squared_error(y_val, preds))
                
            scores.append(score)
            
        mean_score = np.mean(scores)
        if mean_score < best_score:
            best_score = mean_score
            best_param = param
            
    # Now run CV with best_param to capture fold metrics
    fold_metrics = []
    for val_year in range(2015, 2026):
        train_mask = df['run_date'].apply(lambda d: d.year < val_year)
        val_mask = df['run_date'].apply(lambda d: d.year == val_year)
        
        df_train = df[train_mask].dropna(subset=features + [target]).copy()
        df_val = df[val_mask].dropna(subset=features + [target]).copy()
        
        if df_train.empty or df_val.empty:
            continue
            
        X_train = df_train[features].values
        y_train = df_train[target].values
        X_val = df_val[features].values
        y_val = df_val[target].values
        
        scaler = StandardScaler()
        X_train_s = scaler.fit_transform(X_train)
        X_val_s = scaler.transform(X_val)
        
        # Calculate Climatology Baseline (which is just the 'climatology' feature itself!)
        # Wait, the prompt says "BSS gegen Klimatologie je Fold".
        # Let's extract the climatology feature for the validation set.
        clim_val = df_val['climatology'].values
        
        if is_prob:
            model = LogisticRegression(C=best_param, solver='lbfgs', random_state=42, max_iter=1000)
            model.fit(X_train_s, y_train.astype(int))
            preds = model.predict_proba(X_val_s)[:, 1]
            score = brier_score_loss(y_val.astype(int), preds)
            
            # BSS = 1 - Brier / Brier_clim
            brier_clim = brier_score_loss(y_val.astype(int), clim_val)
            bss = 1.0 - (score / brier_clim) if brier_clim > 0 else np.nan
            
            fold_metrics.append({
                "val_year": val_year,
                "score": score,
                "bss_clim": bss
            })
        else:
            model = Ridge(alpha=best_param, solver='svd', random_state=42)
            model.fit(X_train_s, y_train)
            preds = model.predict(X_val_s)
            score = np.sqrt(mean_squared_error(y_val, preds))
            fold_metrics.append({
                "val_year": val_year,
                "score": score
            })
            
    return best_param, fold_metrics


def train_final_model(df: pd.DataFrame, features: list[str], target: str, is_prob: bool, param: float) -> dict:
    """Trains final model on all data and returns artifact dict."""
    df_train = df.dropna(subset=features + [target]).copy()
    X = df_train[features].values
    y = df_train[target].values
    
    scaler = StandardScaler()
    X_s = scaler.fit_transform(X)
    
    if is_prob:
        model = LogisticRegression(C=param, solver='lbfgs', random_state=42, max_iter=1000)
        model.fit(X_s, y.astype(int))
    else:
        model = Ridge(alpha=param, solver='svd', random_state=42)
        model.fit(X_s, y)
        
    return {
        "features": features,
        "scaler_mean": scaler.mean_.tolist(),
        "scaler_scale": scaler.scale_.tolist(),
        "coef": model.coef_.tolist() if not is_prob else model.coef_[0].tolist(),
        "intercept": float(model.intercept_) if not is_prob else float(model.intercept_[0]),
        "param": param
    }

