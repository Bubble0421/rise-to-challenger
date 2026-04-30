"""Shared confidence labels used across all three pages."""

def get_confidence_label(games: int) -> str:
    if games >= 150: return "High Confidence"
    if games >= 60:  return "Medium Confidence"
    if games >= 20:  return "Low Sample"
    return "Insufficient Data"

def get_confidence_color(label: str) -> str:
    return {
        "High Confidence":   "#1D9E75",
        "Medium Confidence": "#C8AA6E",
        "Low Sample":        "#E8884A",
        "Insufficient Data": "#8A9AB5",
    }.get(label, "#8A9AB5")

def get_confidence_dot(label: str) -> str:
    return "⚠" if label == "Low Sample" else "●"

def confidence_badge(games: int) -> str:
    """Return an inline HTML badge for embedding in tier list rows."""
    label = get_confidence_label(games)
    color = get_confidence_color(label)
    dot   = get_confidence_dot(label)
    return (
        f"<span style='color:{color};font-size:11px;white-space:nowrap;'>"
        f"{dot} {label}</span>"
    )
