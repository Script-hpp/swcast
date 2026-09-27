import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import brier_score_loss

from swcast.fetch.swpc import fetch_historical_rsga
from swcast.fetch.kp import fetch_training_data, daily_storm_label

def platt_scale_swpc():
    """
    Recalibrate SWPC probabilities (Mid) to predict planetary Kp >= 5.0.
    Returns best variant (raw or recalibrated) per day ahead.
    """
    df_swpc = fetch_historical_rsga(2010, 2025)
    
    # We need GFZ definitive labels for target dates
    df_kp = fetch_training_data(2010, 2025)
    df_daily = daily_storm_label(df_kp)
    
    # Merge SWPC with GFZ labels
    # We only care about day +1, +2, +3 relative to issue date?
    # Actually SWPC targets are already in target_date.
    
    # Convert dates to match
    df_daily['date'] = pd.to_datetime(df_daily['date']).dt.date
    df_swpc['target_date'] = pd.to_datetime(df_swpc['target_date']).dt.date
    
    df_merged = pd.merge(df_swpc, df_daily, left_on='target_date', right_on='date', how='inner')
    
    # Filter out NaNs
    df_merged = df_merged.dropna(subset=['storm_label'])
    
    results = {}
    
    for i in range(1, 4):
        # Filter for day + i
        # SWPC issue_date + i = target_date. 
        # Wait, for a 22:00 product, issue_time is e.g. 2010-09-14 22:00. target_date for day + 1 is 2010-09-15.
        # Let's compute day_ahead directly: target_date - issue_time.floor('D')
        df_merged['day_ahead'] = (pd.to_datetime(df_merged['target_date']) - pd.to_datetime(df_merged['issue_time']).dt.floor('D')).dt.days
        
        df_day = df_merged[df_merged['day_ahead'] == i].copy()
        
        if df_day.empty:
            continue
            
        p = df_day['p_storm'].values
        y = df_day['storm_label'].values.astype(int)
        
        # Raw BSS
        brier_raw = brier_score_loss(y, p)
        # Climatology for BSS: fraction of positives in the whole training set? Or per day?
        # Standard BSS uses sample climatology.
        clim = np.mean(y)
        brier_clim = brier_score_loss(y, np.full_like(y, clim, dtype=float))
        bss_raw = 1 - brier_raw / brier_clim if brier_clim > 0 else np.nan
        
        # Platt Scaling
        p_clip = np.clip(p, 0.005, 0.995)
        # logit(p)
        logit_p = np.log(p_clip / (1 - p_clip)).reshape(-1, 1)
        
        # Fit logistic regression on logit(p)
        lr = LogisticRegression(penalty=None, solver='lbfgs')
        lr.fit(logit_p, y)
        
        p_calib = lr.predict_proba(logit_p)[:, 1]
        brier_calib = brier_score_loss(y, p_calib)
        bss_calib = 1 - brier_calib / brier_clim if brier_clim > 0 else np.nan
        
        # Choose best
        use_calib = bss_calib > bss_raw
        
        results[str(i)] = {
            "use_calib": bool(use_calib),
            "bss_raw": float(bss_raw),
            "bss_calib": float(bss_calib),
            "coef": float(lr.coef_[0][0]),
            "intercept": float(lr.intercept_[0])
        }
        
    return results
