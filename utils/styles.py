import streamlit as st

GOLD = "#C8AA6E"
GOLD_DARK = "#785A28"
DARK_BG = "#010A13"
DARK_SURFACE = "#0A1428"
INPUT_BG = "#132035"
GRID_COLOR = "#1E2D40"
TEXT_COLOR = "#F0E6D3"
TEXT_MUTED = "#A0A0A0"
TEXT_DIM = "#5B5A56"
WIN_COLOR = "#1D9E75"
LOSS_COLOR = "#E84057"
INFO_COLOR = "#0BC4E3"

LOL_CSS = """
<style>
/* Layout */
html, body, [data-testid="stAppViewContainer"], .stApp {
    background-color: #010A13 !important;
}
.block-container { padding-top: 2rem; padding-bottom: 2rem; }
#MainMenu { visibility: hidden; }
footer { visibility: hidden; }

/* Typography */
h1, h2, h3, h4, h5, h6 {
    color: #C8AA6E !important;
    text-transform: uppercase !important;
    letter-spacing: 3px !important;
}
p, li, span, label, .stMarkdown {
    color: #F0E6D3;
}
label, [data-testid="stWidgetLabel"] {
    color: #A0A0A0 !important;
    font-size: 11px !important;
    font-weight: 600 !important;
    text-transform: uppercase !important;
    letter-spacing: 1.5px !important;
}

/* Scrollbar */
::-webkit-scrollbar { width: 4px; }
::-webkit-scrollbar-track { background: #010A13; }
::-webkit-scrollbar-thumb { background: #785A28; border-radius: 2px; }
::-webkit-scrollbar-thumb:hover { background: #C8AA6E; }

/* Buttons */
.stButton > button {
    background: transparent !important;
    border: 1px solid #C8AA6E !important;
    color: #C8AA6E !important;
    border-radius: 2px !important;
    text-transform: uppercase !important;
    letter-spacing: 1.2px !important;
    font-size: 12px !important;
    font-weight: 600 !important;
    padding: 10px 16px !important;
    min-height: 44px !important;
    line-height: 1.35 !important;
    white-space: normal !important;
    width: 100% !important;
    transition: all 0.2s ease !important;
}
.stButton > button:hover {
    background: #C8AA6E18 !important;
    box-shadow: 0 0 16px #C8AA6E33 !important;
    color: #C8AA6E !important;
}
.stButton > button[kind="primary"] {
    background: #C8AA6E18 !important;
}

/* Inputs */
.stTextInput > div > div > input,
.stNumberInput input,
textarea {
    background: #0A1428 !important;
    border: 1px solid #1E2D40 !important;
    border-radius: 2px !important;
    color: #F0E6D3 !important;
    font-size: 14px !important;
}
.stTextInput > div > div > input:focus,
.stNumberInput input:focus,
textarea:focus {
    border-color: #C8AA6E !important;
    box-shadow: 0 0 8px #C8AA6E22 !important;
}

/* Selectbox */
.stSelectbox > div > div,
.stSelectbox [data-baseweb="select"] {
    background: #0A1428 !important;
    border: 1px solid #1E2D40 !important;
    border-radius: 2px !important;
    color: #F0E6D3 !important;
}
[data-baseweb="popover"] [role="listbox"] {
    background: #0A1428 !important;
    border: 1px solid #1E2D40 !important;
}

/* Slider */
.stSlider > div > div > div { background: #C8AA6E !important; }
[data-testid="stSlider"] [role="slider"] { background: #C8AA6E !important; }

/* Expander */
.streamlit-expanderHeader,
[data-testid="stExpander"] summary {
    background: #0A1428 !important;
    border: 1px solid #1E2D40 !important;
    border-radius: 2px !important;
    color: #A0A0A0 !important;
    font-size: 11px !important;
    text-transform: uppercase !important;
    letter-spacing: 1.5px !important;
}
.streamlit-expanderHeader:hover,
[data-testid="stExpander"] summary:hover {
    border-color: #C8AA6E44 !important;
    color: #C8AA6E !important;
}
[data-testid="stExpander"] {
    background: #0A1428 !important;
    border: 1px solid #1E2D40 !important;
    border-radius: 2px !important;
}

/* Metrics */
[data-testid="stMetric"] {
    background: #0A1428 !important;
    border: 1px solid #1E2D40 !important;
    border-radius: 4px !important;
    padding: 16px !important;
}
[data-testid="stMetricLabel"] {
    color: #A0A0A0 !important;
    font-size: 11px !important;
    text-transform: uppercase !important;
    letter-spacing: 1.5px !important;
}
[data-testid="stMetricValue"] {
    color: #F0E6D3 !important;
    font-size: 28px !important;
    font-weight: 700 !important;
}
[data-testid="stMetricDelta"] {
    font-size: 13px !important;
    font-weight: 500 !important;
}

/* Alerts */
.stSuccess, [data-testid="stAlert"][data-type="success"] {
    background: #071A12 !important;
    border: 1px solid #1D9E75 !important;
    border-radius: 2px !important;
}
.stWarning, [data-testid="stAlert"][data-type="warning"] {
    background: #1A1200 !important;
    border: 1px solid #C8AA6E !important;
    border-radius: 2px !important;
}
.stError, [data-testid="stAlert"][data-type="error"] {
    background: #1A0508 !important;
    border: 1px solid #E84057 !important;
    border-radius: 2px !important;
}
.stInfo, [data-testid="stAlert"][data-type="info"] {
    background: #0A1428 !important;
    border: 1px solid #0BC4E3 !important;
    border-radius: 2px !important;
}

/* Sidebar */
[data-testid="stSidebar"] {
    background: #010A13 !important;
    border-right: 1px solid #1E2D40 !important;
}

/* Sidebar nav */
[data-testid="stSidebarNav"] a {
    color: #A0A0A0 !important;
    font-size: 11px !important;
    text-transform: uppercase !important;
    letter-spacing: 1.5px !important;
}
[data-testid="stSidebarNav"] a:hover { color: #C8AA6E !important; }
[data-testid="stSidebarNav"] a[aria-selected="true"] {
    color: #C8AA6E !important;
    background: #C8AA6E11 !important;
    border-left: 2px solid #C8AA6E !important;
}

/* Divider */
hr, [data-testid="stDivider"] {
    border-color: #1E2D40 !important;
    margin: 24px 0 !important;
}

/* Tables, tabs, chat, containers */
[data-testid="stDataFrame"],
[data-testid="stVerticalBlockBorderWrapper"],
[data-testid="stChatMessage"],
[data-testid="stChatInputContainer"] {
    background: #0A1428 !important;
    border: 1px solid #1E2D40 !important;
    border-radius: 2px !important;
}
[data-testid="stTabs"] [role="tab"] {
    color: #A0A0A0 !important;
    text-transform: uppercase !important;
    letter-spacing: 1.5px !important;
}
[data-testid="stTabs"] [role="tab"][aria-selected="true"] {
    color: #C8AA6E !important;
    border-bottom: 2px solid #C8AA6E !important;
}
.stCaption { color: #5B5A56 !important; font-size: 11px; letter-spacing: 1px; }
.js-plotly-plot .plotly .modebar { background: transparent !important; }
</style>
"""

