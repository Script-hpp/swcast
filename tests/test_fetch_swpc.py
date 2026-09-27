import pandas as pd
import pytest

from swcast.fetch.swpc import parse_rsga

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
    assert df.iloc[0]["p_minor_storm"] == 0.25
    assert df.iloc[0]["p_major_severe_storm"] == 0.05
    assert df.iloc[0]["p_storm"] == pytest.approx(0.30)
    
    # Tag +2 is 2024-01-03
    assert df.iloc[1]["target_date"].strftime("%Y-%m-%d") == "2024-01-03"
    assert df.iloc[1]["p_minor_storm"] == 0.15
    assert df.iloc[1]["p_major_severe_storm"] == 0.01
    assert df.iloc[1]["p_storm"] == pytest.approx(0.16)
    
    # Tag +3 is 2024-01-04
    assert df.iloc[2]["target_date"].strftime("%Y-%m-%d") == "2024-01-04"
    assert df.iloc[2]["p_minor_storm"] == 0.05
    assert df.iloc[2]["p_major_severe_storm"] == 0.01
    assert df.iloc[2]["p_storm"] == pytest.approx(0.06)

def test_parse_rsga_missing_fields():
    text = """
:Issued: 2024 Jan 01 2200 UTC
VI.  Geomagnetic Activity Probabilities 02 Jan-04 Jan
A.  Middle Latitudes
Active                40/30/20
"""
    with pytest.raises(ValueError, match="Could not find required probability fields"):
        parse_rsga(text)
