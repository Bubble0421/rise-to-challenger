import pandas as pd
import plotly.graph_objects as go
import requests
import streamlit as st

from api import PATCH, DATA_PATCH_LABEL, champion_icon_url
from utils.data import RANK_OPTIONS, load_rank_matches
from utils.styles import GOLD, TEXT_MUTED, TEXT_COLOR, GRID_COLOR, WIN_COLOR, LOSS_COLOR, chart_layout, inject_css, render_sidebar, render_page_header, render_section_header
from services.confidence_service import get_confidence_label, get_confidence_color, get_confidence_dot

st.set_page_config(page_title="Rise to Challenger", page_icon="⚔", layout="wide", initial_sidebar_state="expanded")
inject_css()

POSITION_MAP = {"TOP": "Top", "JUNGLE": "Jungle", "MIDDLE": "Mid", "BOTTOM": "Bot", "UTILITY": "Support"}
ROLE_TO_POS  = {"All Roles": "All", "Top": "TOP", "Jungle": "JUNGLE", "Mid": "MIDDLE", "Bot": "BOTTOM", "Support": "UTILITY"}
TIER_COLORS  = {"OP": "#E84057", "S": "#C8AA6E", "A": "#1D9E75", "B": "#785A28", "C": "#A0A0A0", "D": "#1E2D40"}
TIER_ORDER   = {"OP": -1, "S": 0, "A": 1, "B": 2, "C": 3, "D": 4}
_WR_TIERS    = [(54, "S"), (52, "A"), (50, "B"), (48, "C")]
_TIER_SEQ    = ["D", "C", "B", "A", "S"]
CHAMP_TYPES  = ["Fighter", "Mage", "Assassin", "Marksman", "Support", "Tank"]


# ── Data loaders ──────────────────────────────────────────────────────────────

@st.cache_data
def load_meta(rank_label: str):
    matches = load_rank_matches(rank_label)
    match_count = len(matches)
    rows = []
    for match in matches:
        dur = match.get("info", {}).get("gameDuration", 0) / 60
        team_damage: dict[int, int] = {}
        participants = match.get("info", {}).get("participants", [])
        for p in participants:
            tid = p["teamId"]
            team_damage[tid] = team_damage.get(tid, 0) + p["totalDamageDealtToChampions"]
        for p in participants:
            pos = p.get("teamPosition", "")
            if not pos or pos == "UNKNOWN":
                continue
            td = team_damage.get(p["teamId"], 1)
            rows.append({
                "champion":     p["championName"],
                "position":     pos,
                "win":          int(p["win"]),
                "kills":        p["kills"],
                "deaths":       p["deaths"],
                "assists":      p["assists"],
                "damage":       p["totalDamageDealtToChampions"],
                "damage_share": p["totalDamageDealtToChampions"] / max(td, 1),
                "vision":       p["visionScore"],
                "cs":           p["totalMinionsKilled"] + p.get("neutralMinionsKilled", 0),
                "duration":     round(dur, 1),
            })
    return pd.DataFrame(rows), match_count


@st.cache_data
def get_champion_types() -> dict:
    url = f"https://ddragon.leagueoflegends.com/cdn/{PATCH}/data/en_US/champion.json"
    try:
        data = requests.get(url, timeout=8).json()
        return {info["id"]: info["tags"][0] if info["tags"] else "Fighter"
                for info in data["data"].values()}
    except Exception:
        return {}


def _wr_base_tier(wr: float) -> str:
    for threshold, tier in _WR_TIERS:
        if wr >= threshold:
            return tier
    return "D"


def compute_tiers(champ_df: pd.DataFrame) -> pd.DataFrame:
    if champ_df.empty:
        return champ_df

    def assign_tier(row) -> str:
        wr, games = row["win_rate"], row["games"]
        if wr >= 56 and games >= 50:
            return "OP"
        base = _wr_base_tier(wr)
        idx  = _TIER_SEQ.index(base)
        if games < 30:
            idx = max(0, idx - 1)
        elif games >= 100:
            idx = min(_TIER_SEQ.index(base), idx + 1)
        return _TIER_SEQ[idx]

    champ_df["sample_confidence"] = (champ_df["games"] / 50).clip(upper=1.0)
    champ_df["tier"]              = champ_df.apply(assign_tier, axis=1)
    champ_df["tier_rank"]         = champ_df["tier"].map(TIER_ORDER)
    return champ_df.sort_values(["tier_rank", "win_rate"], ascending=[True, False]).reset_index(drop=True)