CHART_LAYOUT = dict(
    paper_bgcolor="rgba(0,0,0,0)",
    plot_bgcolor="#0A1428",
    font=dict(color="#A0A0A0", size=11, family="sans-serif"),
    title=dict(text="", font=dict(color="#C8AA6E", size=13)),
    xaxis=dict(
        gridcolor="#1E2D40", linecolor="#1E2D40",
        tickcolor="#1E2D40", tickfont=dict(size=10, color="#5B5A56"),
        title_font=dict(size=11, color="#A0A0A0"),
    ),
    yaxis=dict(
        gridcolor="#1E2D40", linecolor="#1E2D40",
        tickcolor="#1E2D40", tickfont=dict(size=10, color="#5B5A56"),
        title_font=dict(size=11, color="#A0A0A0"),
    ),
    legend=dict(
        bgcolor="rgba(0,0,0,0)",
        font=dict(size=10, color="#A0A0A0"),
    ),
    margin=dict(l=40, r=20, t=36, b=40),
    colorway=["#C8AA6E", "#1D9E75", "#0BC4E3", "#E84057", "#785A28"],
)


def inject_css():
    st.markdown(LOL_CSS, unsafe_allow_html=True)


def render_sidebar():
    st.sidebar.html("""
    <div style="text-align:center; padding: 20px 0 16px 0;">
        <div style="color:#785A28; letter-spacing:6px; font-size:11px; margin-bottom:12px;">
            -- ⚔ --
        </div>
        <div style="font-size:13px; font-weight:700; color:#C8AA6E;
                    letter-spacing:4px; text-transform:uppercase;">
            RISE TO
        </div>
        <div style="font-size:18px; font-weight:800; color:#C8AA6E;
                    letter-spacing:4px; text-transform:uppercase; margin-bottom:6px;">
            CHALLENGER
        </div>
        <div style="font-size:9px; color:#5B5A56; letter-spacing:2px;
                    text-transform:uppercase;">
            MASTER THE META
        </div>
        <div style="color:#785A28; letter-spacing:6px; font-size:11px; margin-top:12px;">
            -- ⚔ --
        </div>
    </div>
    """)

    st.sidebar.divider()

    st.sidebar.html("""
    <div style="font-size:10px; color:#5B5A56; text-transform:uppercase;
                letter-spacing:1.5px; line-height:2.2;">
    NA · SOLO/DUO RANKED<br>
    MASTER+ DATA<br>
    REAL-TIME API
    </div>
    """)


def render_page_header(title, subtitle):
    st.html(f"""
    <div style="padding: 8px 0 24px 0;">
        <div style="font-size:10px; color:#785A28; letter-spacing:3px;
                    text-transform:uppercase; margin-bottom:6px;">
            RISE TO CHALLENGER
        </div>
        <div style="font-size:24px; font-weight:700; color:#C8AA6E;
                    letter-spacing:3px; text-transform:uppercase;
                    border-bottom:1px solid #785A28;
                    padding-bottom:12px; margin-bottom:8px;">
            {title}
        </div>
        <div style="font-size:11px; color:#5B5A56; letter-spacing:1px;">
            {subtitle}
        </div>
    </div>
    """)


def render_section_header(title):
    st.html(f"""
    <div style="display:flex; align-items:center; gap:10px;
                margin: 32px 0 16px 0;">
        <div style="width:3px; height:18px; background:#C8AA6E;
                    border-radius:1px; flex-shrink:0;"></div>
        <div style="font-size:13px; font-weight:700; color:#C8AA6E;
                    letter-spacing:2px; text-transform:uppercase;">
            {title}
        </div>
    </div>
    """)


def chart_layout(**kwargs) -> dict:
    """Return CHART_LAYOUT merged with any overrides."""
    layout = dict(CHART_LAYOUT)
    for key in ("xaxis", "yaxis", "legend", "title", "margin"):
        if key in kwargs and isinstance(kwargs[key], dict):
            merged = dict(layout.get(key, {}))
            merged.update(kwargs.pop(key))
            kwargs[key] = merged
    layout.update(kwargs)
    return layout
