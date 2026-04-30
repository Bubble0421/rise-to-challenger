import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from api import (
    champion_icon_url,
    get_item_names,
    get_item_name,
    get_league_info,
    get_match_detail,
    get_match_ids,
    get_summoner,
    get_timeline,
    get_participant_id_from_match,
    get_enemy_participant_id_from_match,
    analyze_deaths,
    profile_icon_url,
    rank_icon_url,
)
from services.coach_service import (
    get_kpi_explanation,
    gold_diff_summary,
    get_recurring_issues,
)
from services.comp_service import classify_comp, get_game_plan, comp_label, get_team_identity
from services.champion_rule_service import (
    get_contextual_champion_tips,
    get_enemy_threats,
    get_item_tags,
    has_item_tag,
)
from services.execution_service import compute_chall_targets, compute_scorecard, compute_grade, get_top_gaps
from services.rune_service import evaluate_runes
from features.player_review.benchmarks import (
    dataset_for_tier,
    get_position_benchmark,
    get_rank_meta_context,
    load_benchmark_matches,
    load_optimal_builds,
)
from features.player_review.parser import parse_match
from utils.llm import create_chat_chain
from utils.render import item_icon_html
from utils.styles import GOLD, chart_layout, inject_css, render_sidebar, render_page_header, render_section_header
from utils.timeline import (
    build_replay_checkpoints,
    parse_timeline,
    CHALL_AVG_ITEM_MIN,
    classify_first_death,
    format_minute,
)
from utils.agents import run_ai_coach_report_agent

st.set_page_config(page_title="Rise to Challenger", page_icon="⚔", layout="wide", initial_sidebar_state="expanded")
inject_css()

POSITION_MAP = {
    "TOP": "Top", "JUNGLE": "Jungle", "MIDDLE": "Mid",
    "BOTTOM": "Bot", "UTILITY": "Support", "UNKNOWN": "Unknown",
}
POSITION_METRICS = {
    "TOP":     [("damage_share", "Damage Share %", False), ("cs_per_min", "CS/min", False), ("deaths", "Deaths", True), ("kda", "KDA", False)],
    "JUNGLE":  [("kp", "Kill Participation %", False), ("cs_per_min", "CS/min", False), ("vision", "Vision Score", False), ("kda", "KDA", False)],
    "MIDDLE":  [("damage", "Damage Dealt", False), ("cs_per_min", "CS/min", False), ("kda", "KDA", False), ("kp", "Kill Participation %", False)],
    "BOTTOM":  [("damage_share", "Damage Share %", False), ("cs_per_min", "CS/min", False), ("deaths", "Deaths", True), ("kda", "KDA", False)],
    "UTILITY": [("vision", "Vision Score", False), ("kp", "Kill Participation %", False), ("deaths", "Deaths", True), ("damage", "Damage Dealt", False)],
}
GOLD_COLOR  = "#C8AA6E"
RED_COLOR   = "#E84057"
GREEN_COLOR = "#1D9E75"
CYAN_COLOR  = "#0BC4E3"

# ─── UI helpers ───────────────────────────────────────────────────────────────

def format_metric_value(key: str, value: float) -> str:
    if key in {"kp", "damage_share"}:   return f"{value:.1f}%"
    if key == "kda":                    return f"{value:.2f}"
    if key == "cs_per_min":             return f"{value:.1f}"
    return f"{int(round(value)):,}"


def scorecard_meaning(row: dict) -> str:
    if not row.get("reliable", True):
        return "Unavailable - excluded from diagnosis"
    delta = row["delta"]
    if abs(delta) <= max(abs(row["target"]) * 0.08, 0.5):
        return "Close to benchmark"
    if row["lower"]:
        return "Cleaner than benchmark" if delta < 0 else "Cost/risk above benchmark"
    return "Creates advantage" if delta > 0 else "Limits impact"


def format_scorecard_actual(row: dict) -> str:
    return f"{row['actual']:.1f}" if row.get("reliable", True) else "N/A"


def render_metric_cards(selected_match: dict, benchmark: dict):
    metrics = POSITION_METRICS.get(selected_match["position"], POSITION_METRICS["MIDDLE"])
    cols = st.columns(4)
    for idx, (key, label, lower_is_better) in enumerate(metrics):
        value = selected_match[key]
        avg   = benchmark.get(key, 0)
        delta = value - avg
        good  = (delta <= 0) if lower_is_better else (delta >= 0)
        color = GREEN_COLOR if good else RED_COLOR
        delta_text  = f"{delta:+.1f} vs Challenger"
        explanation = get_kpi_explanation(key, good)
        with cols[idx]:
            st.markdown(
                f"<div style='background:#0A1428;border:1px solid {color}55;border-radius:4px;"
                f"padding:16px 18px;min-height:140px;'>"
                f"<div style='font-size:12px;color:#A0A0A0;text-transform:uppercase;letter-spacing:.08em;'>{label}</div>"
                f"<div style='font-size:28px;font-weight:700;color:{color};margin-top:8px;'>{format_metric_value(key, value)}</div>"
                f"<div style='font-size:12px;color:{color};margin-top:6px;'>{delta_text}</div>"
                f"<div style='font-size:11px;color:#A0A0A0;margin-top:6px;line-height:1.4;'>{explanation}</div>"
                f"</div>",
                unsafe_allow_html=True,
            )


# Position-appropriate CS@10 Challenger references
_CHALL_CS10_BY_POS = {
    "TOP": 80, "JUNGLE": 55, "MIDDLE": 80, "BOTTOM": 85, "UTILITY": 15,
}


def render_timeline_cards(tl: dict, position: str = "MIDDLE"):
    """Render 3 Timeline metric cards: CS@10 diff, first death, first item."""
    cs10    = tl["cs_at_10"]
    ecs10   = tl["enemy_cs_at_10"]
    lane_data_valid = isinstance(cs10, int) and isinstance(ecs10, int)
    if lane_data_valid and position != "UTILITY" and cs10 == 0:
        lane_data_valid = False
    cs_diff = (cs10 - ecs10) if lane_data_valid else 0
    death_m = tl["first_death_minute"]
    item_m  = tl["first_item_minute"]

    def _card(title: str, main: str, sub: str, color: str) -> str:
        return (
            f"<div style='background:#0A1428;border:1px solid {color}55;border-radius:4px;"
            f"padding:16px 18px;min-height:120px;'>"
            f"<div style='font-size:12px;color:#A0A0A0;text-transform:uppercase;letter-spacing:.08em;'>{title}</div>"
            f"<div style='font-size:22px;font-weight:700;color:{color};margin-top:8px;'>{main}</div>"
            f"<div style='font-size:12px;color:{color};margin-top:8px;'>{sub}</div>"
            f"</div>"
        )

    cols = st.columns(3)

    # CS @ 10 — position-aware reference
    chall_cs10 = _CHALL_CS10_BY_POS.get(position, 75)
    cs_color   = GREEN_COLOR if cs_diff >= 0 else RED_COLOR
    if not lane_data_valid:
        cs_sub = "Excluded from lane diagnosis"
        cs_color = GOLD_COLOR
        cs_main = "Unavailable"
    elif position == "UTILITY":
        # Support: show absolute CS vs Challenger support avg, not diff-based
        cs_vs_chall = cs10 - chall_cs10
        cs_sub = f"You: {cs10} · Chall support avg: ~{chall_cs10} ({cs_vs_chall:+d})"
        cs_color = GREEN_COLOR if cs_vs_chall >= -5 else GOLD_COLOR
        cs_main = f"{cs10} vs {ecs10}"
    else:
        cs_sub = f"Diff: {cs_diff:+d}  ·  Chall {POSITION_MAP.get(position, position)} avg: ~{chall_cs10}"
        cs_main = f"{cs10} vs {ecs10}"
    with cols[0]:
        st.markdown(
            _card("CS @ 10 min", cs_main, cs_sub, cs_color),
            unsafe_allow_html=True,
        )

    # First death
    death_color = GREEN_COLOR if death_m is None or death_m >= 10 else (GOLD_COLOR if death_m >= 5 else RED_COLOR)
    with cols[1]:
        death_main = f"Minute {death_m}" if death_m else "No deaths"
        death_sub  = classify_first_death(death_m)
        st.markdown(_card("First Death", death_main, death_sub, death_color), unsafe_allow_html=True)

    # First big item
    if item_m:
        item_gap   = item_m - CHALL_AVG_ITEM_MIN
        item_color = GREEN_COLOR if item_gap <= 0 else (GOLD_COLOR if item_gap <= 3 else RED_COLOR)
        item_main  = f"Minute {item_m}"
        item_sub   = f"{item_gap:+.0f} min vs Challenger avg ({CHALL_AVG_ITEM_MIN} min)"
    else:
        item_color = "#A0A0A0"
        item_main  = "Not recorded"
        item_sub   = "No legendary item purchase found"
    with cols[2]:
        st.markdown(_card("First Core Item", item_main, item_sub, item_color), unsafe_allow_html=True)


def render_gold_diff_chart(tl: dict, first_death_min: float | None, win: bool = False):
    """Plotly gold difference line chart with ahead/behind fill, death + item markers."""
    gd  = tl["gold_diff_by_minute"]
    if not gd:
        st.caption("No gold diff data available (no enemy laner found at same position).")
        return

    minutes = sorted(gd.keys())
    diffs   = [gd[m] for m in minutes]
    y_min   = min(diffs) * 1.15 if min(diffs) < 0 else -200
    y_max   = max(diffs) * 1.15 if max(diffs) > 0 else 200

    pos_y = [max(0, d) for d in diffs]
    neg_y = [min(0, d) for d in diffs]

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=minutes, y=pos_y,
        fill="tozeroy", fillcolor="rgba(200,170,110,0.25)",
        line=dict(color=GOLD_COLOR, width=2),
        name="Ahead",
        hovertemplate="Min %{x}: +%{y:,}g<extra></extra>",
    ))
    fig.add_trace(go.Scatter(
        x=minutes, y=neg_y,
        fill="tozeroy", fillcolor="rgba(226,75,74,0.25)",
        line=dict(color=RED_COLOR, width=2),
        name="Behind",
        hovertemplate="Min %{x}: %{y:,}g<extra></extra>",
    ))
    fig.add_hline(y=0, line_dash="dot", line_color="#1E2D40", line_width=1)

    shapes, annotations = [], []

    # First death marker
    if first_death_min is not None:
        shapes.append(dict(
            type="line", x0=first_death_min, x1=first_death_min,
            y0=y_min, y1=y_max,
            line=dict(color=RED_COLOR, width=1.5, dash="dash"),
        ))
        annotations.append(dict(
            x=first_death_min, y=y_max * 0.85,
            text=f"{int(first_death_min)}m", showarrow=False,
            font=dict(color=RED_COLOR, size=11),
        ))

    # First core item marker
    item_min = tl.get("first_item_minute")
    if item_min is not None:
        shapes.append(dict(
            type="line", x0=item_min, x1=item_min,
            y0=y_min, y1=y_max,
            line=dict(color=GOLD_COLOR, width=1.5, dash="dot"),
        ))
        annotations.append(dict(
            x=item_min, y=y_min * 0.85 if y_min < 0 else y_max * 0.5,
            text=f"{int(item_min)}m", showarrow=False,
            font=dict(color=GOLD_COLOR, size=11),
        ))

    # Peak lead and worst deficit markers
    if diffs:
        peak_val = max(diffs)
        peak_min = minutes[diffs.index(peak_val)]
        trough_val = min(diffs)
        trough_min = minutes[diffs.index(trough_val)]

        if peak_val > 300:
            annotations.append(dict(
                x=peak_min, y=peak_val,
                text=f"▲ +{peak_val:,}g",
                showarrow=True, arrowhead=2, arrowcolor=GOLD_COLOR,
                ax=0, ay=-28,
                font=dict(color=GOLD_COLOR, size=10),
            ))
        if trough_val < -300:
            annotations.append(dict(
                x=trough_min, y=trough_val,
                text=f"▼ {trough_val:,}g",
                showarrow=True, arrowhead=2, arrowcolor=RED_COLOR,
                ax=0, ay=28,
                font=dict(color=RED_COLOR, size=10),
            ))

    layout = chart_layout(
        height=280,
        xaxis=dict(title="Game minute"),
        yaxis=dict(title="Gold difference vs enemy laner"),
        showlegend=True,
        legend=dict(orientation="h", y=1.08),
        margin=dict(l=10, r=10, t=10, b=10),
    )
    layout["shapes"]      = shapes
    layout["annotations"] = annotations
    fig.update_layout(**layout)
    st.plotly_chart(fig, use_container_width=True)

    # Rule-based caption below chart
    caption = gold_diff_summary(gd, first_death_min, win=win)
    if caption:
        st.caption(caption)