def compute_tab_scores(df: pd.DataFrame) -> pd.DataFrame:
    """Add blind/carry/hidden/overhyped scores."""
    if df.empty:
        return df
    max_games = max(df["games"].max(), 1)
    max_pr    = max(df["play_rate"].max(), 0.01)

    df["blind_score"]  = (
        (df["win_rate"] / 100) * 0.5
        + df["sample_confidence"] * 0.3
        + (df["games"] / max_games) * 0.2
    )
    df["carry_score"]  = (
        df["avg_damage_share"] * 0.3
        + (df["win_rate"] / 100) * 0.4
        + (df["kda"] / max(df["kda"].max(), 1)) * 0.3
    )
    df["hidden_score"] = (
        (df["win_rate"] / 100) * 0.6
        + (1 - df["play_rate"] / max_pr) * 0.4
    )
    return df


# ── Sidebar ────────────────────────────────────────────────────────────────────

render_sidebar()

# ── Filters ────────────────────────────────────────────────────────────────────

render_page_header("META ANALYSIS", f"Offline Master+ NA data · Patches {DATA_PATCH_LABEL}")

if not RANK_OPTIONS:
    st.warning("Offline ranked datasets are not available in this environment.")
    st.info(
        "To use Meta Analysis, collect local data first with `python scripts/collect_data.py`, "
        "then reload the app."
    )
    st.stop()

rank_col, role_col = st.columns(2)
with rank_col:
    selected_rank = st.selectbox("Rank", RANK_OPTIONS, index=0)
with role_col:
    selected_role = st.selectbox("Role", list(ROLE_TO_POS.keys()), index=0)

sel_pos = ROLE_TO_POS[selected_role]
df, match_count = load_meta(selected_rank)

if df.empty:
    st.info("No data available for this rank yet.")
    st.stop()

# ── Aggregation ────────────────────────────────────────────────────────────────

champ = (
    df.groupby(["champion", "position"])
    .agg(
        games           = ("win", "count"),
        wins            = ("win", "sum"),
        avg_kills       = ("kills", "mean"),
        avg_deaths      = ("deaths", "mean"),
        avg_assists     = ("assists", "mean"),
        avg_damage      = ("damage", "mean"),
        avg_damage_share= ("damage_share", "mean"),
        avg_vision      = ("vision", "mean"),
        avg_cs          = ("cs", "mean"),
    )
    .reset_index()
)
champ["win_rate"]  = (champ["wins"] / champ["games"] * 100).round(1)
champ["kda"]       = ((champ["avg_kills"] + champ["avg_assists"]) / champ["avg_deaths"].clip(lower=1)).round(2)
champ["play_rate"] = (champ["games"] / max(len(df) / 10, 1) * 100).round(2)   # per-match basis

champ_filtered = champ if sel_pos == "All" else champ[champ["position"] == sel_pos]
qualified      = compute_tiers(champ_filtered.copy())
qualified      = compute_tab_scores(qualified)

# ── KPI pool ──────────────────────────────────────────────────────────────────

best_pool    = qualified[(qualified["win_rate"] > 52) & (qualified["games"] >= 60)]
best_carry   = best_pool.sort_values("blind_score", ascending=False).iloc[0]   if len(best_pool)   else None
carry_pool   = qualified[(qualified["games"] >= 30)]
high_carry   = carry_pool.sort_values("carry_score", ascending=False).iloc[0]  if len(carry_pool)  else None
hidden_pool  = qualified[(qualified["win_rate"] > 54) & (qualified["games"] >= 20) &
                         (qualified["play_rate"] <= qualified["play_rate"].median())]
hidden_op    = hidden_pool.sort_values("hidden_score", ascending=False).iloc[0] if len(hidden_pool) else None
avoid_pool   = qualified[(qualified["play_rate"] >= qualified["play_rate"].quantile(0.8)) &
                         (qualified["win_rate"] < 49) & (qualified["games"] >= 30)]
