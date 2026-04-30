from utils.timeline import build_replay_checkpoints, classify_first_death, parse_timeline


def test_classify_first_death_boundaries():
    assert classify_first_death(None) == "No deaths recorded"
    assert classify_first_death(4.9).startswith("Very early")
    assert classify_first_death(9.9).startswith("Early")
    assert classify_first_death(14.9).startswith("Mid")
    assert classify_first_death(15).startswith("Post")


def test_parse_timeline_extracts_cs_gold_and_first_death():
    timeline = {
        "info": {
            "frames": [
                {
                    "timestamp": 600000,
                    "participantFrames": {
                        "1": {"minionsKilled": 70, "jungleMinionsKilled": 3, "totalGold": 4000},
                        "2": {"minionsKilled": 65, "jungleMinionsKilled": 0, "totalGold": 3800},
                    },
                    "events": [
                        {"type": "CHAMPION_KILL", "victimId": 1, "timestamp": 620000},
                        {"type": "ITEM_PURCHASED", "participantId": 1, "itemId": 9999, "timestamp": 650000},
                        {"type": "ELITE_MONSTER_KILL", "monsterType": "DRAGON", "killerId": 2, "timestamp": 700000},
                    ],
                }
            ]
        }
    }

    parsed = parse_timeline(timeline, participant_id=1, enemy_participant_id=2)

    assert parsed["cs_at_10"] == 73
    assert parsed["enemy_cs_at_10"] == 65
    assert parsed["gold_diff_by_minute"][10] == 200
    assert parsed["first_death_minute"] == 10.3
    assert parsed["death_minutes"] == [10.3]
    assert parsed["death_events"][0]["assist_count"] == 0
    assert parsed["death_events"][0]["first_blood_candidate"] is True
    assert parsed["deaths_pre_15"] == 1
    assert parsed["item_purchase_minutes"] == [{"minute": 10.8, "item_id": 9999}]
    assert parsed["objective_events"][0]["type"] == "DRAGON"


def test_build_replay_checkpoints_uses_real_timestamps():
    checkpoints = build_replay_checkpoints({
        "death_minutes": [8.3],
        "first_item_minute": 17.2,
        "objective_events": [{"minute": 16.7, "type": "DRAGON"}],
    })

    assert checkpoints[0]["timestamp"] == "8:18"
    assert checkpoints[0]["label"] == "First Death"
    assert "hypothesis" in checkpoints[0]
    assert checkpoints[1]["label"] == "Delayed Core Item Window"
    assert checkpoints[2]["label"] == "Dragon"
    assert "Objective at 16:42" in checkpoints[2]["evidence"]