def render_cs_curve_chart(tl: dict, position: str):
    """CS per minute curve: player vs enemy laner vs ideal Challenger pace."""
    cs_by_min      = tl.get("cs_by_minute", {})
    enemy_cs_by_min = tl.get("enemy_cs_by_minute", {})
    if not cs_by_min:
        return

    # Challenger ideal pace by position
    if position == "UTILITY":
        cs_rate = 1.5   # supports rarely farm — 1.5/min is realistic
    elif position == "JUNGLE":
        cs_rate = 5.5
    else:
        cs_rate = 7.5
    minutes = sorted(cs_by_min.keys())
    if len(minutes) < 5:
        return

    player_cs = [cs_by_min.get(m, 0) for m in minutes]
    enemy_cs  = [enemy_cs_by_min.get(m, 0) for m in minutes] if enemy_cs_by_min else []
    ideal_cs  = [round(m * cs_rate) for m in minutes]

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=minutes, y=player_cs,
        name="You", line=dict(color=GOLD_COLOR, width=2.5),
        hovertemplate="Min %{x}: %{y} CS<extra></extra>",
    ))
    if enemy_cs:
        fig.add_trace(go.Scatter(
            x=minutes, y=enemy_cs,
            name="Enemy laner", line=dict(color=RED_COLOR, width=1.5, dash="dot"),
            hovertemplate="Min %{x}: %{y} CS<extra></extra>",
        ))
    pace_label = "Support pace" if position == "UTILITY" else "Jungle pace" if position == "JUNGLE" else "Challenger pace"
    fig.add_trace(go.Scatter(
        x=minutes, y=ideal_cs,
        name=f"{pace_label} ({cs_rate}/min)", line=dict(color="#1E2D40", width=1, dash="dash"),
        hovertemplate="Min %{x}: %{y} CS (target)<extra></extra>",
    ))

    layout = chart_layout(
        height=220,
        xaxis=dict(title="Game minute"),
        yaxis=dict(title="Total CS"),
        showlegend=True,
        legend=dict(orientation="h", y=1.12),
        margin=dict(l=10, r=10, t=10, b=10),
    )
    fig.update_layout(**layout)
    st.plotly_chart(fig, use_container_width=True)


def render_role_impact_chart(selected_match: dict):
    """Render a user-selectable team comparison for the match overview."""
    position = selected_match["position"]
    participants = selected_match["participants"]
    me_puuid = selected_match["puuid"]

    metric_options = {
        "Damage to Champions": ("totalDamageDealtToChampions", "Damage to Champions"),
        "Kill Participation": ("kp", "Kill Participation %"),
        "Team Damage Share": ("damage_share", "Team Damage Share %"),
        "Vision Score": ("visionScore", "Vision Score"),
        "CS": ("cs", "Total CS"),
        "KDA Ratio": ("kda", "KDA Ratio"),
    }
    default_metric = {
        "UTILITY": "Vision Score",
        "JUNGLE": "Kill Participation",
        "TOP": "Team Damage Share",
        "MIDDLE": "Damage to Champions",
        "BOTTOM": "Damage to Champions",
    }.get(position, "Damage to Champions")

    render_section_header("MATCH OVERVIEW")
    metric_label = st.selectbox(
        "Compare Metric",
        list(metric_options.keys()),
        index=list(metric_options.keys()).index(default_metric),
        key=f"overview_metric_{selected_match['match_id']}",
    )
    metric_key, axis_title = metric_options[metric_label]

    team_totals: dict[int, dict[str, float]] = {}
    for pp in participants:
        team_id = pp["teamId"]
        team_totals.setdefault(team_id, {"kills": 0, "damage": 0})
        team_totals[team_id]["kills"] += pp.get("kills", 0)
        team_totals[team_id]["damage"] += pp.get("totalDamageDealtToChampions", 0)

    rows = []
    for pp in participants:
        team_id = pp["teamId"]
        if metric_key == "kp":
            value = (pp.get("kills", 0) + pp.get("assists", 0)) / max(team_totals[team_id]["kills"], 1) * 100
        elif metric_key == "damage_share":
            value = pp.get("totalDamageDealtToChampions", 0) / max(team_totals[team_id]["damage"], 1) * 100
        elif metric_key == "cs":
            value = pp.get("totalMinionsKilled", 0) + pp.get("neutralMinionsKilled", 0)
        elif metric_key == "kda":
            value = (pp.get("kills", 0) + pp.get("assists", 0)) / max(pp.get("deaths", 0), 1)
        else:
            value = pp.get(metric_key, 0)
        rows.append({
            "Champion": pp["championName"],
            "Value": round(value, 1),
            "isMe": pp.get("puuid") == me_puuid,
        })

    role_data = pd.DataFrame(rows).sort_values("Value", ascending=True)
    if metric_key in {"kp", "damage_share"}:
        text_values = role_data["Value"].apply(lambda v: f"{v:.1f}%")
    elif metric_key == "kda":
        text_values = role_data["Value"].apply(lambda v: f"{v:.2f}")
    else:
        text_values = role_data["Value"].apply(lambda v: f"{int(round(v)):,}")

    fig_role = go.Figure(go.Bar(
        x=role_data["Value"],
        y=role_data["Champion"],
        orientation="h",
        marker_color=[GOLD if flag else "#1E2D40" for flag in role_data["isMe"]],
        text=text_values,
        textposition="outside",
    ))
    fig_role.update_layout(**chart_layout(
        height=360,
        xaxis=dict(title=axis_title),
        margin=dict(l=10, r=80, t=10, b=10),
    ))
    st.plotly_chart(fig_role, use_container_width=True)


def render_replay_checkpoints(checkpoints: list[dict]):
    if not checkpoints:
        return

    render_section_header("REPLAY CHECKPOINTS")
    st.caption("These timestamps come from Riot timeline data. The questions are fixed replay checks, not AI claims.")
    for checkpoint in checkpoints:
        hypothesis = checkpoint.get("hypothesis")
        evidence = checkpoint.get("evidence")
        hypothesis_html = (
            f"<div style='font-size:13px;color:{GOLD_COLOR};line-height:1.45;margin-top:10px;'>"
            f"Hypothesis to verify: {hypothesis}</div>"
            if hypothesis else ""
        )
        evidence_html = (
            f"<div style='font-size:12px;color:#A0A0A0;line-height:1.45;margin-top:4px;'>"
            f"Timeline evidence: {evidence}</div>"
            if evidence else ""
        )
        questions_html = "".join(
            f"<div style='font-size:13px;color:#F0E6D3;line-height:1.5;margin-top:6px;'>□ {question}</div>"
            for question in checkpoint.get("questions", [])
        )
        st.markdown(
            f"<div style='background:#0A1428;border:1px solid #1E2D40;border-left:3px solid {GOLD_COLOR};"
            f"border-radius:4px;padding:14px 18px;margin-bottom:12px;'>"
            f"<div style='display:flex;gap:14px;align-items:baseline;'>"
            f"<div style='font-size:18px;color:{GOLD_COLOR};font-weight:700;'>{checkpoint.get('timestamp', 'unknown')}</div>"
            f"<div style='font-size:12px;color:#A0A0A0;text-transform:uppercase;letter-spacing:1.2px;'>"
            f"{checkpoint.get('label', 'Replay Check')}</div></div>"
            f"{hypothesis_html}{evidence_html}{questions_html}</div>",
            unsafe_allow_html=True,
        )


def build_phase_analysis(sel: dict, chall_avg: dict, tl: dict | None) -> dict[str, dict[str, str]]:
    position = sel["position"]
    cs10 = tl.get("cs_at_10") if tl else None
    enemy_cs10 = tl.get("enemy_cs_at_10") if tl else None
    gold10 = tl.get("gold_diff_by_minute", {}).get(10) if tl else None
    first_death = tl.get("first_death_minute") if tl else None
    first_item = tl.get("first_item_minute") if tl else None
    death_minutes = tl.get("death_minutes", []) if tl else []
    objectives = tl.get("objective_events", []) if tl else []

    lane_data_valid = isinstance(cs10, int) and isinstance(enemy_cs10, int)
    if lane_data_valid and position != "UTILITY" and cs10 == 0 and sel.get("cs", 0) >= 25:
        lane_data_valid = False

    if lane_data_valid:
        cs_diff = cs10 - enemy_cs10
        lane_what = f"CS@10 was {cs10} vs enemy {enemy_cs10} ({cs_diff:+d}); first death was {format_minute(first_death) if first_death else 'none recorded'}."
        if cs_diff >= 5 and not first_death:
            lane_why = "Lane created a small resource edge without donating tempo."
            lane_action = "When this happens, convert the wave edge into river setup with jungle instead of staying only for plates."
        elif cs_diff < -8:
            lane_why = "Lane was under pressure; forcing trades from behind risks delaying item timing."
            lane_action = "Stabilize the wave first, then move with jungle/support instead of contesting alone."
        else:
            lane_why = "Lane stayed close enough that mid-game decisions matter more than pure laning."
            lane_action = "Use the next recall or push window to secure vision before the first objective."
    else:
        lane_what = "Lane CS@10 is unavailable or failed the data-quality check."
        lane_why = "Do not grade lane phase from this field; use deaths, gold, wave state, and replay instead."
        lane_action = "Review first death, first recall, and first river move before assigning lane responsibility."

    if first_item:
        item_gap = first_item - CHALL_AVG_ITEM_MIN
        mid_what = f"First core item completed at {format_minute(first_item)} vs Challenger target {CHALL_AVG_ITEM_MIN}:00 ({item_gap:+.1f} min)."
        if item_gap > 2:
            mid_why = "Delayed item timing reduces power in early objective windows."
            mid_action = "If objective spawns soon and you have component/core gold, recall before one more wave."
        else:
            mid_why = "Item timing was close enough to contest mid-game fights on schedule."
            mid_action = "Keep syncing recalls with objective timers rather than farming through setup windows."
    else:
        mid_what = "First core item timing is unclear from available data."
        mid_why = "Mid-game power spike cannot be judged precisely."
        mid_action = "Review recall timing around minutes 11-14 and compare it to objective spawn timers."

    late_deaths = [m for m in death_minutes if m >= 25]
    kp = sel.get("kp", 0)
    damage_gap = sel.get("damage", 0) - chall_avg.get("damage", 0)
    if objectives:
        obj_text = ", ".join(f"{obj.get('type')} {format_minute(obj.get('minute'))}" for obj in objectives[:3])
    else:
        obj_text = "objective timestamps unavailable"
    late_what = f"KP was {kp:.1f}%, damage gap was {damage_gap:+,.0f}, late deaths: {len(late_deaths)}; objectives: {obj_text}."
    if late_deaths:
        late_why = "Late deaths are high leverage because they directly change Baron, Elder, and ending windows."
        late_action = "Before late objectives, enter fog behind frontline and hold key defensive/CC cooldowns for first engage."
    elif (not sel.get("win")) and kp >= chall_avg.get("kp", 0) + 8 and damage_gap < 0 and sel.get("deaths", 0) > chall_avg.get("deaths", 0):
        late_why = "High KP in a loss with low damage and high deaths can mean joining too many losing fights."
        late_action = "Review whether each joined fight had item timing, vision setup, and frontline access before committing."
    elif kp < max(chall_avg.get("kp", 0) - 5, 45):
        late_why = "Lower KP suggests some output may have happened away from decisive team actions."
        late_action = "When Baron or Dragon setup starts, stop side-wave collection and move with jungle/support first."
    else:
        late_why = "Late-game participation and survival were not the obvious failure point from available data."
        late_action = "Keep grouping around objective setup and review only the fights listed in checkpoints."

    return {
        "Lane Phase": {"what": lane_what, "why": lane_why, "action": lane_action},
        "Mid Game": {"what": mid_what, "why": mid_why, "action": mid_action},
        "Late Game": {"what": late_what, "why": late_why, "action": late_action},
    }


def render_phase_analysis(phases: dict[str, dict[str, str]]):
    render_section_header("PHASE ANALYSIS")
    cards_html = ""
    for phase, data in phases.items():
        rows = [
            ("Read", data["what"]),
            ("Meaning", data["why"]),
            ("Review cue", data["action"]),
        ]
        rows_html = "".join(
            f"<div style='padding:10px 0;border-top:1px solid #1E2D40;'>"
            f"<div style='font-size:10px;color:#A0A0A0;text-transform:uppercase;"
            f"letter-spacing:1.3px;font-weight:700;margin-bottom:5px;'>{label}</div>"
            f"<div style='color:#F0E6D3;font-size:13px;line-height:1.5;'>{text}</div>"
            f"</div>"
            for label, text in rows
        )
        cards_html += (
            f"<div style='background:#0A1428;border:1px solid #1E2D40;border-top:2px solid {GOLD_COLOR};"
            f"border-radius:4px;padding:16px 18px;min-height:250px;'>"
            f"<div style='font-size:13px;color:{GOLD_COLOR};font-weight:700;text-transform:uppercase;"
            f"letter-spacing:1.7px;margin-bottom:8px;'>{phase}</div>"
            f"{rows_html}</div>"
        )
    st.markdown(
        f"<div style='display:grid;grid-template-columns:repeat(3,minmax(0,1fr));"
        f"gap:16px;align-items:stretch;'>{cards_html}</div>",
        unsafe_allow_html=True,
    )


