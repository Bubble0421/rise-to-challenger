from features.coaching.validators import judge_counter_output


def test_counter_validator_accepts_specific_item_plan():
    text = """MATCHUP READ
Jinx can contest Caitlyn after level 6 if traps are avoided.

LANE PLAN
- Trade after Caitlyn Q cooldown.
- Respect level 2 trap headshot.

MID GAME
- Move with support after first tower.
- Fight dragon with rocket range.

LATE GAME
Front-to-back around resets and peel.

ITEM PLAN
- Infinity Edge - max crit damage
- Guardian Angel - answers Caitlyn burst
"""

    passed, feedback = judge_counter_output({"draft": text, "enemy_champ": "Caitlyn"})

    assert passed, feedback