avoid_pick   = avoid_pool.sort_values("play_rate", ascending=False).iloc[0]    if len(avoid_pool)  else None

# ── Meta Summary Banner ────────────────────────────────────────────────────────

role_label = selected_role if selected_role != "All Roles" else "All Roles"
rank_label = selected_rank

banner_lines = []
if best_carry is not None:
    bc_conf = get_confidence_label(int(best_carry["games"]))
    banner_lines.append(
        f"**Best blind pick:** {best_carry['champion']} ({best_carry['win_rate']:.1f}% WR · {bc_conf})"
    )
if high_carry is not None:
    banner_lines.append(
        f"**Highest carry upside:** {high_carry['champion']} ({high_carry['win_rate']:.1f}% WR · "
        f"{high_carry['avg_damage_share']*100:.1f}% dmg share)"
    )
if avoid_pick is not None:
    banner_lines.append(
        f"**Avoid:** {avoid_pick['champion']} (high play rate, only {avoid_pick['win_rate']:.1f}% WR)"
    )

if banner_lines:
    st.info(
        f"**{rank_label} · {role_label} — This Patch:**\n" + "\n".join(f"• {l}" for l in banner_lines)
    )

st.markdown(
    f"<span style='color:{TEXT_MUTED};font-size:12px;'>"
    f"Showing {match_count:,} matches · {selected_rank} · {selected_role} · Patches {DATA_PATCH_LABEL}"
    f"</span>",
    unsafe_allow_html=True,
)
st.divider()

# ── KPI Cards ─────────────────────────────────────────────────────────────────

c1, c2, c3, c4 = st.columns(4)

with c1:
    if best_carry is not None:
        conf = get_confidence_label(int(best_carry["games"]))
        st.metric(
            "Best Blind Pick",
            best_carry["champion"],
            delta=f"{best_carry['win_rate']:.1f}% WR · {int(best_carry['games'])} games",
            delta_color="off",
            help="Composite score = 0.5 × win rate + 0.3 × sample confidence + 0.2 × game count. Min 60 games.",
        )
        st.caption(f"{get_confidence_dot(conf)} {conf}")
    else:
        st.metric("Best Blind Pick", "—", help="Requires 60+ games and WR > 52%")

with c2:
    if high_carry is not None:
        conf = get_confidence_label(int(high_carry["games"]))
        st.metric(
            "Highest Carry Upside",
            high_carry["champion"],
            delta=f"{high_carry['win_rate']:.1f}% WR · {high_carry['avg_damage_share']*100:.1f}% dmg share",
            delta_color="off",
            help="Carry score = 0.4 × win rate + 0.3 × damage share + 0.3 × KDA. Measures snowball potential.",
        )
        st.caption(f"{get_confidence_dot(conf)} {conf}")
    else:
        st.metric("Highest Carry Upside", "—")

with c3:
    if hidden_op is not None:
        conf = get_confidence_label(int(hidden_op["games"]))
        st.metric(
            "Hidden OP",
            hidden_op["champion"],
            delta=f"{hidden_op['win_rate']:.1f}% WR · {hidden_op['play_rate']:.1f}% pick rate",
            delta_color="off",
            help="Win rate > 54%, play rate below role median. Min 20 games. Enemy won't expect it.",
        )
        st.caption(f"{get_confidence_dot(conf)} {conf}")
    else:
        st.metric("Hidden OP", "—", help="Win rate > 54% + play rate < median. Min 20 games.")

with c4:
    if avoid_pick is not None:
        conf = get_confidence_label(int(avoid_pick["games"]))
        st.metric(
            "Most Contested / Avoid",
            avoid_pick["champion"],
            delta=f"{avoid_pick['win_rate']:.1f}% WR · {avoid_pick['play_rate']:.1f}% pick rate",
            delta_color="inverse",
            help="High play rate (top 20%) but win rate below 49%. Overhyped — people pick it but it underperforms.",
        )
        st.caption(f"{get_confidence_dot(conf)} {conf}")
    else:
        st.metric("Most Contested / Avoid", "—", help="High pick rate + below 49% WR.")

