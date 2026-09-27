import pandas as pd
import pytest

from swcast.fetch.swpc import parse_rsga, parse_daypre

def test_parse_rsga():
    text = """
:Product: 0101RSGA.txt
:Issued: 2024 Jan 01 2200 UTC
# Prepared jointly by the U.S. Dept. of Commerce, NOAA,

IA.  Analysis of Solar Active Regions

IIA.  Geophysical Activity Summary 31/2100Z to 01/2100Z

VI.  Geomagnetic Activity Probabilities 02 Jan-04 Jan
A.  Middle Latitudes
Active                40/30/20
Minor Storm           25/15/05
Major-severe storm    05/01/01
B.  High Latitudes
Active                10/15/15
Minor Storm           25/30/25
Major-severe storm    60/45/25
"""
    df = parse_rsga(text)
    
    assert len(df) == 3
    assert df.iloc[0]["issue_time"].strftime("%Y-%m-%d %H:%M") == "2024-01-01 22:00"
    
    # Tag +1 is 2024-01-02
    assert df.iloc[0]["target_date"].strftime("%Y-%m-%d") == "2024-01-02"
    assert df.iloc[0]["p_minor_storm"] == pytest.approx(0.25)
    assert df.iloc[0]["p_major_severe_storm"] == pytest.approx(0.05)
    assert df.iloc[0]["p_storm"] == pytest.approx(0.30)
    
    # Tag +2 is 2024-01-03
    assert df.iloc[1]["target_date"].strftime("%Y-%m-%d") == "2024-01-03"
    assert df.iloc[1]["p_minor_storm"] == pytest.approx(0.15)
    
def test_parse_daypre():
    text = """
:Product: 3-day Space Weather Predictions daypre.txt
:Issued: 2026 Sep 26 2200 UTC

:Prediction_dates:   2026 Sep 27   2026 Sep 28   2026 Sep 29

:Prob_Mid:
Mid/Active               10             5            10
Mid/Minor_Storm           5            10             1
Mid/Major-Severe_Storm    2             1             0
"""
    df = parse_daypre(text)
    assert len(df) == 3
    assert df.iloc[0]["target_date"].strftime("%Y-%m-%d") == "2026-09-27"
    assert df.iloc[0]["p_minor_storm"] == pytest.approx(0.05)
    assert df.iloc[0]["p_major_severe_storm"] == pytest.approx(0.02)
    
    assert df.iloc[1]["target_date"].strftime("%Y-%m-%d") == "2026-09-28"
    assert df.iloc[1]["p_minor_storm"] == pytest.approx(0.10)
    assert df.iloc[1]["p_major_severe_storm"] == pytest.approx(0.01)

def test_parse_rsga_missing_fields():
    text = """
:Issued: 2024 Jan 01 2200 UTC
VI.  Geomagnetic Activity Probabilities 02 Jan-04 Jan
A.  Middle Latitudes
Active                40/30/20
"""
    with pytest.raises(ValueError, match="Could not find required probability fields"):
        parse_rsga(text)
