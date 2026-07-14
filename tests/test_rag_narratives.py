"""Tests for behavioral-narrative RAG (utils/rag.py)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.rag import build_behavior_narrative, _keyword_search, _tokenize


def _participant(**challenges):
    base = {
        "championName": "Ahri", "teamPosition": "MIDDLE", "win": True,
        "kills": 8, "deaths": 2, "assists": 6, "totalDamageDealtToChampions": 25000,
        "totalTimeSpentDead": 30, "damageDealtToObjectives": 8000,
        "detectorWardsPlaced": 0, "wardsKilled": 0,
        "challenges": challenges,
    }
    return base


def test_narrative_describes_behavior_not_stats():
    p = _participant(
        maxCsAdvantageOnLaneOpponent=40, maxLevelLeadLaneOpponent=2,
        turretPlatesTaken=8, soloKills=3, teamDamagePercentage=0.35,
        damageTakenOnTeamPercentage=0.15,
    )
    text = build_behavior_narrative(p, game_min=30)
    lower = text.lower()
    # Behavioral verbs present
    assert "dominated lane" in lower
    assert "solo kills" in lower
    assert "fight carry" in lower
    # Not a bare stat line
    assert "cs/min" not in lower
    assert "kda" not in lower


def test_thin_summary_yields_no_narrative():
    # No challenges block -> nothing behavioral to say
    assert build_behavior_narrative({"championName": "Ahri", "teamPosition": "MID"}, 30) == ""
    # A challenges block with almost no signal stays under the 3-part threshold
    p = _participant(maxCsAdvantageOnLaneOpponent=1)
    assert build_behavior_narrative(p, game_min=12) == ""


def test_death_discipline_narrative():
    # Realistic participant: high deaths plus other behavioral signal so the
    # narrative crosses the min-signal threshold and includes the death line.
    p = _participant(win=False, soloKills=2, dragonTakedowns=2,
                     maxCsAdvantageOnLaneOpponent=25, turretPlatesTaken=6)
    p["deaths"] = 8
    p["totalTimeSpentDead"] = 200
    text = build_behavior_narrative(p, game_min=32).lower()
    assert "died 8 times" in text


def test_keyword_search_ranks_by_overlap():
    corpus = [
        {"content": "Challenger Lux support used vision to set up dragons and deny picks", "champion": "Lux"},
        {"content": "Challenger Darius top dominated lane with a big CS lead", "champion": "Darius"},
    ]
    import utils.rag as rag
    rag._load_narratives.cache_clear()
    rag.NARRATIVES_FILE = type(rag.NARRATIVES_FILE)("/nonexistent")  # force use of monkeypatched loader
    rag._load_narratives = lambda: tuple(corpus)  # type: ignore
    hits = _keyword_search("vision to set up objectives and deny enemy picks", k=1)
    assert hits and hits[0]["champion"] == "Lux"


def test_tokenize_drops_stopwords():
    toks = _tokenize("how they played the game well")
    assert "how" not in toks and "the" not in toks