def render_review_focus(cards: list[tuple[str, list[tuple[str, str]], str]]):
    render_section_header("REVIEW FOCUS")
    cards_html = ""
    for title, rows, color in cards:
        rows_html = "".join(
            f"<div style='display:grid;grid-template-columns:132px minmax(0,1fr);gap:16px;"
            f"padding:12px 0;border-top:1px solid #1E2D40;'>"
            f"<div style='font-size:11px;color:#A0A0A0;text-transform:uppercase;"
            f"letter-spacing:1.2px;font-weight:700;'>{label}</div>"
            f"<div style='font-size:14px;color:#F0E6D3;line-height:1.55;'>{text}</div>"
            f"</div>"
            for label, text in rows
        )
        cards_html += (
            f"<div style='background:#0A1428;border:1px solid #1E2D40;border-left:3px solid {color};"
            f"border-radius:4px;padding:18px 20px;'>"
            f"<div style='font-size:12px;color:{color};font-weight:700;text-transform:uppercase;"
            f"letter-spacing:1.5px;margin-bottom:4px;'>{title}</div>"
            f"{rows_html}</div>"
        )
    st.markdown(
        f"<div style='display:grid;grid-template-columns:1fr;gap:14px;'>{cards_html}</div>",
        unsafe_allow_html=True,
    )


def render_coach_final_review(cards: list[tuple[str, str, str, str]]):
    cards_html = ""
    for idx, (title, kicker, body, color) in enumerate(cards, start=1):
        cards_html += (
            f"<div style='background:#0A1428;border:1px solid #1E2D40;border-left:3px solid {color};"
            f"border-radius:4px;padding:18px 20px;'>"
            f"<div style='display:flex;align-items:center;gap:12px;margin-bottom:10px;'>"
            f"<div style='font-size:11px;color:{color};font-weight:800;letter-spacing:1.5px;'>0{idx}</div>"
            f"<div style='font-size:12px;color:{color};font-weight:700;text-transform:uppercase;"
            f"letter-spacing:1.5px;'>{title}</div>"
            f"</div>"
            f"<div style='font-size:14px;color:#F0E6D3;font-weight:700;line-height:1.45;margin-bottom:8px;'>{kicker}</div>"
            f"<div style='font-size:13px;color:#A0A0A0;line-height:1.6;'>{body}</div>"
            f"</div>"
        )
    st.markdown(
        f"<div style='display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:16px;'>{cards_html}</div>",
        unsafe_allow_html=True,
    )


def render_ai_coach_report(text: str):
    sections = []
    current = None
    body: list[str] = []
    headers = {"COACH READ", "WHAT YOU DID RIGHT", "ROLE EXECUTION", "TURNING POINTS", "PRACTICE ASSIGNMENT"}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line in headers:
            if current:
                sections.append((current, "\n".join(body).strip()))
            current = line
            body = []
        elif current:
            body.append(line)
    if current:
        sections.append((current, "\n".join(body).strip()))
    if not sections:
        sections = [("AI COACH REPORT", text)]

    cards_html = ""
    for title, value in sections:
        value_html = "<br>".join(value.splitlines())
        cards_html += (
            f"<div style='background:#0A1428;border:1px solid #1E2D40;border-left:3px solid {GOLD_COLOR};"
            f"border-radius:4px;padding:16px 18px;'>"
            f"<div style='font-size:12px;color:{GOLD_COLOR};font-weight:700;text-transform:uppercase;"
            f"letter-spacing:1.4px;margin-bottom:8px;'>{title}</div>"
            f"<div style='font-size:14px;color:#F0E6D3;line-height:1.6;'>{value_html}</div>"
            f"</div>"
        )
    st.markdown(
        f"<div style='display:grid;grid-template-columns:1fr;gap:12px;'>{cards_html}</div>",
        unsafe_allow_html=True,
    )


def build_data_quality(selected_match: dict, tl: dict | None) -> dict:
    issues: list[str] = []
    reliable = {
        "timeline": bool(tl),
        "lane": False,
        "gold": False,
        "deaths": False,
        "items": False,
    }
    if not tl:
        issues.append("Timeline unavailable; lane, death timing, and item timing are lower confidence.")
        return {"issues": issues, "reliable": reliable, "confidence": "LOW"}

    cs10 = tl.get("cs_at_10")
    enemy_cs10 = tl.get("enemy_cs_at_10")
    lane_valid = isinstance(cs10, int) and isinstance(enemy_cs10, int)
    if lane_valid and selected_match["position"] != "UTILITY" and cs10 == 0 and selected_match.get("cs", 0) >= 25:
        lane_valid = False
        issues.append("CS@10 reads as 0 despite later CS; lane CS data was excluded from diagnosis.")
    elif not lane_valid:
        issues.append("CS@10 or enemy CS@10 missing; lane economy is lower confidence.")
    reliable["lane"] = lane_valid

    gold10 = tl.get("gold_diff_by_minute", {}).get(10)
    reliable["gold"] = isinstance(gold10, (int, float))
    if not reliable["gold"]:
        issues.append("Gold@10 missing; lane pressure cannot be judged from gold difference.")

    death_minutes = tl.get("death_minutes", [])
    reliable["deaths"] = bool(death_minutes) or selected_match.get("deaths", 0) == 0
    if selected_match.get("deaths", 0) > 0 and not death_minutes:
        issues.append("Death timestamps missing; replay priority cannot assign exact death windows.")

    reliable["items"] = tl.get("first_item_minute") is not None
    if not reliable["items"]:
        issues.append("First core item timing missing; item-spike diagnosis is lower confidence.")

    confidence = "HIGH"
    if len(issues) >= 3:
        confidence = "LOW"
    elif issues:
        confidence = "MEDIUM"
    return {"issues": issues, "reliable": reliable, "confidence": confidence}


def render_data_quality(quality: dict):
    confidence = quality["confidence"]
    color = GREEN_COLOR if confidence == "HIGH" else GOLD_COLOR if confidence == "MEDIUM" else RED_COLOR
    issues = quality["issues"] or ["Timeline, lane, death, gold, and item timing data passed basic checks."]
    issue_html = "".join(
        f"<div style='font-size:12px;color:#F0E6D3;line-height:1.45;margin-top:4px;'>{issue}</div>"
        for issue in issues[:4]
    )
    st.markdown(
        f"<div style='background:#0A1428;border:1px solid {color}55;border-left:3px solid {color};"
        f"border-radius:4px;padding:12px 16px;margin-bottom:14px;'>"
        f"<div style='font-size:11px;color:{color};font-weight:700;text-transform:uppercase;"
        f"letter-spacing:1.4px;'>Data Confidence: {confidence}</div>"
        f"{issue_html}</div>",
        unsafe_allow_html=True,
    )


_GRADE_RANK = {"S": 7, "A": 6, "B+": 5, "B": 4, "C+": 3, "C": 2, "D": 1}
_GRADE_BY_RANK = {rank: grade for grade, rank in _GRADE_RANK.items()}


def _cap_grade(grade: str, max_grade: str) -> str:
    return _GRADE_BY_RANK[min(_GRADE_RANK.get(grade, 1), _GRADE_RANK[max_grade])]


def format_primary_failure(row: dict | None) -> str:
    if not row:
        return "No single primary failure detected"
    label = row.get("label", "Primary metric")
    actual = row.get("actual", 0)
    target = row.get("target", 0)
    key = row.get("key", "")
    if key in {"deaths", "deaths_pre_15"}:
        return f"Death control ({actual:.0f} deaths vs Challenger avg {target:.1f})"
    if key in {"vision", "roam_count", "cs_per_min", "damage_share", "kp"}:
        return f"{label} ({actual:.1f} vs Challenger avg {target:.1f})"
    if key == "first_item_min":
        return f"Item timing ({actual:.1f} min vs Challenger target {target:.1f})"
    if key == "cs_diff_10":
        return f"Lane CS @10 ({actual:+.0f} vs target {target:+.0f})"
    return f"{label} ({actual:.1f} vs target {target:.1f})"


def apply_coach_grade_rules(
    grade: str,
    desc: str,
    rows: list[dict],
    selected_match: dict,
    benchmark: dict,
    quality: dict,
) -> tuple[str, str]:
    reliable_rows = [r for r in rows if r.get("reliable", True)]
    below_rows = [
        r for r in reliable_rows
        if (r["lower"] and r["delta"] > 0) or (not r["lower"] and r["delta"] < 0)
    ]
    severe_rows = [r for r in reliable_rows if r["score"] < 0.5]

    if len(below_rows) >= 4:
        grade = _cap_grade(grade, "C")
        worst = min(below_rows, key=lambda r: r["score"])
        desc = f"Primary failure: {format_primary_failure(worst)}. Other benchmark gaps are secondary."
    elif len(below_rows) >= 3:
        grade = _cap_grade(grade, "C+")
        worst = min(below_rows, key=lambda r: r["score"])
        desc = f"Primary failure: {format_primary_failure(worst)}. Fix this before praising secondary strengths."

    if len(severe_rows) >= 2:
        grade = _cap_grade(grade, "C")
        worst = min(severe_rows, key=lambda r: r["score"])
        desc = f"Primary failure: {format_primary_failure(worst)}. Multiple severe gaps exist, but this is the review anchor."

    high_kp_loss = (
        not selected_match.get("win")
        and selected_match.get("kp", 0) >= benchmark.get("kp", 0) + 8
        and selected_match.get("damage", 0) < benchmark.get("damage", 0)
        and selected_match.get("deaths", 0) > benchmark.get("deaths", 0)
    )
    if high_kp_loss:
        grade = _cap_grade(grade, "C+")
        desc = (
            f"Primary failure: Death control ({selected_match.get('deaths', 0):.0f} deaths vs Challenger avg "
            f"{benchmark.get('deaths', 0):.1f}). High KP in this loss may be low-quality participation."
        )

    if quality["confidence"] != "HIGH":
        desc = f"{desc} Confidence: {quality['confidence'].lower()} due to missing or suspect timeline fields."

    return grade, desc


def render_items_row(item_ids: list[int], item_names: dict, size: int = 36) -> str:
    return "".join(item_icon_html(iid, item_names.get(iid, ""), size) for iid in item_ids if iid != 0)


def render_scoreboard(selected_match: dict, item_names: dict):
    current_puuid = selected_match["puuid"]
    player_win    = selected_match["win"]

    # Split participants into ally team and enemy team based on win flag
    ally_team  = [pp for pp in selected_match["participants"] if pp["win"] == player_win]
    enemy_team = [pp for pp in selected_match["participants"] if pp["win"] != player_win]

    def _row(pp: dict, bg: str) -> str:
        border     = f"border-left:4px solid {GOLD};" if pp["puuid"] == current_puuid else ""
        items_html = render_items_row([pp.get(f"item{i}", 0) for i in range(6)], item_names, 28)
        return (
            f"<tr style='background:{bg};{border}'>"
            f"<td style='padding:10px 12px;'><img src='{champion_icon_url(pp['championName'])}' "
            f"width='28' height='28' style='border-radius:4px;vertical-align:middle;margin-right:8px;'>"
            f"{pp.get('riotIdGameName') or pp.get('summonerName') or 'Unknown'}</td>"
            f"<td style='padding:10px 12px;'>{pp['kills']}/{pp['deaths']}/{pp['assists']}</td>"
            f"<td style='padding:10px 12px;'>{pp['totalDamageDealtToChampions']:,}</td>"
            f"<td style='padding:10px 12px;'>{pp['totalMinionsKilled'] + pp.get('neutralMinionsKilled', 0)}</td>"
            f"<td style='padding:10px 12px;'>{pp['visionScore']}</td>"
            f"<td style='padding:10px 12px;'><div style='display:flex;gap:4px;flex-wrap:wrap;'>{items_html}</div></td>"
            f"</tr>"
        )

    HEADER_COLS = (
        "<thead><tr style='color:#A0A0A0;text-align:left;'>"
        "<th style='padding:6px 12px;'>Player</th><th style='padding:6px 12px;'>KDA</th>"
        "<th style='padding:6px 12px;'>Damage</th><th style='padding:6px 12px;'>CS</th>"
        "<th style='padding:6px 12px;'>Vision</th><th style='padding:6px 12px;'>Items</th>"
        "</tr></thead>"
    )

    ally_rows  = "".join(_row(pp, "rgba(40,85,160,0.18)")  for pp in ally_team)
    enemy_rows = "".join(_row(pp, "rgba(160,45,45,0.18)") for pp in enemy_team)

    ally_label  = "YOUR TEAM"
    enemy_label = "ENEMY TEAM"

    def _section(label: str, color: str, rows_html: str) -> str:
        return (
            f"<tr><td colspan='6' style='padding:10px 12px 4px;font-size:11px;font-weight:700;"
            f"color:{color};text-transform:uppercase;letter-spacing:.1em;'>{label}</td></tr>"
            + rows_html
        )

    st.html(
        "<table style='width:100%;border-collapse:separate;border-spacing:0 4px;font-size:13px;'>"
        + HEADER_COLS
        + "<tbody>"
        + _section(ally_label,  "#0BC4E3", ally_rows)
        + _section(enemy_label, "#E84057", enemy_rows)
        + "</tbody></table>"
    )


