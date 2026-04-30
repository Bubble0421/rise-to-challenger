from services.confidence_service import get_confidence_label


def test_confidence_thresholds():
    assert get_confidence_label(150) == "High Confidence"
    assert get_confidence_label(60) == "Medium Confidence"
    assert get_confidence_label(20) == "Low Sample"
    assert get_confidence_label(19) == "Insufficient Data"
