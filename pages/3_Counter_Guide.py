import streamlit as st
from collections import Counter
import plotly.graph_objects as go
import pandas as pd
import requests

from api import PATCH, DATA_PATCH_LABEL, champion_icon_url, item_icon_url, get_item_names
from services.confidence_service import get_confidence_label, get_confidence_color
from services.counter_plan_service import LOW_VALUE_ITEM_NAMES, build_counter_plan
from utils.agents import run_counter_agents
from utils.data import load_rank_matches
from utils.styles import inject_css, chart_layout, GOLD, WIN_COLOR, LOSS_COLOR, render_sidebar, render_page_header, render_section_header

st.set_page_config(page_title="Rise to Challenger", page_icon="⚔", layout="wide", initial_sidebar_state="expanded")
inject_css()

POSITION_MAP = {
    "TOP": "Top", "JUNGLE": "Jungle", "MIDDLE": "Mid",
    "BOTTOM": "Bot", "UTILITY": "Support",
}
POS_OPTIONS = list(POSITION_MAP.keys())


# ─── Data ─────────────────────────────────────────────────────────────────────

@st.cache_data
def load_matches():
    return load_rank_matches("Master+")


@st.cache_data
def get_champion_list():
    url = f"https://ddragon.leagueoflegends.com/cdn/{PATCH}/data/en_US/champion.json"
    try:
        data = requests.get(url, timeout=6).json()["data"]
        return sorted(data.keys())
    except Exception:
        matches = load_matches()
        champs = set()
        for match in matches:
            for p in match["info"]["participants"]:
                if p.get("teamPosition"):
                    champs.add(p["championName"])
        return sorted(champs)


_ITEM_REASON_TAGS = {
    "Morellonomicon":        "vs healing",
    "Void Staff":            "armor pen",
    "Zhonya's Hourglass":    "vs burst",
    "Banshee's Veil":        "vs CC",
    "Rabadon's Deathcap":    "max damage",
    "Shadowflame":           "burst damage",
    "Luden's Tempest":       "poke + roam",
    "Luden's Companion":     "poke + roam",
    "Infinity Edge":         "crit scaling",
    "Kraken Slayer":         "vs tanks",
    "Galeforce":             "mobility",
    "Runaan's Hurricane":    "AoE DPS",
    "Nashor's Tooth":        "attack speed",
    "Trinity Force":         "split push",
    "Black Cleaver":         "armor shred",
    "Death's Dance":         "survivability",
    "Sterak's Gage":         "burst survival",
    "Guardian Angel":        "second life",
    "Warmog's Armor":        "HP regen",
    "Thornmail":             "anti-heal + armor",
    "Frozen Heart":          "attack speed slow",
    "Sunfire Aegis":         "sustained dmg",
    "Serpent's Fang":        "vs shields",
    "Stormsurge":            "burst AP",
    "Hextech Rocketbelt":    "gap close",
    "Lich Bane":             "burst + wave",
    "Seraph's Embrace":      "mana + shield",
    "Archangel's Staff":     "mana scaling",
    "Rod of Ages":           "scaling stat stick",
    "Night Harvester":       "burst mobility",
    "Cosmic Drive":          "CDR + speed",
    "Demonic Embrace":       "burn damage",
    "Liandry's Torment":     "burn damage",
    "Liandry's Anguish":     "burn damage",
}

def get_item_reason(item_name: str) -> str:
    return _ITEM_REASON_TAGS.get(item_name, "")


def get_matchup_stats(attacker, attacker_pos, defender, defender_pos, matches):
    results = []
    for match in matches:
        participants = match["info"]["participants"]
        attacker_p = next(
            (p for p in participants
             if p["championName"] == attacker and p.get("teamPosition") == attacker_pos),
            None,
        )
        if not attacker_p:
            continue
        defender_p = next(
            (p for p in participants
             if p["championName"] == defender
             and p.get("teamPosition") == defender_pos
             and p["teamId"] != attacker_p["teamId"]),
            None,
        )
        if not defender_p:
            continue
        results.append({
            "win":     attacker_p["win"],
            "kills":   attacker_p["kills"],
            "deaths":  attacker_p["deaths"],
            "assists": attacker_p["assists"],
            "damage":  attacker_p["totalDamageDealtToChampions"],
            "cs":      attacker_p["totalMinionsKilled"] + attacker_p.get("neutralMinionsKilled", 0),
            "vision":  attacker_p["visionScore"],
            "items":   [attacker_p.get(f"item{i}", 0) for i in range(6)],
        })
    return results


# ─── Sidebar ──────────────────────────────────────────────────────────────────

render_sidebar()