# ─── Page bootstrap ───────────────────────────────────────────────────────────

item_names = get_item_names()

render_sidebar()

render_page_header("PLAYER REVIEW", "Real-time match data · Challenger benchmarks · AI coaching")

col_input, col_slider = st.columns([3, 1])
with col_input:
    name_tag = st.text_input("Summoner Name#TAG", placeholder="e.g. Faker#KR1", key="summoner_input")
with col_slider:
    match_count = st.slider("Match count", 5, 20, 10)

if name_tag and "#" in name_tag:
    game_name, tag_line = [p.strip() for p in name_tag.split("#", 1)]
else:
    st.info("Enter a summoner name above to get started.")
    st.stop()

summoner = get_summoner(game_name, tag_line)
if not summoner:
    st.stop()

league      = get_league_info(summoner["puuid"])
rank_dataset = dataset_for_tier(league["tier"] if league else None)
rank_matches = load_benchmark_matches(rank_dataset)

c_icon, c_name, c_rank, c_stats = st.columns([1, 2, 2, 2])
with c_icon:
    st.image(profile_icon_url(summoner["profileIconId"]), width=80)
with c_name:
    st.markdown(f"### {game_name}#{tag_line}")
    st.caption(f"Level {summoner['summonerLevel']}")
with c_rank:
    if league:
        st.image(rank_icon_url(league["tier"]), width=48)
        st.markdown(f"**{league['tier']} {league['rank']}** — {league['leaguePoints']} LP")
    else:
        st.markdown("**Unranked**")
with c_stats:
    if league:
        wins, losses = league["wins"], league["losses"]
        wr = round(wins / max(wins + losses, 1) * 100, 1)
        st.metric("Win Rate", f"{wr}%", delta=f"{wins}W {losses}L", delta_color="off")
    else:
        st.caption("No ranked data")

st.divider()

match_ids = get_match_ids(summoner["puuid"], count=match_count)
if not match_ids:
    st.warning("No recent ranked matches found.")
    st.stop()

matches = []
with st.spinner("Loading match history..."):
    for mid in match_ids:
        detail = get_match_detail(mid)
        if detail:
            matches.append(detail)

parsed = [pm for m in matches for pm in [parse_match(summoner["puuid"], m)] if pm]
challenger_matches = load_benchmark_matches("Challenger")

# ─── Multi-game trend sparklines ─────────────────────────────────────────────
if len(parsed) >= 3:
    _sp_games = list(range(1, len(parsed) + 1))
    _sp_deaths = [m["deaths"] for m in parsed]
    _sp_cs     = [m["cs_per_min"] for m in parsed]
    _sp_vision = [m["vision"] for m in parsed]
    _sp_champ_avg, _ = get_position_benchmark(
        challenger_matches,
        max(set(m["champion"] for m in parsed), key=lambda c: sum(1 for m in parsed if m["champion"] == c), default=""),
        max(set(m["position"] for m in parsed if m["position"] != "UNKNOWN"), key=lambda p: sum(1 for m in parsed if m["position"] == p), default="MIDDLE"),
    )

    _fig_sp = go.Figure()
    _fig_sp.add_trace(go.Scatter(
        x=_sp_games, y=_sp_deaths, name="Deaths",
        line=dict(color=RED_COLOR, width=2), mode="lines+markers",
        hovertemplate="Game %{x}: %{y} deaths<extra></extra>",
    ))
    _fig_sp.add_trace(go.Scatter(
        x=_sp_games, y=_sp_cs, name="CS/min",
        line=dict(color=GOLD_COLOR, width=2), mode="lines+markers",
        hovertemplate="Game %{x}: %{y} CS/min<extra></extra>",
        yaxis="y2",
    ))
    _fig_sp.add_hline(y=_sp_champ_avg.get("deaths", 3.5), line_dash="dot",
                      line_color=RED_COLOR, line_width=1, opacity=0.4,
                      annotation_text="Chall avg", annotation_position="top right")
    _fig_sp.update_layout(**chart_layout(
        height=180,
        xaxis=dict(title=None, dtick=1),
        yaxis=dict(title=None, side="left"),
        showlegend=True,
        legend=dict(orientation="h", y=1.16, x=0, font=dict(size=10)),
        margin=dict(l=34, r=48, t=28, b=24),
    ))
    _fig_sp.update_layout(yaxis2=dict(
        title=None,
        overlaying="y", side="right",
        showgrid=False, zeroline=False,
        tickfont=dict(color=GOLD_COLOR),
    ))
    with st.expander("Recent Games Trend", expanded=False):
        st.plotly_chart(_fig_sp, use_container_width=True)

# ─── Match history list ───────────────────────────────────────────────────────
render_section_header("MATCH HISTORY")
for match in parsed:
    border_color = GREEN_COLOR if match["win"] else RED_COLOR
    bg_color     = "rgba(29,158,117,0.08)" if match["win"] else "rgba(226,75,74,0.08)"
    items_html   = render_items_row(match["items"], item_names, 30)
    st.markdown(
        f"<div style='background:{bg_color};border-left:4px solid {border_color};border-radius:4px;"
        f"padding:10px 14px;margin-bottom:8px;display:flex;align-items:center;gap:14px;'>"
        f"<div style='min-width:44px;text-align:center;'>"
        f"<div style='font-weight:700;font-size:13px;color:{border_color};'>{'WIN' if match['win'] else 'LOSS'}</div>"
        f"<div style='font-size:11px;color:#A0A0A0;'>{match['duration']}m</div></div>"
        f"<img src='{champion_icon_url(match['champion'])}' width='44' height='44' "
        f"style='border-radius:4px;border:2px solid {border_color};'>"
        f"<div style='min-width:90px;'>"
        f"<div style='font-weight:600;font-size:14px;color:#F0E6D3;'>{match['champion']}</div>"
        f"<div style='font-size:11px;color:#A0A0A0;'>{POSITION_MAP.get(match['position'], match['position'])}</div></div>"
        f"<div style='min-width:90px;text-align:center;'>"
        f"<div style='font-size:15px;font-weight:700;color:#F0E6D3;'>{match['kills']}/{match['deaths']}/{match['assists']}</div>"
        f"<div style='font-size:11px;color:#A0A0A0;'>KDA {match['kda']}</div></div>"
        f"<div style='min-width:70px;text-align:center;'>"
        f"<div style='font-size:13px;color:#F0E6D3;'>{match['cs']} CS</div>"
        f"<div style='font-size:11px;color:#A0A0A0;'>{match['cs_per_min']}/min</div></div>"
        f"<div style='min-width:80px;text-align:center;'>"
        f"<div style='font-size:13px;color:#F0E6D3;'>{match['damage']:,}</div>"
        f"<div style='font-size:11px;color:#A0A0A0;'>Damage</div></div>"
        f"<div style='margin-left:auto;display:flex;gap:4px;flex-wrap:wrap;'>{items_html}</div>"
        f"</div>",
        unsafe_allow_html=True,
    )

st.divider()
render_section_header("SELECT A MATCH TO REVIEW")
match_options = {
    f"{p['champion']} · {'WIN' if p['win'] else 'LOSS'} · {p['kills']}/{p['deaths']}/{p['assists']} · {p['duration']}min": p
    for p in parsed
}
selected_label = st.selectbox("Choose a match", list(match_options.keys()))
sel = match_options[selected_label]
chall_avg, benchmark_label = get_position_benchmark(challenger_matches, sel["champion"], sel["position"])

left_col, right_col = st.columns([7, 3])

