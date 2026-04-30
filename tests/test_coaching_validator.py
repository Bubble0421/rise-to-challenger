from features.coaching.validators import judge_coaching_output


def test_coaching_validator_requires_diagnostic_labels_and_grounding():
    text = (
        "Main Diagnosis: Evidence: Vision 80 vs avg 60. Meaning: fog setup was a strength. Action: repeat river setup before objective spawn.\n"
        "Lane Phase: Evidence: CS@10 62 vs enemy 70. Meaning: wave control lagged. Action: stabilize wave before roaming.\n"
        "Threat Handling: Evidence: enemy Akali present. Meaning: flank threat changes spell usage. Action: hold Q for flank pressure."
    )

    passed, feedback = judge_coaching_output({"draft": text, "labels": ("Main Diagnosis", "Lane Phase", "Threat Handling")})

    assert passed, feedback
