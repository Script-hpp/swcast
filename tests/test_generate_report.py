import numpy as np

from swcast.training.generate_report import classify, recalibrate_swpc


def test_recalibrate_swpc_identity_and_clip():
    p = np.array([0.0, 0.2, 0.5, 1.0])
    out = recalibrate_swpc(p, coef=1.0, intercept=0.0)
    # identity mapping inside the clip range, clipped at the edges
    np.testing.assert_allclose(out, [0.005, 0.2, 0.5, 0.995])


def test_classify_thresholds():
    assert classify(0.01) == "Übertreffen"
    assert classify(0.0) == "Mithalten"
    assert classify(-0.049) == "Mithalten"
    assert classify(-0.05) == "nicht erreicht"