with left_col:

    # ─── Section 1: Game Context ───────────────────────────────────────────────────
    ally_champs_for_comp  = sel["ally_champions"] + [sel["champion"]]
    enemy_champs_for_comp = sel["enemy_champions"]
    ally_comp_type  = classify_comp(ally_champs_for_comp)
    enemy_comp_type = classify_comp(enemy_champs_for_comp)
    game_plan = get_game_plan(ally_comp_type, enemy_comp_type, sel["position"], sel["champion"])
    enemy_threats = get_enemy_threats(enemy_champs_for_comp)
    enemy_tags = {tag for tag, champs in enemy_threats.items() if champs}
    team_identity = get_team_identity(ally_champs_for_comp, sel["champion"], sel["position"])

    timeline_data_str = ""
    tl_parsed: dict | None = None
    replay_checkpoints: list[dict] = []
    timeline_raw = None
    with st.spinner("Fetching timeline data..."):
        timeline_raw = get_timeline(sel["match_id"])

    if timeline_raw:
        puuid = summoner["puuid"]
        pid = get_participant_id_from_match(sel["match_obj"], puuid)
        enemy_pid = get_enemy_participant_id_from_match(sel["match_obj"], puuid)
        if pid:
            tl_parsed = parse_timeline(timeline_raw, pid, enemy_pid)
            replay_checkpoints = build_replay_checkpoints(tl_parsed)
            gd_curve = list(tl_parsed["gold_diff_by_minute"].values())[:20]
            death_times = ", ".join(format_minute(m) for m in tl_parsed.get("death_minutes", [])) or "none"
            core_items = ", ".join(
                f"{event['item_id']} at {format_minute(event['minute'])}"
                for event in tl_parsed.get("core_item_minutes", [])
            ) or "none"
            objectives = ", ".join(
                f"{event['type']} at {format_minute(event['minute'])}"
                for event in tl_parsed.get("objective_events", [])
            ) or "none"
            timeline_data_str = (
                f"CS at 10 min: {tl_parsed['cs_at_10']} (enemy: {tl_parsed['enemy_cs_at_10']}, "
                f"diff: {tl_parsed['cs_at_10'] - tl_parsed['enemy_cs_at_10']:+d})\n"
                f"CS at 15 min: {tl_parsed['cs_at_15']} (enemy: {tl_parsed['enemy_cs_at_15']})\n"
                f"First death: minute {tl_parsed['first_death_minute']} ({classify_first_death(tl_parsed['first_death_minute'])})\n"
                f"All player death timestamps: {death_times}\n"
                f"First core item: minute {tl_parsed['first_item_minute']} (Challenger avg: {CHALL_AVG_ITEM_MIN} min)\n"
                f"Core item purchase timestamps: {core_items}\n"
                f"Objective timestamps: {objectives}\n"
                f"Gold diff curve (min 0-{len(gd_curve)-1}): {gd_curve}\n"
            )

    data_quality = build_data_quality(sel, tl_parsed)

    _COMP_COLOR = {
        "engage": "#0BC4E3", "poke": "#C8AA6E", "splitpush": "#1D9E75",
        "teamfight": "#785A28", "protect": "#1D9E75", "assassin": "#E84057",
    }
    ally_color  = _COMP_COLOR.get(ally_comp_type, "#A0A0A0")
    enemy_color = _COMP_COLOR.get(enemy_comp_type, "#A0A0A0")

    render_section_header("GAME CONTEXT")
    gc1, gc2 = st.columns(2)
    with gc1:
        st.markdown(
            f"<div style='background:#0A1428;border:1px solid {ally_color}55;border-radius:4px;padding:18px 22px;min-height:126px;'>"
            f"<div style='font-size:12px;color:#A0A0A0;text-transform:uppercase;letter-spacing:1.4px;font-weight:600;'>Your Team Comp</div>"
            f"<div style='font-size:22px;font-weight:700;color:{ally_color};margin-top:8px;line-height:1.2;'>{comp_label(ally_comp_type)}</div>"
            f"<div style='font-size:13px;color:#A0A0A0;margin-top:10px;line-height:1.45;'>{', '.join(ally_champs_for_comp)}</div>"
            f"</div>",
            unsafe_allow_html=True,
        )
    with gc2:
        st.markdown(
            f"<div style='background:#0A1428;border:1px solid {enemy_color}55;border-radius:4px;padding:18px 22px;min-height:126px;'>"
            f"<div style='font-size:12px;color:#A0A0A0;text-transform:uppercase;letter-spacing:1.4px;font-weight:600;'>Enemy Comp</div>"
            f"<div style='font-size:22px;font-weight:700;color:{enemy_color};margin-top:8px;line-height:1.2;'>{comp_label(enemy_comp_type)}</div>"
            f"<div style='font-size:13px;color:#A0A0A0;margin-top:10px;line-height:1.45;'>{', '.join(enemy_champs_for_comp)}</div>"
            f"</div>",
            unsafe_allow_html=True,
        )

    st.markdown(
        f"<div style='background:#010A13;border:1px solid #1E2D40;border-left:3px solid {GOLD_COLOR};"
        f"border-radius:4px;padding:14px 18px;margin:14px 0;'>"
        f"<div style='font-size:11px;color:#A0A0A0;text-transform:uppercase;letter-spacing:1.3px;margin-bottom:8px;'>Role Identity</div>"
        f"<div style='display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:14px;'>"
        f"<div><div style='font-size:10px;color:#5B5A56;text-transform:uppercase;letter-spacing:1px;'>Primary Win Condition</div>"
        f"<div style='font-size:13px;color:#F0E6D3;line-height:1.45;'>{team_identity['primary']}</div></div>"
        f"<div><div style='font-size:10px;color:#5B5A56;text-transform:uppercase;letter-spacing:1px;'>Side Pressure</div>"
        f"<div style='font-size:13px;color:#F0E6D3;line-height:1.45;'>{team_identity['side_carrier']}</div></div>"
        f"<div><div style='font-size:10px;color:#5B5A56;text-transform:uppercase;letter-spacing:1px;'>Fight Core</div>"
        f"<div style='font-size:13px;color:#F0E6D3;line-height:1.45;'>{team_identity.get('fight_core_detail', team_identity['fight_core'])}</div></div>"
        f"<div><div style='font-size:10px;color:#5B5A56;text-transform:uppercase;letter-spacing:1px;'>Your Job</div>"
        f"<div style='font-size:13px;color:#F0E6D3;line-height:1.45;'>{team_identity['player_job']}</div></div>"
        f"</div></div>",
        unsafe_allow_html=True,
    )

    gp1, gp2, gp3, gp4 = st.columns(4)
    _plan_phase_keys = ["lane", "mid_game", "teamfight", "win_condition"]
    _plan_cols = [
        ("Lane Phase",    game_plan.get("lane", ""),          "lane"),
        ("Mid Game",      game_plan.get("mid_game", ""),      "mid_game"),
        ("Teamfight",     game_plan.get("teamfight", ""),     "teamfight"),
        ("Win Condition", game_plan.get("win_condition", ""), "win_condition"),
    ]
    for col, (title, text, phase_key) in zip([gp1, gp2, gp3, gp4], _plan_cols):
        _mechanic_tips = get_contextual_champion_tips(
            sel["champion"],
            phase_key,
            ally_comp_type=ally_comp_type,
            enemy_comp_type=enemy_comp_type,
            enemy_tags=enemy_tags,
            item_tags=set(),
        )
        _mechanic_html = (
            f"<div style='font-size:13px;color:#C8AA6E;margin-top:12px;border-top:1px solid #1E2D40;"
            f"padding-top:10px;line-height:1.5;'>"
            + "".join(f"<div>{sel['champion']}: {tip}</div>" for tip in _mechanic_tips)
            + "</div>"
            if _mechanic_tips else ""
        )
        with col:
            st.markdown(
                f"<div style='background:#010A13;border:1px solid #1E2D4088;border-radius:4px;padding:16px 18px;min-height:170px;'>"
                f"<div style='font-size:13px;color:{ally_color};font-weight:700;margin-bottom:10px;'>{title}</div>"
                f"<div style='font-size:14px;color:#F0E6D3;line-height:1.55;'>{text}</div>"
                f"{_mechanic_html}"
                f"</div>",
                unsafe_allow_html=True,
            )

    st.divider()

    # ─── Section 2: Execution Scorecard ───────────────────────────────────────────
    render_section_header("EXECUTION SCORECARD")
    render_data_quality(data_quality)
    _exec_targets = compute_chall_targets([], sel["position"], sel["champion"], chall_avg)
    _score_rows   = compute_scorecard(sel, _exec_targets, tl_parsed, sel["position"])
    _grade, _grade_desc = compute_grade(_score_rows)
    _grade, _grade_desc = apply_coach_grade_rules(_grade, _grade_desc, _score_rows, sel, chall_avg, data_quality)
    _grade_color = (GREEN_COLOR if _grade in {"S", "A"} else GOLD_COLOR if _grade in {"B+", "B"} else RED_COLOR)
    _top_gaps = get_top_gaps(_score_rows, n=3)  # pre-computed for use in Strategic Verdict + Training Goals

    _sc_left, _sc_right = st.columns([3, 1])
    with _sc_left:
        _table_rows = "".join(
            f"<tr style='border-bottom:1px solid #1E2D40;'>"
            f"<td style='padding:8px 12px;color:#F0E6D3;font-size:13px;'>{r['label']}</td>"
            f"<td style='padding:8px 12px;color:#A0A0A0;font-size:12px;'>{format_scorecard_actual(r)}</td>"
            f"<td style='padding:8px 12px;color:#A0A0A0;font-size:12px;'>{r['target']:.1f}</td>"
            f"<td style='padding:8px 12px;font-size:13px;'>{scorecard_meaning(r)}</td>"
            f"</tr>"
            for r in _score_rows
        )
        st.html(
            "<table style='width:100%;border-collapse:collapse;'>"
            "<thead><tr style='color:#A0A0A0;font-size:11px;text-transform:uppercase;letter-spacing:.08em;'>"
            "<th style='padding:6px 12px;text-align:left;'>Metric</th>"
            "<th style='padding:6px 12px;text-align:left;'>You</th>"
            "<th style='padding:6px 12px;text-align:left;'>Challenger Avg</th>"
            "<th style='padding:6px 12px;text-align:left;'>Meaning</th>"
            "</tr></thead>"
            f"<tbody>{_table_rows}</tbody></table>"
        )
        st.caption(f"Benchmark: {benchmark_label}")
    with _sc_right:
        st.markdown(
            f"<div style='background:#0A1428;border:2px solid {_grade_color};border-radius:4px;"
            f"padding:20px;text-align:center;'>"
            f"<div style='font-size:11px;color:#A0A0A0;text-transform:uppercase;letter-spacing:.08em;'>Performance Grade</div>"
            f"<div style='font-size:64px;font-weight:900;color:{_grade_color};line-height:1.1;margin-top:6px;'>{_grade}</div>"
            f"<div style='font-size:12px;color:#F0E6D3;margin-top:8px;line-height:1.4;'>{_grade_desc}</div>"
            f"</div>",
            unsafe_allow_html=True,
        )

    st.divider()

    # ─── Section 3: Runes & Spells ────────────────────────────────────────────────
    render_section_header("RUNES & SPELLS")
    _rune_eval = evaluate_runes(
        champion=sel["champion"],
        position=sel["position"],
        keystone_id=sel.get("keystone_id", 0),
        spell1_id=sel.get("spell1_id", 0),
        spell2_id=sel.get("spell2_id", 0),
        ally_comp_type=ally_comp_type,
        enemy_comp_type=enemy_comp_type,
    )
    def _tier_color(tier: str) -> str:
        return {
            "optimal":    GREEN_COLOR,
            "situational": GOLD_COLOR,
            "unusual":    "#A0A0A0",
        }.get(tier, GOLD_COLOR)

    _rune_color  = _tier_color(_rune_eval["keystone_tier"])
    _spell_color = _tier_color(_rune_eval["spell_tier"])
    _r1, _r2 = st.columns(2)
    with _r1:
        st.markdown(
            f"<div style='background:#0A1428;border:1px solid {_rune_color}55;border-radius:4px;padding:14px 18px;'>"
            f"<div style='font-size:11px;color:#A0A0A0;text-transform:uppercase;letter-spacing:.08em;'>Keystone Rune</div>"
            f"<div style='font-size:16px;font-weight:700;color:{_rune_color};margin-top:6px;'>"
            f"{_rune_eval['keystone_icon']} {_rune_eval['keystone_name']}</div>"
            f"<div style='font-size:12px;color:#F0E6D3;margin-top:6px;line-height:1.4;'>{_rune_eval['keystone_note']}</div>"
            f"</div>",
            unsafe_allow_html=True,
        )
    with _r2:
        _spell_names = f"{_rune_eval['spell1_name']} + {_rune_eval['spell2_name']}"
        st.markdown(
            f"<div style='background:#0A1428;border:1px solid {_spell_color}55;border-radius:4px;padding:14px 18px;'>"
            f"<div style='font-size:11px;color:#A0A0A0;text-transform:uppercase;letter-spacing:.08em;'>Summoner Spells</div>"
            f"<div style='font-size:16px;font-weight:700;color:{_spell_color};margin-top:6px;'>"
            f"{_rune_eval['spell_icon']} {_spell_names}</div>"
            f"<div style='font-size:12px;color:#F0E6D3;margin-top:6px;line-height:1.4;'>{_rune_eval['spell_note']}</div>"
            f"</div>",
            unsafe_allow_html=True,
        )

    st.divider()

    # ─── Benchmark stat cards ─────────────────────────────────────────────────────
    render_section_header(f"POSITION PRIORITIES VS CHALLENGER ({sel['champion']} · {POSITION_MAP.get(sel['position'], sel['position'])})")
    render_metric_cards(sel, chall_avg)

    # ─── Timeline section ─────────────────────────────────────────────────────────
    render_section_header("TIMELINE ANALYSIS")
    if tl_parsed:
        render_timeline_cards(tl_parsed, sel["position"])

        render_section_header("GOLD DIFFERENCE VS ENEMY LANER")
        render_gold_diff_chart(tl_parsed, tl_parsed.get("first_death_minute"), win=sel["win"])

        render_section_header("CS ACCUMULATION VS ENEMY LANER")
        render_cs_curve_chart(tl_parsed, sel["position"])

        with st.expander("Replay Checkpoints", expanded=False):
            render_replay_checkpoints(replay_checkpoints)
    else:
        st.caption("Timeline data unavailable — showing standard analysis only.")

    # ─── Build comparison ─────────────────────────────────────────────────────────

    # ── Build style detection ──────────────────────────────────────────────────────
    _ENCHANTER_ITEMS = {
        "Dream Maker", "Moonstone Renewer", "Echoes of Helia", "Dawncore",
        "Staff of Flowing Water", "Ardent Censer", "Imperial Mandate",
        "Shurelya's Battlesong", "Redemption", "Mikael's Blessing",
    }
    _DAMAGE_SUPP_ITEMS = {
        "Luden's Companion", "Luden's Tempest", "Shadowflame", "Horizon Focus",
        "Cryptbloom", "Zaz'Zak's Realmspike", "Stormsurge", "Liandry's Torment",
        "Liandry's Anguish", "Seraph's Embrace", "Archangel's Staff",
        "Lich Bane", "Rabadon's Deathcap",
    }
    _TANK_SUPP_ITEMS = {
        "Locket of the Iron Solari", "Knight's Vow", "Zeke's Convergence",
        "Warmog's Armor", "Sunfire Aegis", "Gargoyle Stoneplate",
        "Heartsteel", "Frozen Heart",
    }
    _CRIT_ADC_ITEMS = {
        "Infinity Edge", "Galeforce", "Kraken Slayer", "Navori Flickerblade",
        "Phantom Dancer", "Runaan's Hurricane",
    }
    _ONHIT_ADC_ITEMS = {
        "Guinsoo's Rageblade", "Blade of the Ruined King", "Wit's End",
        "Nashor's Tooth", "Recurve Bow",
    }

    def _detect_build_style(item_names_list: list[str], position: str) -> str:
        if position == "UTILITY":
            enchanter  = sum(1 for i in item_names_list if i in _ENCHANTER_ITEMS)
            damage     = sum(1 for i in item_names_list if i in _DAMAGE_SUPP_ITEMS)
            tank       = sum(1 for i in item_names_list if i in _TANK_SUPP_ITEMS)
            if damage >= 2:   return "damage"
            if tank >= 2:     return "tank"
            if enchanter >= 1: return "enchanter"
            return "enchanter"
        elif position == "BOTTOM":
            crit   = sum(1 for i in item_names_list if i in _CRIT_ADC_ITEMS)
            onhit  = sum(1 for i in item_names_list if i in _ONHIT_ADC_ITEMS)
            return "on-hit" if onhit >= 2 and onhit > crit else "crit"
        return "standard"


    def _get_style_optimal(champion: str, position: str, style: str, matches: list) -> list[int]:
        """Find the most common items in winning Challenger games that match build style."""
        from collections import Counter
        item_counter: Counter = Counter()
        for match in matches:
            for p in match.get("info", {}).get("participants", []):
                if p.get("championName") != champion or p.get("teamPosition") != position:
                    continue
                if not p.get("win"):
                    continue
                p_items = [get_item_name(p.get(f"item{i}", 0)) for i in range(6)]
                p_items = [n for n in p_items if n]
                p_style = _detect_build_style(p_items, position)
                if p_style == style:
                    for iid in (p.get(f"item{i}", 0) for i in range(6)):
                        if iid and iid != 0:
                            item_counter[iid] += 1
        return [iid for iid, _ in item_counter.most_common(6)]


    render_section_header("BUILD COMPARISON")
    optimal_builds = load_optimal_builds()
    my_items         = [iid for iid in sel["items"] if iid != 0]
    my_item_names_preview = [get_item_name(i) for i in my_items]
    player_style     = _detect_build_style(my_item_names_preview, sel["position"])

    # Style-aware reference lookup
    style_optimal_ids = _get_style_optimal(sel["champion"], sel["position"], player_style, challenger_matches)
    if not style_optimal_ids:
        # Fallback to the existing benchmark cache if no style data exists.
        style_optimal_ids = [iid for iid in optimal_builds.get((sel["champion"], sel["position"]), []) if iid != 0]

    optimal_items            = style_optimal_ids
    optimal_item_names_preview = [get_item_name(i) for i in optimal_items]

    # Style label for UI
    _STYLE_LABELS = {
        "damage": "AP Damage", "enchanter": "Enchanter", "tank": "Tank Support",
        "crit": "Crit ADC", "on-hit": "On-Hit ADC", "standard": "Standard",
    }
    style_label = _STYLE_LABELS.get(player_style, player_style.title())

    col_my, col_opt = st.columns(2)
    with col_my:
        st.caption(f"Your Build — {style_label} style")
        st.html(f"<div style='display:flex;gap:6px;flex-wrap:wrap;align-items:center;'>{render_items_row(my_items, item_names, 40)}</div>")
    with col_opt:
        st.caption(f"Challenger Reference — Common {style_label} {sel['champion']} {POSITION_MAP.get(sel['position'], sel['position'])}")
        st.html(f"<div style='display:flex;gap:6px;flex-wrap:wrap;align-items:center;'>{render_items_row(optimal_items, item_names, 40)}</div>")

    # Build overlap analysis (same-style comparison)
    matched_items_preview  = [n for n in my_item_names_preview if n in optimal_item_names_preview]
    extra_items_preview    = [n for n in my_item_names_preview  if n not in optimal_item_names_preview]
    missing_items_preview  = [n for n in optimal_item_names_preview if n not in my_item_names_preview]
    item_overlap_preview   = len(matched_items_preview)

    overlap_pct   = int(item_overlap_preview / max(len(optimal_item_names_preview), 1) * 100)
    # Situational mismatch tags
    situation_tags = []
    burst_threats_preview = enemy_threats["burst"]
    tank_threats_preview = enemy_threats["tank"]
    cc_threats_preview = enemy_threats["cc"]
    engage_threats_preview = enemy_threats["engage"]
    heal_threats_preview = enemy_threats["heal"]
    item_tags_preview = get_item_tags(my_item_names_preview)
    built_locket_preview = "locket" in item_tags_preview
    built_mikael_preview = "mikael" in item_tags_preview
    built_morello_preview = "anti_heal" in item_tags_preview
    anti_burst_covered_preview = "anti_burst" in item_tags_preview
    cc_covered_preview = built_mikael_preview or has_item_tag(my_item_names_preview, "banshee")

    if burst_threats_preview and not anti_burst_covered_preview:
        situation_tags.append(f"Anti-burst item vs {', '.join(burst_threats_preview[:2])}")
    if tank_threats_preview and "Void Staff" not in my_item_names_preview and sel["position"] != "UTILITY":
        situation_tags.append(f"Void Staff vs {', '.join(tank_threats_preview[:2])}")
    if cc_threats_preview and not cc_covered_preview:
        situation_tags.append(f"CC answer vs {', '.join(cc_threats_preview[:2])}")
    if heal_threats_preview and not built_morello_preview:
        situation_tags.append(f"Anti-heal vs {', '.join(heal_threats_preview[:2])}")

    covered_tags = []
    if built_locket_preview and (burst_threats_preview or engage_threats_preview):
        covered_tags.append(
            f"Locket covers first engage from {', '.join((engage_threats_preview or burst_threats_preview)[:2])}"
        )
    if built_mikael_preview and cc_threats_preview:
        covered_tags.append(f"Mikael's answers CC from {', '.join(cc_threats_preview[:2])}")
    if built_morello_preview and heal_threats_preview:
        covered_tags.append(f"Anti-heal answers {', '.join(heal_threats_preview[:2])}")

    enemy_win_plan_bits = []
    if engage_threats_preview:
        enemy_win_plan_bits.append(f"hard engage ({', '.join(engage_threats_preview[:2])})")
    if burst_threats_preview:
        enemy_win_plan_bits.append(f"burst follow-up ({', '.join(burst_threats_preview[:2])})")
    if cc_threats_preview:
        enemy_win_plan_bits.append(f"CC chain ({', '.join(cc_threats_preview[:2])})")
    if heal_threats_preview:
        enemy_win_plan_bits.append(f"sustain ({', '.join(heal_threats_preview[:2])})")
    enemy_win_plan = "; ".join(enemy_win_plan_bits) or "standard front-to-back fights"

    seraphine_locket_fit = (
        sel["champion"] == "Seraphine"
        and built_locket_preview
        and (burst_threats_preview or engage_threats_preview)
    )
    if seraphine_locket_fit:
        fit_label = "SMART SITUATIONAL ADAPTATION"
        fit_color = GREEN_COLOR
        fit_text = (
            "Locket is justified here: it absorbs the first engage burst, then Seraphine W/double-W can "
            "speed, shield, heal, and reset the fight."
        )
    elif covered_tags:
        fit_label = "MATCHUP NEED COVERED"
        fit_color = GREEN_COLOR
        fit_text = "Your build directly answers this enemy win condition: " + "; ".join(covered_tags[:2]) + "."
    elif situation_tags:
        fit_label = "SITUATIONAL GAP"
        fit_color = GOLD_COLOR
        fit_text = "Consider whether the build needs: " + "; ".join(situation_tags[:2]) + "."
    elif overlap_pct < 50:
        fit_label = "DIFFERENT BUT DEFENSIBLE"
        fit_color = GOLD_COLOR
        fit_text = "The path differs from the reference, but no urgent counter-item gap was detected."
    else:
        fit_label = "STANDARD PATH"
        fit_color = GREEN_COLOR
        fit_text = "Your items are close enough to the reference and cover the visible enemy threats."

    oc1, oc2 = st.columns(2)
    with oc1:
        extra_text   = ", ".join(extra_items_preview)   if extra_items_preview   else "—"
        missing_text = ", ".join(missing_items_preview) if missing_items_preview else "—"
        st.markdown(
            f"<div style='background:#0A1428;border:1px solid #1E2D4055;border-radius:4px;padding:12px 16px;'>"
            f"<div style='font-size:11px;color:#A0A0A0;text-transform:uppercase;margin-bottom:6px;'>Build Intent ({style_label})</div>"
            f"<div style='font-size:12px;color:#F0E6D3;line-height:1.5;'><span style='color:{GOLD_COLOR};'>Enemy win plan:</span> {enemy_win_plan}</div>"
            f"<div style='font-size:12px;color:#F0E6D3;line-height:1.5;margin-top:6px;'><span style='color:{GOLD_COLOR};'>Your adaptation:</span> {extra_text}</div>"
            f"<div style='font-size:11px;color:#A0A0A0;margin-top:6px;line-height:1.4;'>Reference alternatives: {missing_text}</div>"
            f"</div>", unsafe_allow_html=True,
        )
    with oc2:
        st.markdown(
            f"<div style='background:#0A1428;border:1px solid {fit_color}55;border-radius:4px;padding:12px 16px;'>"
            f"<div style='font-size:11px;color:#A0A0A0;text-transform:uppercase;margin-bottom:4px;'>Situational Verdict</div>"
            f"<div style='font-size:12px;color:{fit_color};font-weight:700;letter-spacing:1px;text-transform:uppercase;'>{fit_label}</div>"
            f"<div style='font-size:12px;color:#F0E6D3;line-height:1.5;margin-top:8px;'>{fit_text}</div>"
            f"</div>",
            unsafe_allow_html=True,
        )

    reference_note = (
        "Use the reference build as a high-rank baseline, not a rulebook. "
        "Path differences can be valid when they fit lane state, gold timing, or team plan."
    )
    if seraphine_locket_fit or covered_tags:
        reference_note += " Your situational items cover the enemy's main fight pattern, so low overlap is not automatically bad."
    elif situation_tags:
        reference_note += " The matchup check is the higher-priority signal here because it flags enemy-specific item needs."
    else:
        reference_note += " The matchup check found no urgent anti-heal, anti-burst, anti-CC, or tank-response gap."
    st.markdown(
        f"<div style='background:#010A13;border:1px solid #1E2D40;border-left:3px solid {GOLD_COLOR};"
        f"border-radius:4px;padding:12px 16px;margin-top:12px;'>"
        f"<div style='font-size:11px;color:#A0A0A0;text-transform:uppercase;letter-spacing:1px;margin-bottom:4px;'>How to read this</div>"
        f"<div style='font-size:13px;color:#F0E6D3;line-height:1.6;'>{reference_note}</div>"
        f"</div>",
        unsafe_allow_html=True,
    )

    # ─── Role impact chart ────────────────────────────────────────────────────────
    render_role_impact_chart(sel)

    with st.expander("FULL SCOREBOARD", expanded=False):
        render_scoreboard(sel, item_names)

    st.divider()

    # ─── Section 5: Coach Review ───────────────────────────────────────────────
    render_section_header("POST-GAME REVIEW")

    champ_wr, best_champ_wr = get_rank_meta_context(rank_matches or challenger_matches, sel["champion"], sel["position"])

    my_item_names         = my_item_names_preview
    optimal_item_names    = optimal_item_names_preview
    extra_items           = extra_items_preview
    missing_items         = missing_items_preview
    item_overlap          = item_overlap_preview

    enemy_laner_str = sel.get("enemy_laner") or "Unknown"
    enemy_champs    = sel["enemy_champions"]
    ally_champs     = sel["ally_champions"]

    burst_threats    = burst_threats_preview
    tank_threats     = tank_threats_preview
    cc_threats       = cc_threats_preview
    engage_threats   = engage_threats_preview
    heal_threats     = heal_threats_preview
    built_locket     = built_locket_preview
    needs_anti_burst = bool(burst_threats or engage_threats) and not anti_burst_covered_preview
    needs_void_staff = bool(tank_threats)  and "Void Staff"          not in my_item_names and sel["position"] != "UTILITY"
    needs_cc_answer  = bool(cc_threats) and not cc_covered_preview
    needs_morello    = bool(heal_threats) and not built_morello_preview

    enemy_comp_str = ", ".join(enemy_champs)

    death_info = {}
    if timeline_raw and summoner:
        death_info = analyze_deaths(summoner["puuid"], timeline_raw)

    early_deaths = death_info.get("early_deaths", "N/A")
    mid_deaths   = death_info.get("mid_deaths",   "N/A")
    late_deaths  = death_info.get("late_deaths",  "N/A")
    first_death_min_str = (
        f"minute {death_info['first_death_minute']}"
        if death_info.get("first_death_minute") is not None
        else (f"minute {tl_parsed['first_death_minute']}" if tl_parsed and tl_parsed.get("first_death_minute") else "unknown")
    )

    cs10 = ecs10 = gold10 = item_min = "N/A"
    if tl_parsed:
        cs10     = tl_parsed["cs_at_10"]
        ecs10    = tl_parsed["enemy_cs_at_10"]
        gold10   = tl_parsed["gold_diff_by_minute"].get(10, "N/A")
        item_min = tl_parsed["first_item_minute"] or "N/A"
    cs10_note = (
        f"{cs10} (enemy laner: {ecs10}, diff: {(cs10 - ecs10) if isinstance(cs10, int) and isinstance(ecs10, int) else 'N/A'})"
        if data_quality["reliable"].get("lane")
        else f"{cs10} (unreliable or unavailable; excluded from lane diagnosis)"
    )

    vision_gap = sel["vision"] - chall_avg.get("vision", 0)
    if vision_gap < -15:
        vision_note = "Low vision score is a real objective-control risk in this match."
    elif vision_gap > 15:
        vision_note = "Vision was a measurable strength; corrections should focus on timing/safety only if death or threat data supports it."
    else:
        vision_note = "Vision was close to benchmark; do not overstate it as the main issue without supporting death/objective evidence."

    match_summary = f"""\
=== MATCH OVERVIEW ===
Player: {game_name}#{tag_line}
Champion: {sel['champion']} ({POSITION_MAP.get(sel['position'], sel['position'])})
Result: {'VICTORY' if sel['win'] else 'DEFEAT'}
Duration: {sel['duration']} minutes
Champion win rate this patch: {champ_wr}% (Challenger best for this role: {best_champ_wr}%)

=== TEAM COMPOSITIONS ===
Your Team: {sel['champion']}, {', '.join(ally_champs)}
Enemy Team: {', '.join(enemy_champs)}
Your Lane Opponent: {enemy_laner_str}
Team identity: {team_identity['primary']}
Side pressure carrier: {team_identity['side_carrier']}
Fight core: {team_identity.get('fight_core_detail', team_identity['fight_core'])}
Your role in this comp: {team_identity['player_job']}

=== DATA QUALITY ===
Confidence: {data_quality['confidence']}
Issues: {'; '.join(data_quality['issues']) if data_quality['issues'] else 'No major timeline quality issues detected'}

=== ENEMY THREAT ANALYSIS ===
Burst Damage Threats ({len(burst_threats)}): {burst_threats if burst_threats else 'None'}
Engage Threats ({len(engage_threats)}): {engage_threats if engage_threats else 'None'}
Tanks ({len(tank_threats)}): {tank_threats if tank_threats else 'None'}
Heavy CC ({len(cc_threats)}): {cc_threats if cc_threats else 'None'}
Healing Champions ({len(heal_threats)}): {heal_threats if heal_threats else 'None'}
Enemy win plan: {enemy_win_plan}
Anti-burst covered by current items: {anti_burst_covered_preview}
Locket built: {built_locket}
Seraphine + Locket synergy: {seraphine_locket_fit}
Needs additional anti-burst: {needs_anti_burst}
Needs Void Staff vs tanks: {needs_void_staff}
Needs CC answer: {needs_cc_answer}
Needs anti-heal: {needs_morello}

=== PERFORMANCE VS CHALLENGER AVERAGE ({sel['champion']} {POSITION_MAP.get(sel['position'], sel['position'])}) ===
KDA: {sel['kills']}/{sel['deaths']}/{sel['assists']} (ratio: {sel['kda']:.2f} vs Challenger avg {chall_avg.get('kda', 0):.2f})
Damage: {sel['damage']:,} vs Challenger avg {chall_avg.get('damage', 0):,.0f} ({sel['damage'] - chall_avg.get('damage', 0):+,.0f})
CS/min: {sel['cs_per_min']:.1f} vs Challenger avg {chall_avg.get('cs_per_min', 0):.1f} ({sel['cs_per_min'] - chall_avg.get('cs_per_min', 0):+.1f})
Vision Score: {sel['vision']} vs Challenger avg {chall_avg.get('vision', 0):.0f} ({sel['vision'] - chall_avg.get('vision', 0):+.0f})
Kill Participation: {sel['kp']}%
Damage share of team: {sel['damage_share']}% vs Challenger avg {chall_avg.get('damage_share', 0):.1f}%

=== DEATH BREAKDOWN ===
Total Deaths: {sel['deaths']} vs Challenger avg {chall_avg.get('deaths', 0):.1f}
Early deaths (before min 15 — laning phase): {early_deaths}
Mid game deaths (min 15-25 — skirmish phase): {mid_deaths}
Late deaths (after min 25 — teamfight phase): {late_deaths}
First death: {first_death_min_str}
All death timestamps: {', '.join(format_minute(m) for m in tl_parsed.get('death_minutes', [])) if tl_parsed else 'N/A'}

=== TIMELINE DATA ===
CS at minute 10: {cs10_note}
Gold difference at minute 10: {gold10}
First core item completed: minute {item_min} (Challenger avg: {CHALL_AVG_ITEM_MIN} min)
Objective timestamps: {', '.join(f"{event.get('type')} at {format_minute(event.get('minute'))}" for event in tl_parsed.get('objective_events', [])) if tl_parsed else 'N/A'}

=== ITEM BUILD ANALYSIS ===
Your items: {', '.join(my_item_names) if my_item_names else 'None built'}
Challenger optimal: {', '.join(optimal_item_names) if optimal_item_names else 'Unknown'}
Items you built that Challengers skip: {', '.join(extra_items) if extra_items else 'None'}
Items Challengers build that you skipped: {', '.join(missing_items) if missing_items else 'None'}
Item match score: {item_overlap}/{max(len(optimal_item_names), 1)} vs Challenger optimal
Build intent verdict: {fit_label} - {fit_text}
Covered matchup needs: {', '.join(covered_tags) if covered_tags else 'None'}
Open matchup item gaps: {', '.join(situation_tags) if situation_tags else 'None'}

=== VISION CONTROL ===
Wards placed: {sel['wards_placed']} (Challenger avg for this position: {chall_avg.get('wards_placed', 0):.0f})
Control wards bought: {sel['vision_wards']}
Wards destroyed: {sel['wards_killed']}
Vision score: {sel['vision']} vs Challenger avg {chall_avg.get('vision', 0):.0f} ({sel['vision'] - chall_avg.get('vision', 0):+.0f})
Note: {vision_note}
"""

    if st.session_state.get("selected_match_id") != sel["match_id"]:
        st.session_state["selected_match_id"] = sel["match_id"]
        st.session_state["chat_chain"]        = None

    import re as _re
    def _clean_llm_md(text: str) -> str:
        return _re.sub(r'\*{2,3}([^*]+)\*{2,3}', r'\1', text)

    def _get_chat_chain():
        chain = st.session_state.get("chat_chain")
        if chain is None:
            chain = create_chat_chain(match_summary)
            st.session_state["chat_chain"] = chain
        return chain

    # Only show metrics where the player is actually BELOW Challenger avg
    _below_avg_gaps = [
        r for r in _score_rows
        if r.get("reliable", True)
        if (r["lower"] and r["delta"] > 0) or (not r["lower"] and r["delta"] < 0)
    ]
    _training_gaps = sorted(_below_avg_gaps, key=lambda r: r["score"])[:3]

    _reliable_rows = [r for r in _score_rows if r.get("reliable", True)]
    _severe_gaps = [r for r in _reliable_rows if r["score"] < 0.5]
    _primary_gap = _training_gaps[0] if _training_gaps else (_top_gaps[0] if _top_gaps else None)
    _primary_failure_text = format_primary_failure(_primary_gap)
    _positive_rows = [
        r for r in _reliable_rows
        if (r["lower"] and r["delta"] <= 0) or (not r["lower"] and r["delta"] >= 0)
    ]
    _positive_row = max(_positive_rows, key=lambda r: r["score"], default=None)
    _positive_signal_text = (
        f"{_positive_row['label']} was a real positive: {_positive_row['actual']:.1f} vs Challenger avg {_positive_row['target']:.1f}. "
        "Keep this habit, but convert the awareness into safer execution around the primary failure."
        if _positive_row else
        "No clear above-benchmark positive stood out; focus this review on the primary failure first."
    )
    _high_kp_loss = (
        not sel["win"]
        and sel.get("kp", 0) >= chall_avg.get("kp", 0) + 8
        and sel.get("damage", 0) < chall_avg.get("damage", 0)
        and sel.get("deaths", 0) > chall_avg.get("deaths", 0)
    )
    if data_quality["confidence"] == "LOW":
        diagnosis_kicker = "Confidence is low; verify timeline fields before assigning lane blame."
        diagnosis_body = "This report should guide replay review, not pretend uncertain data is proof. Use reliable box-score gaps and turning-point timestamps first."
        diagnosis_color = GOLD_COLOR
    elif _high_kp_loss:
        diagnosis_kicker = f"Primary failure: {_primary_failure_text}."
        diagnosis_body = (
            f"KP was {sel['kp']}%, but damage was {sel['damage']:,} vs Challenger avg "
            f"{chall_avg.get('damage', 0):,.0f} and deaths were {sel['deaths']} vs avg {chall_avg.get('deaths', 0):.1f}. "
            "This points to possible low-quality fight participation."
        )
        diagnosis_color = RED_COLOR
    elif _primary_gap and not sel["win"]:
        diagnosis_kicker = f"Primary failure: {_primary_failure_text}."
        diagnosis_body = f"Grade {_grade}: {_grade_desc} Do not over-focus on secondary positives until this failure is checked in replay."
        diagnosis_color = RED_COLOR if _severe_gaps else GOLD_COLOR
    elif _primary_gap:
        diagnosis_kicker = f"Primary review priority: {_primary_failure_text}."
        diagnosis_body = f"Grade {_grade}: {_grade_desc} Keep the winning pattern, but verify whether this gap would punish you in a closer game."
        diagnosis_color = GOLD_COLOR
    else:
        diagnosis_kicker = "No single benchmark gap dominated the review."
        diagnosis_body = f"Grade {_grade}: {_grade_desc} Focus the replay on decision quality around lane exits and objective setup."
        diagnosis_color = GREEN_COLOR

    role_kicker = team_identity["player_job"]
    role_body = (
        f"Team identity: {team_identity['primary']}. Side pressure: {team_identity['side_carrier']}. "
        f"Fight core: {team_identity.get('fight_core_detail', team_identity['fight_core'])}. "
        f"Judge {sel['champion']} by this player's job: {team_identity['player_job']} "
        "Do not treat a peel support, side-laner, or frontline engage role as the reviewed player's job."
    )

    _turning_points = []
    if replay_checkpoints:
        _turning_points = [
            (
                f"{cp.get('timestamp', 'unknown')} - {cp.get('label', cp.get('title', 'Replay check'))}. "
                f"Hypothesis: {cp.get('hypothesis', 'verify the fight setup in replay')}. "
                f"Evidence: {cp.get('evidence', 'timeline timestamp only')}."
            )
            for cp in replay_checkpoints[:3]
        ]
    else:
        if first_death_min_str != "unknown":
            _turning_points.append(f"{first_death_min_str} - first death")
        if item_min != "N/A":
            _turning_points.append(f"minute {item_min} - first core item timing")
        if tl_parsed and tl_parsed.get("objective_events"):
            event = tl_parsed["objective_events"][0]
            _turning_points.append(f"{format_minute(event.get('minute'))} - first {event.get('type')} setup")
    if not _turning_points:
        _turning_points = ["Replay unavailable - start with first death, first recall, and first objective setup."]
    turning_kicker = "Review these moments before changing your next-game plan."
    turning_body = " / ".join(_turning_points)

    if not data_quality["reliable"].get("lane"):
        priority_kicker = "First priority: validate lane data in replay."
        priority_body = "Check first three waves, first recall, and first death. Do not build lane conclusions from unreliable CS@10."
    elif _high_kp_loss:
        priority_kicker = "First priority: separate good grouping from forced losing fights."
        priority_body = "For each joined fight, ask: did we have wave push, vision entry, item timing, and a clear frontline path?"
    elif _primary_gap and _primary_gap["key"] in {"deaths", "deaths_pre_15"}:
        priority_kicker = "First priority: cut the first two preventable deaths."
        priority_body = "Before walking into lane or river fog, confirm wave state, enemy threat location, and defensive cooldown availability."
    elif _primary_gap and _primary_gap["key"] in {"vision", "roam_count"}:
        priority_kicker = "First priority: arrive earlier to objective setup."
        priority_body = "Move with support/jungle before the timer; late vision entry turns your teamfight comp into a face-check comp."
    elif _primary_gap and _primary_gap["key"] in {"cs_per_min", "cs_diff_10", "first_item_min"}:
        priority_kicker = "First priority: repair economy before forcing map plays."
        priority_body = "Hold lane resources and recall on item windows; bad roams from weak waves delay the spike your comp needs."
    else:
        priority_kicker = "First priority: review whether your role matched the comp plan."
        priority_body = "Use the role identity above as the standard: stabilize, move first when allowed, and enter fights with the correct cooldowns."

    final_review_cards = [
        ("Coach Diagnosis", diagnosis_kicker, diagnosis_body, diagnosis_color),
        ("Role Responsibility", role_kicker, role_body, CYAN_COLOR),
        ("Turning Points", turning_kicker, turning_body, GOLD_COLOR),
        ("One Priority Fix", priority_kicker, priority_body, GREEN_COLOR if sel["win"] else RED_COLOR),
    ]
    render_coach_final_review(final_review_cards)

    checkpoint_packet = "; ".join(
        (
            f"{cp.get('timestamp', 'unknown')} {cp.get('label', cp.get('title', 'Replay check'))}: "
            f"hypothesis={cp.get('hypothesis', 'verify setup in replay')}; "
            f"evidence={cp.get('evidence', 'timestamp only')}; "
            + " / ".join(cp.get("questions", [])[:2])
        )
        for cp in replay_checkpoints[:3]
    ) or turning_body
    data_health_packet = (
        f"Confidence {data_quality['confidence']}; "
        f"{'; '.join(data_quality['issues']) if data_quality['issues'] else 'timeline, lane, death, gold, and item timing passed basic checks'}"
    )
    metric_packet = (
        f"Result {'WIN' if sel['win'] else 'LOSS'}; Grade {_grade}; "
        f"KDA {sel['kills']}/{sel['deaths']}/{sel['assists']} ({sel['kda']:.2f} vs avg {chall_avg.get('kda', 0):.2f}); "
        f"Damage {sel['damage']:,} vs avg {chall_avg.get('damage', 0):,.0f}; "
        f"Vision {sel['vision']} vs avg {chall_avg.get('vision', 0):.0f}; "
        f"KP {sel['kp']:.1f}%; CS/min {sel['cs_per_min']:.1f} vs avg {chall_avg.get('cs_per_min', 0):.1f}; "
        f"Deaths {sel['deaths']} vs avg {chall_avg.get('deaths', 0):.1f}."
    )
    deterministic_report_text = "\n".join(
        f"{title}: {kicker} {body}" for title, kicker, body, _ in final_review_cards
    )
    deterministic_report_text = "\n".join(
        [
            deterministic_report_text,
            f"Primary Failure: {_primary_failure_text}",
            f"Positive Signal: {_positive_signal_text}",
            f"Match Metrics: {metric_packet}",
            f"Data Health: {data_health_packet}",
            f"Replay Checkpoints: {checkpoint_packet}",
        ]
    )
    st.divider()
    render_phase_analysis(build_phase_analysis(sel, chall_avg, tl_parsed))

    st.divider()

    # ── Deterministic review focus: stable context for the AI report.
    if situation_tags:
        item_read = f"Enemy win plan: {enemy_win_plan}. Open item question: {', '.join(situation_tags[:2])}."
    elif covered_tags:
        item_read = f"Your item path answered the main fight pattern: {', '.join(covered_tags[:2])}."
    else:
        item_read = f"Build was a reference check only. Enemy win plan: {enemy_win_plan}."

    if built_locket and (burst_threats or engage_threats):
        item_adjust = "Treat Locket as an anti-first-combo choice: hold it for the engage burst, then use Seraphine W/double-W to reset the fight."
    elif needs_anti_burst:
        item_adjust = "Plan one real anti-burst answer before major fights: Locket/Celestial for support, or Zhonya/Banshee plus safer spacing for carries."
    elif needs_cc_answer:
        item_adjust = "Respect the CC chain first. Consider Mikael/Banshee when your role can buy it, and avoid entering fog before frontline."
    elif needs_morello:
        item_adjust = "Anti-heal is only a priority because this enemy comp has sustain threats; buy it when fights last long enough for healing to matter."
    else:
        item_adjust = "Do not grade the build by overlap alone. Ask whether each completed item solved the next fight window."

    objective_events = tl_parsed.get("objective_events", []) if tl_parsed else []
    objective_text = (
        ", ".join(f"{event.get('type')} at {format_minute(event.get('minute'))}" for event in objective_events[:3])
        if objective_events else "Riot timeline did not expose reliable objective timestamps."
    )
    vision_gap = sel["vision"] - chall_avg.get("vision", 0)
    if vision_gap >= 10:
        objective_read = f"Vision was a strength: {sel['vision']} vs Challenger avg {chall_avg.get('vision', 0):.0f} ({vision_gap:+.0f})."
        objective_adjust = "Convert the vision lead into first move. Set river control before the timer, then make the enemy face-check into your poke/CC."
    elif vision_gap < -10:
        objective_read = f"Vision was behind benchmark: {sel['vision']} vs Challenger avg {chall_avg.get('vision', 0):.0f} ({vision_gap:+.0f})."
        objective_adjust = "Move earlier with jungle/support before objective spawn; do not enter river alone after the enemy already owns fog."
    else:
        objective_read = f"Vision was close to benchmark: {sel['vision']} vs Challenger avg {chall_avg.get('vision', 0):.0f} ({vision_gap:+.0f})."
        objective_adjust = "The review question is timing: did you arrive before the fight, or only after the objective had started?"

    if data_quality["reliable"].get("lane") and isinstance(cs10, int) and isinstance(ecs10, int):
        lane_delta_text = f"CS@10 {cs10} vs enemy {ecs10} ({cs10 - ecs10:+d})."
        if cs10 - ecs10 >= 10:
            early_read = f"You had lane resource control. {lane_delta_text}"
            early_adjust = "When lane is winning, the coaching question is conversion: crash wave, move first, and turn pressure into dragon or enemy jungle vision."
        elif cs10 - ecs10 <= -10:
            early_read = f"Lane economy was under pressure. {lane_delta_text}"
            early_adjust = "Stabilize the wave before roaming. A bad roam from a losing wave costs plates, CS, and objective tempo."
        else:
            early_read = f"Lane was not decided by CS alone. {lane_delta_text}"
            early_adjust = "Review trading pattern and wave state before first river move; small lane edges only matter if they create first move."
    else:
        early_read = "CS@10 and enemy lane comparison were not available from timeline data."
        early_adjust = "Use replay to check the first three wave states, first recall, and whether the first roam had lane priority."

    render_review_focus([
        (
            "ITEM DECISION",
            [("Read", item_read), ("Evidence", fit_text), ("Coach cue", item_adjust)],
            GOLD_COLOR,
        ),
        (
            "OBJECTIVE SETUP",
            [("Read", objective_read), ("Evidence", objective_text), ("Coach cue", objective_adjust)],
            GREEN_COLOR if vision_gap >= 0 else RED_COLOR,
        ),
        (
            "EARLY PRESSURE",
            [("Read", early_read), ("Evidence", f"First death: {first_death_min_str}; gold@10: {gold10}."), ("Coach cue", early_adjust)],
            CYAN_COLOR if data_quality["reliable"].get("lane") and isinstance(cs10, int) and isinstance(ecs10, int) and cs10 >= ecs10 else GOLD_COLOR,
        ),
    ])

    st.divider()

    ai_coach_key = f"ai_coach_report_v3_{sel['match_id']}"
    ai_coach_sources_key = f"{ai_coach_key}_sources"
    render_section_header("AI COACH REPORT")
    st.caption("Orchestrated agent: coach engine facts + champion knowledge + RAG context + reflection guardrails.")
    if st.session_state.get(ai_coach_key) is None:
        if st.button("RUN AI COACH REPORT", type="primary", key=f"run_{ai_coach_key}"):
            with st.spinner("AI coach is reviewing the match..."):
                report, sources = run_ai_coach_report_agent(
                    coach_context=deterministic_report_text,
                    match_data=match_summary,
                    timeline_data=timeline_data_str or "No timeline data.",
                    champion=sel["champion"],
                    position=POSITION_MAP.get(sel["position"], sel["position"]),
                )
                st.session_state[ai_coach_key] = report
                st.session_state[ai_coach_sources_key] = sources
    else:
        render_ai_coach_report(st.session_state[ai_coach_key])
        sources = st.session_state.get(ai_coach_sources_key, [])
        if sources:
            st.caption("Sources: " + " · ".join(sorted(set(sources))[:4]))

    render_section_header("COACH CHAT")
    _chat_key = f"coach_chat_{sel['match_id']}"
    st.session_state.setdefault(_chat_key, [])

    for msg in st.session_state[_chat_key][-6:]:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    free_question = st.chat_input(
        "ASK A FOLLOW-UP ABOUT THIS MATCH",
        key=f"coach_chat_input_{sel['match_id']}",
    )
    if free_question:
        st.session_state[_chat_key].append({"role": "user", "content": free_question})
        chat_prompt = (
            "Answer this player's follow-up about the reviewed League of Legends match. "
            "Give a coach read, match evidence, and one tactical adjustment for this game state.\n\n"
            f"Question: {free_question}"
        )
        with st.spinner("Coach is thinking..."):
            chain = _get_chat_chain()
            answer = chain.predict(input=chat_prompt) if chain else "AI coach not available."
        st.session_state[_chat_key].append({"role": "assistant", "content": _clean_llm_md(answer)})
        st.rerun()

    st.divider()