st.divider()

# ── Quick Pick Cards — top 3 per position ────────────────────────────────────

render_section_header("QUICK PICK")
st.caption("Top 3 champions per role by blind pick score. Min 20 games.")

_QP_POSITIONS = ["TOP", "JUNGLE", "MIDDLE", "BOTTOM", "UTILITY"]
_qp_cols = st.columns(5)

for _qp_col, _pos in zip(_qp_cols, _QP_POSITIONS):
    _pool = qualified[qualified["position"] == _pos].sort_values("blind_score", ascending=False).head(3)
    with _qp_col:
        st.markdown(
            f"<div style='font-size:11px;color:#A0A0A0;text-transform:uppercase;"
            f"letter-spacing:.07em;margin-bottom:8px;'>{POSITION_MAP.get(_pos, _pos)}</div>",
            unsafe_allow_html=True,
        )
        for _rank, (_, _row) in enumerate(_pool.iterrows(), 1):
            _tier    = _row.get("tier", "B")
            _tier_bg = TIER_COLORS.get(_tier, "#785A28")
            _txt_col = "#FFFFFF" if _tier in ("OP", "D") else "#010A13"
            _wr_col  = WIN_COLOR if _row["win_rate"] > 52 else (LOSS_COLOR if _row["win_rate"] < 48 else TEXT_COLOR)
            st.markdown(
                f"<div style='background:#0A1428;border-radius:4px;padding:8px 10px;margin-bottom:6px;"
                f"display:flex;align-items:center;gap:8px;'>"
                f"<img src='{champion_icon_url(_row['champion'])}' width='28' height='28' "
                f"style='border-radius:4px;flex-shrink:0;'>"
                f"<div>"
                f"<div style='font-size:12px;font-weight:600;color:#F0E6D3;'>{_row['champion']}</div>"
                f"<div style='font-size:11px;'>"
                f"<span style='background:{_tier_bg};color:{_txt_col};padding:1px 5px;"
                f"border-radius:2px;font-weight:700;font-size:10px;'>{_tier}</span> "
                f"<span style='color:{_wr_col};'>{_row['win_rate']:.1f}%</span>"
                f"</div></div></div>",
                unsafe_allow_html=True,
            )

st.divider()

# ── Tier List — 4-Tab View ────────────────────────────────────────────────────

render_section_header("CHAMPION TIER LIST")

def _tier_row_html(row, show_tier: bool = True) -> None:
    tier     = row.get("tier", "B")
    tier_bg  = TIER_COLORS.get(tier, "#785A28")
    glow     = "box-shadow:0 0 6px #FF465588;" if tier == "OP" else ""
    txt_col  = "#FFFFFF" if tier in ("OP", "D") else "#010A13"
    wr       = row["win_rate"]
    wr_color = WIN_COLOR if wr > 52 else (LOSS_COLOR if wr < 48 else TEXT_COLOR)
    games    = int(row["games"])
    conf_lbl = get_confidence_label(games)
    conf_col = get_confidence_color(conf_lbl)
    conf_dot = get_confidence_dot(conf_lbl)

    cols = st.columns([0.5, 1.0, 2.1, 1.2, 1, 1.2, 1, 1.1, 1.1, 2.2])
    with cols[0]:
        st.image(champion_icon_url(row["champion"]), width=32)
    with cols[1]:
        if show_tier:
            st.markdown(
                f"<span style='background:{tier_bg};color:{txt_col};"
                f"padding:1px 7px;border-radius:3px;font-weight:bold;font-size:12px;{glow}'>{tier}</span>",
                unsafe_allow_html=True,
            )
    with cols[2]:
        st.markdown(f"**{row['champion']}**")
    with cols[3]:
        st.markdown(POSITION_MAP.get(row["position"], row["position"]))
    with cols[4]:
        st.markdown(str(games))
    with cols[5]:
        st.markdown(
            f"<span style='color:{wr_color};font-weight:600'>{wr:.1f}%</span>",
            unsafe_allow_html=True,
        )
    with cols[6]:
        st.markdown(f"{row['play_rate']:.1f}%")
    with cols[7]:
        st.markdown(f"{row['kda']:.2f}")
    with cols[8]:
        st.markdown(f"{row['avg_damage_share']*100:.1f}%")
    with cols[9]:
        st.markdown(
            f"<span style='color:{conf_col};font-size:11px;'>{conf_dot} {conf_lbl}</span>",
            unsafe_allow_html=True,
        )