all_champions = get_champion_list()
offline_matches = load_matches()

if not offline_matches or not all_champions:
    render_page_header("COUNTER GUIDE", "Master+ matchup data · 30-second pre-game guide")
    st.warning("Offline matchup datasets are not available in this environment.")
    st.info(
        "To use Counter Guide fully, collect local ranked data with `python scripts/collect_data.py`, "
        "then reload the app."
    )
    st.stop()

# ─── Page Header ──────────────────────────────────────────────────────────────

render_page_header("COUNTER GUIDE", "Master+ matchup data · 30-second pre-game guide")

# ─── Champion Selectors ───────────────────────────────────────────────────────

col1, col2, col3, col4 = st.columns([2, 1, 2, 1])
with col1:
    your_champ = st.selectbox("Your Champion", all_champions,
                              index=all_champions.index("Jinx") if "Jinx" in all_champions else 0)
with col2:
    your_pos = st.selectbox("Your Role", POS_OPTIONS, format_func=lambda x: POSITION_MAP[x], index=3)
with col3:
    enemy_champ = st.selectbox("Enemy Champion", all_champions,
                               index=all_champions.index("Caitlyn") if "Caitlyn" in all_champions else 1)
with col4:
    enemy_pos = st.selectbox("Enemy Role", POS_OPTIONS, format_func=lambda x: POSITION_MAP[x],
                             index=3, key="enemy_pos")

if your_champ == enemy_champ:
    st.warning("Please select two different champions.")
    st.stop()

# ─── Champion Icons ───────────────────────────────────────────────────────────

ic1, ic_vs, ic2 = st.columns([1, 0.3, 1])
with ic1:
    try:
        st.image(champion_icon_url(your_champ), width=72)
    except Exception:
        pass
    st.markdown(f"**{your_champ}** — {POSITION_MAP[your_pos]}")
with ic_vs:
    st.markdown("<div style='text-align:center;font-size:2rem;padding-top:12px'>VS</div>",
                unsafe_allow_html=True)
with ic2:
    try:
        st.image(champion_icon_url(enemy_champ), width=72)
    except Exception:
        pass
    st.markdown(f"**{enemy_champ}** — {POSITION_MAP[enemy_pos]}")

st.divider()

# ─── Query Matchup Data ───────────────────────────────────────────────────────

current_matchup_key = f"{your_champ}:{your_pos}:{enemy_champ}:{enemy_pos}"

with st.spinner("Loading high-elo matchup data..."):
    matches = offline_matches
    item_names = get_item_names()

results = get_matchup_stats(your_champ, your_pos, enemy_champ, enemy_pos, matches)
n = len(results)

if n == 0:
    st.info(
        f"No games found for {your_champ} ({POSITION_MAP[your_pos]}) vs "
        f"{enemy_champ} ({POSITION_MAP[enemy_pos]}). Try different roles."
    )
    st.stop()

# ─── Win Rate KPIs ────────────────────────────────────────────────────────────

wins        = sum(1 for r in results if r["win"])
wr          = round(wins / n * 100, 1)
avg_kills   = round(sum(r["kills"]   for r in results) / n, 1)
avg_deaths  = round(sum(r["deaths"]  for r in results) / n, 1)
avg_assists = round(sum(r["assists"] for r in results) / n, 1)
avg_kda     = round((avg_kills + avg_assists) / max(avg_deaths, 1), 2)
avg_damage  = round(sum(r["damage"]  for r in results) / n)
avg_cs      = round(sum(r["cs"]      for r in results) / n, 1)

conf_label      = get_confidence_label(n)
conf_color      = get_confidence_color(conf_label)
wr_delta_color  = "normal" if wr >= 52 else ("inverse" if wr < 48 else "off")

# Confidence-aware verdict text + color
def _verdict_text(win_rate: float, games: int) -> tuple[str, str]:
    """Return (display_text, color)."""
    low_sample = get_confidence_label(games) in ("Low Sample", "Insufficient Data")
    if win_rate > 55:
        direction, base_color = "STRONG EDGE", WIN_COLOR
    elif win_rate > 52:
        direction, base_color = "FAVORABLE", WIN_COLOR
    elif win_rate >= 48:
        direction, base_color = "EVEN", GOLD
    elif win_rate >= 45:
        direction, base_color = "UNFAVORABLE", LOSS_COLOR
    else:
        direction, base_color = "HARD COUNTER", LOSS_COLOR

    if low_sample:
        return f"LEANS {direction}", base_color
    elif games < 150:
        prefix = "SLIGHT EDGE —" if win_rate > 50 else "SLIGHT DISADVANTAGE —"
        return f"{prefix} {direction}", base_color
    else:
        return direction, base_color

