import logging
from pathlib import Path
from datetime import datetime, timezone, timedelta
import pandas as pd
import numpy as np

from swcast.config import load_config
from swcast.fetch.swpc import fetch_historical_rsga
from swcast.fetch.kp import fetch_training_data
from swcast.fetch.solarwind import fetch_omni_historical, compute_2h_features, FallbackError

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def generate_coverage_report():
    cfg = load_config()
    reports_dir = Path(cfg["paths"]["reports_dir"])
    reports_dir.mkdir(parents=True, exist_ok=True)
    report_path = reports_dir / "data_coverage.md"
    
    with open(report_path, "w") as f:
        f.write("# Data Coverage Report\n\n")
        f.write("## RSGA (2010-2025)\n\n")
        f.write("| Year | Parsed (Used) | Excluded (Time) | Excluded (Dates) | Parse Errors | Missing |\n")
        f.write("|------|---------------|-----------------|------------------|--------------|---------|\n")
        
        # We need to capture the logs or just rewrite the loop to collect stats
        # For simplicity, we can fetch all and we already have logs, but wait: the prompt asks to report these in the table.
        # Let's import the internals or copy the logic to get stats.
        # It's cleaner to modify `fetch_historical_rsga` to return stats, but we can't change signature easily without breaking things.
        # Actually, `fetch_historical_rsga` just returns the df. Let's just do a manual loop here to generate exact stats for the report.
        
        from swcast.fetch.swpc import SWPC_FTP_BASE, _get_cache_dir, parse_rsga, fetch_historical_rsga
        import tarfile
        
        # Ensure all data is downloaded first
        try:
            fetch_historical_rsga(2010, 2025)
        except Exception as e:
            logger.warning(f"Failed to fetch some RSGA: {e}")

        cache_dir = _get_cache_dir()
        for year in range(2010, 2026):
            tar_filename = f"{year}_RSGA.tar.gz"
            cache_path = cache_dir / tar_filename
            
            valid_count = 0
            parse_errors = 0
            excluded_time = 0
            excluded_dates = 0
            
            if cache_path.exists():
                with tarfile.open(cache_path, "r:gz") as tar:
                    members = [m for m in tar.getmembers() if m.name.endswith("RSGA.txt")]
                    for member in members:
                        m_name = member.name.split("/")[-1]
                        m_date_str = m_name[:8]
                        try:
                            file_date = pd.to_datetime(m_date_str, format="%Y%m%d").date()
                        except Exception:
                            continue
                            
                        file_obj = tar.extractfile(member)
                        if file_obj:
                            text = file_obj.read().decode("utf-8", errors="replace")
                            try:
                                df = parse_rsga(text)
                            except Exception:
                                parse_errors += 1
                                continue
                                
                            issue_time = df["issue_time"].iloc[0]
                            target_date_1 = df["target_date"].iloc[0]
                            
                            if issue_time >= pd.Timestamp(target_date_1, tz=timezone.utc):
                                excluded_time += 1
                                continue
                                
                            expected_target_1 = file_date + timedelta(days=1)
                            if target_date_1 != expected_target_1:
                                excluded_dates += 1
                                continue
                                
                            valid_count += 1
            expected = 365 if year % 4 != 0 else 366
            missing = expected - valid_count
            f.write(f"| {year} | {valid_count} | {excluded_time} | {excluded_dates} | {parse_errors} | {missing} |\n")
            
        f.write("\n## GFZ Kp Definitive (2005-2025)\n\n")
        f.write("| Year | Total 3h Values | Gaps |\n")
        f.write("|------|-----------------|------|\n")
        
        df_kp = fetch_training_data(2005, 2025)
        df_kp['year'] = df_kp['time'].dt.year
        kp_stats = df_kp.groupby('year').agg(
            total=('time', 'count'),
            gaps=('is_gap', 'sum')
        ).reset_index()
        
        for _, row in kp_stats.iterrows():
            f.write(f"| {int(row['year'])} | {int(row['total'])} | {int(row['gaps'])} |\n")
            
        f.write("\n## OMNI 1-min (2005-2025)\n\n")
        f.write("| Year | Valid Minutes % | Fallback 22:30 Runs % |\n")
        f.write("|------|-----------------|-----------------------|\n")
        
        for year in range(2005, 2026):
            try:
                df_omni = fetch_omni_historical(year)
                # fraction of minutes with all 4 valid variables
                df_omni['is_valid'] = df_omni[['by_gsm', 'bz_gsm', 'speed', 'density']].notna().all(axis=1)
                valid_pct = df_omni['is_valid'].mean() * 100.0
                
                # Check 22:30 runs
                # Runs happen daily at 22:30 UTC. Window is 20:30 to 22:30.
                dates = pd.date_range(start=f"{year}-01-01 22:30", end=f"{year}-12-31 22:30", freq="D", tz=timezone.utc)
                fallback_count = 0
                for d in dates:
                    try:
                        compute_2h_features(df_omni, d)
                    except FallbackError:
                        fallback_count += 1
                        
                fallback_pct = fallback_count / len(dates) * 100.0
                f.write(f"| {year} | {valid_pct:.2f}% | {fallback_pct:.2f}% ({fallback_count}/{len(dates)}) |\n")
            except Exception as e:
                logger.error(f"Error processing OMNI {year}: {e}")
                f.write(f"| {year} | Error | Error |\n")

    logger.info(f"Coverage report generated at {report_path}")

if __name__ == "__main__":
    generate_coverage_report()