def _tab_header():
    h = st.columns([0.5, 1.0, 2.1, 1.2, 1, 1.2, 1, 1.1, 1.1, 2.2])
    for col, label in zip(h, ["", "Tier", "Champion", "Role", "Games", "Win Rate", "Pick%", "KDA", "Dmg%", "Confidence"]):
        col.markdown(
            f"<span style='color:{TEXT_MUTED};font-size:11px;text-transform:uppercase;letter-spacing:.07em'>{label}</span>",
            unsafe_allow_html=True,
        )

display_positions = [sel_pos] if sel_pos != "All" else list(POSITION_MAP.keys())


def _render_tab(pool: pd.DataFrame, n: int = 10, show_tier: bool = True):
    display_positions_local = [sel_pos] if sel_pos != "All" else list(POSITION_MAP.keys())
    for pos in display_positions_local:
        if sel_pos == "All":
            pos_data = pool[pool["position"] == pos]
        else:
            pos_data = pool
        if pos_data.empty:
            continue
        if sel_pos == "All":
            st.markdown(f"#### {POSITION_MAP.get(pos, pos)}")
        sub = pos_data.head(n)
        _tab_header()
        for _, row in sub.iterrows():
            _tier_row_html(row, show_tier=show_tier)
        st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)


champ_search = st.text_input("Search Champion", placeholder="e.g. Jinx, Yasuo, Lux...", key="champ_search_meta")
if champ_search:
    _search_results = qualified[qualified["champion"].str.contains(champ_search, case=False, na=False)]
    if _search_results.empty:
        st.info(f"No results for '{champ_search}' in {selected_rank} · {selected_role}.")
    else:
        st.markdown(f"**Search results for '{champ_search}' by role:**")
        _tab_header()
        for _, _sr in _search_results.sort_values(["champion", "position"]).iterrows():
            _tier_row_html(_sr)
    st.divider()

tab_blind, tab_carry, tab_hidden, tab_avoid, tab_all = st.tabs([
    "Blind Pick Safe",
    "High Carry",
    "Hidden OP",
    "Avoid / Overhyped",
    "All Champions",
])


with tab_blind:
    st.caption("Champions with highest composite score (win rate × confidence × sample size). Safe into unknown matchups.")
    pool = qualified[qualified["games"] >= 20].sort_values("blind_score", ascending=False)
    _render_tab(pool, n=10)

with tab_carry:
    st.caption("Champions that produce the most damage and kills when ahead. High upside, higher variance.")
    pool = qualified[qualified["games"] >= 20].sort_values("carry_score", ascending=False)
    _render_tab(pool, n=10)

with tab_hidden:
    st.caption("Win rate > 54% but play rate below median — enemy won't counterpick. Min 20 games.")
    pool = qualified[
        (qualified["win_rate"] > 54) &
        (qualified["play_rate"] <= qualified["play_rate"].median()) &
        (qualified["games"] >= 20)
    ].sort_values("hidden_score", ascending=False)
    _render_tab(pool, n=10)

with tab_avoid:
    st.caption("High pick rate but sub-49% win rate. Overhyped this patch — avoid in ranked.")
    pool = qualified[
        (qualified["play_rate"] >= qualified["play_rate"].quantile(0.75)) &
        (qualified["win_rate"] < 49) &
        (qualified["games"] >= 30)
    ].sort_values("win_rate")
    _render_tab(pool, n=10, show_tier=False)

with tab_all:
    st.caption("Full champion list sorted by tier and win rate.")
    for pos in display_positions:
        pos_data = qualified if sel_pos != "All" else qualified[qualified["position"] == pos]
        if pos_data.empty:
            continue
        if sel_pos == "All":
            st.markdown(f"#### {POSITION_MAP.get(pos, pos)}")
        _tab_header()
        for _, row in pos_data.iterrows():
            _tier_row_html(row)
        st.markdown("<div style='height:12px'></div>", unsafe_allow_html=True)

