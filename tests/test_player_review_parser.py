from features.player_review.parser import infer_role_in_comp, parse_match


def test_infer_role_in_comp_prefers_support_position():
    assert infer_role_in_comp("Lux", "UTILITY") == "support"
    assert infer_role_in_comp("Jinx", "BOTTOM") == "carry"


def test_parse_match_extracts_player_summary():
    match = {
        "metadata": {"matchId": "NA1_1"},
        "info": {
            "gameDuration": 1800,
            "participants": [
                {
                    "puuid": "me",
                    "teamId": 100,
                    "championName": "Jinx",
                    "teamPosition": "BOTTOM",
                    "win": True,
                    "kills": 5,
                    "deaths": 2,
                    "assists": 7,
                    "totalMinionsKilled": 210,
                    "neutralMinionsKilled": 5,
                    "totalDamageDealtToChampions": 22000,
                    "visionScore": 18,
                    "item0": 6672,
                    "item1": 3006,
                    "perks": {"styles": [{"selections": [{"perk": 8008}]}]},
                    "summoner1Id": 4,
                    "summoner2Id": 7,
                },
                {
                    "puuid": "ally",
                    "teamId": 100,
                    "championName": "Lulu",
                    "teamPosition": "UTILITY",
                    "kills": 7,
                    "totalDamageDealtToChampions": 4000,
                },
                {
                    "puuid": "enemy",
                    "teamId": 200,
                    "championName": "Caitlyn",
                    "teamPosition": "BOTTOM",
                    "kills": 3,
                    "totalDamageDealtToChampions": 16000,
                },
            ],
        },
    }

    parsed = parse_match("me", match)

    assert parsed["match_id"] == "NA1_1"
    assert parsed["champion"] == "Jinx"
    assert parsed["enemy_laner"] == "Caitlyn"
    assert parsed["cs_per_min"] == 7.2
    assert parsed["kp"] == 100.0
    assert parsed["keystone_id"] == 8008