with right_col:
    # ── Training Goals / Strengths ───────────────────────────────────────────────
    if _training_gaps:
        render_section_header("TRAINING GOALS")
        _why_map = {
            "vision":        "Vision → objective control: low score = free dragons for enemies.",
            "kp":            "Kill participation determines your gold and XP advantage.",
            "deaths":        "Each death costs ~300g gold and 20+ seconds of tempo.",
            "cs_per_min":    "1 CS/min gap = ~300g lost per 20 minutes.",
            "cs_diff_10":    "CS leads at 10 min compound into item timing advantages.",
            "deaths_pre_15": "Early deaths give lane opponent a lead that shapes mid game.",
            "first_item_min": "First item faster → power spike while enemies are still weak.",
            "damage_share":  "Low damage share = you're not creating fight threats.",
            "roam_count":    "Roams convert lane advantage into map-wide pressure.",
        }
        for idx, gap in enumerate(_training_gaps):
            _why = _why_map.get(gap["key"], "Improving this metric improves your win rate.")
            _gap_color = RED_COLOR if gap["score"] < 0.5 else GOLD_COLOR
            _delta_str = f"{gap['delta']:+.1f}"
            st.markdown(
                f"<div style='background:#0A1428;border-left:3px solid {_gap_color};"
                f"border-radius:0 4px 4px 0;padding:12px 14px;margin-bottom:8px;'>"
                f"<div style='font-size:12px;font-weight:600;color:#F0E6D3;'>#{idx+1} {gap['label']}</div>"
                f"<div style='font-size:11px;color:{_gap_color};'>{_delta_str} vs avg {gap['target']:.1f}</div>"
                f"<div style='font-size:11px;color:#A0A0A0;margin-top:3px;line-height:1.3;'>{_why}</div>"
                f"</div>",
                unsafe_allow_html=True,
            )
    elif not _below_avg_gaps:
        render_section_header("STRENGTHS TO MAINTAIN")
        _above_metrics = [
            r for r in _score_rows
            if r.get("reliable", True)
            if (r["lower"] and r["delta"] <= 0) or (not r["lower"] and r["delta"] >= 0)
        ]
        for r in _above_metrics[:4]:
            _delta_str = f"{r['delta']:+.1f}"
            st.markdown(
                f"<div style='background:#0A1428;border-left:3px solid {GREEN_COLOR};"
                f"border-radius:0 4px 4px 0;padding:12px 14px;margin-bottom:8px;'>"
                f"<div style='font-size:12px;font-weight:600;color:#F0E6D3;'>{r['label']}</div>"
                f"<div style='font-size:11px;color:{GREEN_COLOR};'>{r['actual']:.1f} ({_delta_str} vs avg {r['target']:.1f}) ✓</div>"
                f"</div>",
                unsafe_allow_html=True,
            )
    st.divider()

    # ── Growth Tracker — last 5 games ───────────────────────────────────────────
    if len(parsed) >= 3:
        _main_pos = max(
            set(m["position"] for m in parsed if m["position"] != "UNKNOWN"),
            key=lambda p: sum(1 for m in parsed if m["position"] == p),
            default="MIDDLE",
        )
        _main_champ = max(
            set(m["champion"] for m in parsed),
            key=lambda c: sum(1 for m in parsed if m["champion"] == c),
            default="",
        )
        _pt_avg, _ = get_position_benchmark(challenger_matches, _main_champ, _main_pos)
        tracker = get_recurring_issues(parsed, _pt_avg, n=5)

        if tracker:
            trend_icon  = "Improving" if tracker["improving"] else "Not improving yet"
            trend_color = GREEN_COLOR if tracker["improving"] else GOLD_COLOR
            bar_filled  = tracker["games_affected"]
            bar_total   = tracker["out_of"]
            _EMPTY_BAR  = "#1E2D40"
            bar_html = "".join(
                "<span style='display:inline-block;width:12px;height:12px;border-radius:3px;"
                f"background:{RED_COLOR if i < bar_filled else _EMPTY_BAR};margin-right:2px;'></span>"
                for i in range(bar_total)
            )
            top_label = tracker["issue"]
            others = [(lbl, cnt) for lbl, cnt in tracker["all_issues"].items()
                      if lbl != top_label and cnt > 0]
            others_html = ""
            if others:
                others_html = (
                    "<div style='margin-top:6px;font-size:10px;color:#A0A0A0;'>"
                    "Also: " + ", ".join(f"{lbl} ({cnt}/{bar_total})" for lbl, cnt in others)
                    + "</div>"
                )
            render_section_header("GROWTH TRACKER — LAST " + str(bar_total) + " GAMES")
            st.markdown(
                f"<div style='background:#0A1428;border:1px solid #1E2D4088;border-radius:4px;padding:14px 16px;'>"
                f"<div style='font-size:12px;color:#F0E6D3;font-weight:600;'>Recurring: {top_label}</div>"
                f"<div style='margin-top:6px;'>{bar_html}</div>"
                f"<div style='font-size:10px;color:#A0A0A0;margin-top:3px;'>{bar_filled}/{bar_total} games</div>"
                f"{others_html}"
                f"<div style='margin-top:10px;border-top:1px solid #1E2D40;padding-top:8px;'>"
                f"<div style='font-size:10px;color:#A0A0A0;'>Training focus</div>"
                f"<div style='font-size:11px;color:#F0E6D3;margin-top:3px;line-height:1.4;'>{tracker['focus']}</div>"
                f"<div style='margin-top:6px;font-size:11px;color:{trend_color};font-weight:600;'>{trend_icon}</div>"
                f"</div></div>",
                unsafe_allow_html=True,
            )