st.divider()

# ── Secondary Analysis — collapsible ─────────────────────────────────────────

with st.expander("Meta Breakdown — Champion Types & Game Length", expanded=False):
    champ_types = get_champion_types()

    # Win Condition by Champion Type
    render_section_header("WIN CONDITION BY CHAMPION TYPE")
    if champ_types:
        df_typed = df.copy()
        df_typed["type"] = df_typed["champion"].map(champ_types)
        df_typed = df_typed[df_typed["type"].isin(CHAMP_TYPES)]
        type_stats = (
            df_typed.assign(kda=lambda d: (d["kills"] + d["assists"]) / d["deaths"].clip(lower=1))
            .groupby("type")
            .agg(games=("win", "count"), win_rate=("win", lambda s: round(s.mean() * 100, 1)), avg_kda=("kda", "mean"))
            .reset_index().sort_values("win_rate", ascending=True)
        )
        bar_colors = [GOLD if wr > 52 else "#1E2D40" for wr in type_stats["win_rate"]]
        fig_type = go.Figure(go.Bar(
            x=type_stats["win_rate"], y=type_stats["type"], orientation="h",
            marker_color=bar_colors,
            text=[f"{wr:.1f}%  ({int(g)} games)" for wr, g in zip(type_stats["win_rate"], type_stats["games"])],
            textposition="outside", textfont=dict(color=TEXT_COLOR),
        ))
        fig_type.add_vline(x=50, line_dash="dash", line_color=GRID_COLOR, opacity=0.7)
        fig_type.update_layout(**chart_layout(
            height=300, xaxis=dict(title="Win Rate (%)"), yaxis=dict(title=""), showlegend=False,
        ))
        st.plotly_chart(fig_type, use_container_width=True)
        top_row    = type_stats.sort_values("win_rate", ascending=False).iloc[0]
        bottom_row = type_stats.sort_values("win_rate").iloc[0]
        diff = round(top_row["win_rate"] - bottom_row["win_rate"], 1)
        meta_style = "teamfight" if top_row["type"] in ["Tank", "Fighter"] else "poke/pick"
        st.info(
            f"This patch favors **{top_row['type']}** ({top_row['win_rate']:.1f}% WR) over "
            f"**{bottom_row['type']}** ({bottom_row['win_rate']:.1f}% WR) — {diff:.1f}% gap → **{meta_style}** meta."
        )

    st.divider()

    # Early vs Late
    render_section_header("EARLY VS LATE GAME STRENGTH")
    df_time = df.copy()
    df_time["type"] = df_time["champion"].map(champ_types) if champ_types else "Unknown"

    def bucket(d):
        if d < 25:  return "Early (<25m)"
        if d <= 35: return "Mid (25–35m)"
        return "Late (>35m)"

    df_time["bucket"] = df_time["duration"].apply(bucket)
    bucket_order = ["Early (<25m)", "Mid (25–35m)", "Late (>35m)"]
    bucket_counts = df_time.groupby("bucket")["win"].count().reindex(bucket_order, fill_value=0)
    early_c = int(bucket_counts.get("Early (<25m)", 0)) // 10
    mid_c   = int(bucket_counts.get("Mid (25–35m)", 0)) // 10
    late_c  = int(bucket_counts.get("Late (>35m)", 0)) // 10

    fig_dist = go.Figure(go.Bar(
        x=bucket_order, y=[early_c, mid_c, late_c],
        marker_color=[WIN_COLOR, GOLD, "#785A28"],
        text=[f"{v:,} games" for v in [early_c, mid_c, late_c]],
        textposition="outside", textfont=dict(color=TEXT_COLOR),
    ))
    fig_dist.update_layout(**chart_layout(height=260, xaxis=dict(title=""), yaxis=dict(title="Match Count"), showlegend=False))
    st.plotly_chart(fig_dist, use_container_width=True)

    if early_c > late_c * 1.5:
        st.info("Snowball patch — early champions dominate. Push first objective windows.")
    elif late_c > early_c:
        st.info("Scaling patch — late game picks thrive. Don't force early fights.")
    else:
        st.info("Balanced patch — both styles viable.")