verdict_text, verdict_color = _verdict_text(wr, n)
low_sample = conf_label in ("Low Sample", "Insufficient Data")

# Confidence + verdict summary banner
caveat_html = (
    f"<div style='font-size:11px;color:#A0A0A0;margin-top:4px;'>"
    f"Treat as directional guidance, not a definitive read.</div>"
    if low_sample else ""
)
st.markdown(
    f"<div style='background:#0A1428;border:1px solid {verdict_color}55;border-radius:4px;"
    f"padding:12px 18px;margin-bottom:12px;'>"
    f"<div style='display:flex;align-items:center;gap:16px;'>"
    f"<div style='font-size:22px;font-weight:700;color:{verdict_color};'>{verdict_text}</div>"
    f"<div style='color:#A0A0A0;font-size:13px;'>{your_champ} vs {enemy_champ} · {POSITION_MAP[your_pos]} lane</div>"
    f"<div style='margin-left:auto;'><span style='color:{conf_color};font-size:12px;'>● {conf_label} · {n} Master+ NA games · Patch {DATA_PATCH_LABEL}</span></div>"
    f"</div>{caveat_html}</div>",
    unsafe_allow_html=True,
)

k1, k2, k3, k4, k5 = st.columns(5)
k1.metric(f"{your_champ} Win Rate", f"{wr}%",   delta=verdict_text,             delta_color=wr_delta_color)
k2.metric("Matches Analyzed",       f"{n}")
k3.metric("Avg KDA",  f"{avg_kills}/{avg_deaths}/{avg_assists}", delta=f"ratio {avg_kda}", delta_color="off")
k4.metric("Avg Damage",             f"{avg_damage:,}")
k5.metric("Avg CS",                 avg_cs)

st.divider()

# Pre-compute top items (needed for both AI context and the data expander)
_item_counter = Counter(
    item_id
    for r in results if r["win"]
    for item_id in r["items"] if item_id != 0 and item_id in item_names
)
top_items = [item_id for item_id, _ in _item_counter.most_common(6)]

# ─── Full Matchup Data ────────────────────────────────────────────────────────

with st.expander("See Full Matchup Data", expanded=True):
    col_gauge, col_chart = st.columns([1, 2])

    with col_gauge:
        render_section_header("MATCHUP WIN RATE")
        gauge_color = WIN_COLOR if wr >= 52 else (LOSS_COLOR if wr < 48 else GOLD)
        fig_gauge = go.Figure(go.Indicator(
            mode="gauge+number",
            value=wr,
            number={"suffix": "%", "font": {"size": 36, "color": gauge_color}},
            gauge={
                "axis": {"range": [0, 100], "tickwidth": 1, "tickcolor": "#1E2D40", "tickfont": {"color": "#A0A0A0"}},
                "bar": {"color": gauge_color},
                "bgcolor": "#0A1428",
                "bordercolor": "#1E2D40",
                "steps": [
                    {"range": [0, 48],   "color": "rgba(226,75,74,0.08)"},
                    {"range": [48, 52],  "color": "rgba(200,170,110,0.08)"},
                    {"range": [52, 100], "color": "rgba(29,158,117,0.08)"},
                ],
                "threshold": {"line": {"color": "#1E2D40", "width": 2}, "thickness": 0.75, "value": 50},
            },
            title={"text": f"{your_champ} vs {enemy_champ}", "font": {"color": "#F0E6D3", "size": 13}},
        ))
        fig_gauge.update_layout(height=260, margin=dict(l=20, r=20, t=40, b=10),
                                paper_bgcolor="rgba(0,0,0,0)", font=dict(color="#F0E6D3"))
        st.plotly_chart(fig_gauge, use_container_width=True)

    with col_chart:
        render_section_header("WIN / LOSS BREAKDOWN")
        win_games  = [r for r in results if r["win"]]
        loss_games = [r for r in results if not r["win"]]
        fig_wl = go.Figure()
        fig_wl.add_trace(go.Bar(name="Wins",   x=["Outcome"], y=[len(win_games)],
                                marker_color=WIN_COLOR,  text=[len(win_games)],
                                textposition="inside", textfont=dict(color="#010A13", size=14)))
        fig_wl.add_trace(go.Bar(name="Losses", x=["Outcome"], y=[len(loss_games)],
                                marker_color=LOSS_COLOR, text=[len(loss_games)],
                                textposition="inside", textfont=dict(color="#010A13", size=14)))
        fig_wl.update_layout(**chart_layout(
            barmode="stack", height=260, showlegend=True,
            margin=dict(l=10, r=10, t=10, b=10),
            yaxis=dict(title="Games"),
        ))
        st.plotly_chart(fig_wl, use_container_width=True)

    render_section_header(f"MOST COMMON ITEMS IN WINS VS {enemy_champ}")
    if top_items:
        item_cols = st.columns(len(top_items))
        for idx, item_id in enumerate(top_items):
            with item_cols[idx]:
                try:
                    st.image(item_icon_url(item_id), width=56)
                except Exception:
                    pass
                name   = item_names.get(item_id, "")
                reason = get_item_reason(name)
                st.caption(name[:18] if name else str(item_id))
                if reason:
                    st.markdown(
                        f"<div style='font-size:10px;color:#C8AA6E;margin-top:-6px;'>{reason}</div>",
                        unsafe_allow_html=True,
                    )
    else:
        st.info("Not enough winning game data.")

    render_section_header("KDA DISTRIBUTION — WIN VS LOSS")
    df_results = pd.DataFrame(results)
    df_results["kda"]    = (df_results["kills"] + df_results["assists"]) / df_results["deaths"].clip(lower=1)
    df_results["result"] = df_results["win"].map({True: "Win", False: "Loss"})
    fig_scatter = go.Figure()
    for outcome, color in [("Win", WIN_COLOR), ("Loss", LOSS_COLOR)]:
        subset = df_results[df_results["result"] == outcome]
        fig_scatter.add_trace(go.Scatter(
            x=subset["damage"], y=subset["kda"],
            mode="markers", name=outcome,
            marker=dict(color=color, size=8, opacity=0.8),
            hovertemplate=f"<b>{outcome}</b><br>KDA: %{{y:.2f}}<br>Damage: %{{x:,}}<extra></extra>",
        ))
    fig_scatter.update_layout(**chart_layout(
        height=340,
        xaxis=dict(title="Damage Dealt"),
        yaxis=dict(title="KDA Ratio"),
        legend=dict(orientation="h", y=1.05),
    ))
    st.plotly_chart(fig_scatter, use_container_width=True)

