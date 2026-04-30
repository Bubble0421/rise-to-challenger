import streamlit as st

from utils.styles import inject_css, render_sidebar

st.set_page_config(
    page_title="Rise to Challenger",
    page_icon="⚔",
    layout="wide",
    initial_sidebar_state="expanded",
)

inject_css()
render_sidebar()

st.html("""
<div style="text-align:center; padding: 60px 0 48px 0;">

    <div style="color:#785A28; letter-spacing:8px; font-size:12px; margin-bottom:24px;">
        ⚔ ------------------- ⚔
    </div>

    <div style="font-size:52px; font-weight:800; color:#C8AA6E;
                letter-spacing:8px; text-transform:uppercase;
                line-height:1.1; margin-bottom:4px;">
        RISE TO
    </div>

    <div style="font-size:62px; font-weight:800; color:#C8AA6E;
                letter-spacing:10px; text-transform:uppercase;
                line-height:1.1; margin-bottom:24px;">
        CHALLENGER
    </div>

    <div style="font-size:12px; color:#A0A0A0; letter-spacing:4px;
                text-transform:uppercase; margin-bottom:6px;">
        MASTER THE META · CLIMB THE LADDER
    </div>

    <div style="font-size:11px; color:#5B5A56; letter-spacing:2px;">
        Master+ match data · Real-time Riot API · AI Coaching
    </div>

    <div style="color:#785A28; letter-spacing:8px; font-size:12px; margin-top:24px;">
        ⚔ ------------------- ⚔
    </div>
</div>
""")

st.divider()

col1, col2, col3 = st.columns(3)
cards = [
    ("01", "META ANALYSIS",
     "Champion tier list, hidden OP picks, and role strength from Master+ matches."),
    ("02", "PLAYER REVIEW",
     "Search any player, benchmark vs Challenger, and get AI coaching on any match."),
    ("03", "COUNTER GUIDE",
     "Matchup win rates from real data with AI counter advice in 30 seconds."),
]

for col, (num, title, desc) in zip([col1, col2, col3], cards):
    with col:
        st.html(f"""
        <div style="background:#0A1428; border:1px solid #1E2D40;
                    border-top:2px solid #C8AA6E; border-radius:2px;
                    padding:24px; height:160px;">
            <div style="font-size:10px; color:#785A28; letter-spacing:3px;
                        margin-bottom:10px;">{num}</div>
            <div style="font-size:13px; font-weight:700; color:#C8AA6E;
                        letter-spacing:2px; text-transform:uppercase;
                        margin-bottom:10px;">{title}</div>
            <div style="font-size:12px; color:#5B5A56; line-height:1.6;">
                {desc}</div>
        </div>
        """)

nav1, nav2, nav3 = st.columns(3)
with nav1:
    st.page_link("pages/1_Meta.py", label="OPEN META ANALYSIS")
with nav2:
    st.page_link("pages/2_Player_Review.py", label="OPEN PLAYER REVIEW")
with nav3:
    st.page_link("pages/3_Counter_Guide.py", label="OPEN COUNTER GUIDE")