st.divider()

# ─── Counter plan ─────────────────────────────────────────────────────────────

render_section_header("COUNTER PLAN")

top_item_names = [item_names.get(i, str(i)) for i in top_items]
decision_item_names = [name for name in top_item_names if name and name not in LOW_VALUE_ITEM_NAMES]
tip_key = f"counter_{your_champ}_{your_pos}_{enemy_champ}_{enemy_pos}"

matchup_context = (
    f"Matchup: {your_champ} ({POSITION_MAP[your_pos]}) vs {enemy_champ} ({POSITION_MAP[enemy_pos]})\n"
    f"Data source: {n} NA Master+ matches (Patches {DATA_PATCH_LABEL})\n"
    f"Win rate: {wr}% ({'Favorable' if wr >= 52 else 'Unfavorable' if wr < 48 else 'Even'})\n"
    f"Avg KDA: {avg_kills}/{avg_deaths}/{avg_assists} (ratio {avg_kda})\n"
    f"Avg damage: {avg_damage:,} · Avg CS: {avg_cs}\n"
    f"Best items in winning games: {', '.join(decision_item_names or top_item_names)}\n"
)

default_plan = build_counter_plan(
    your_champ=your_champ,
    your_pos=your_pos,
    enemy_champ=enemy_champ,
    matchup_data=matchup_context,
)

col_btn_agent, _ = st.columns([1, 2])
with col_btn_agent:
    run_agents_btn = st.button(
        "BUILD 30-SECOND PLAN", type="primary",
        key="agents_btn",
    )

# Multi-agent path clears previous result first to avoid duplication.
if run_agents_btn:
    st.session_state[tip_key]              = None
    st.session_state[f"{tip_key}_sources"] = []
    with st.status("Building counter plan...", expanded=True) as status_box:
        advice, sources = run_counter_agents(
            your_champ=your_champ,
            your_pos=your_pos,
            enemy_champ=enemy_champ,
            matchup_data=matchup_context,
            status_writer=status_box.write,
        )
        status_box.update(label="Counter plan ready", state="complete", expanded=False)

    st.session_state[tip_key]              = advice or default_plan
    st.session_state[f"{tip_key}_sources"] = sources

# Display cached result, shown only when tip_key has a non-None value.
cached_advice = st.session_state.get(tip_key) or default_plan
if cached_advice:
    with st.container(border=True):
        st.markdown(cached_advice)

    cached_sources = st.session_state.get(f"{tip_key}_sources", [])
    if cached_sources:
        st.markdown(
            "**Sources used:**\n" + "\n".join(f"• {s}" for s in set(cached_sources))
        )
