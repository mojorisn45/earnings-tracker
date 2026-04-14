"""
EARNINGS TRACKER — Post-Earnings Accumulation Strategy
Companion app for the Pre-Earnings Prediction System v4.0

Tracks stocks through the full lifecycle:
  Screener flagged → v4.0 analyzed → Earnings reported → Entry signal → Position open → Sold

Run locally:  streamlit run app.py
Deploy:       Push to GitHub → Connect to Streamlit Cloud (free)

Data persistence:
  - Streamlit Cloud: reads/writes earnings_data.json via GitHub API (needs
    a PAT in Streamlit secrets — see .streamlit/secrets.toml.example)
  - Local: reads/writes earnings_data.json on disk (same directory)
"""

import streamlit as st
import json
import base64
import requests
from datetime import datetime, timedelta, date
from pathlib import Path
import calendar as cal

# ─── Configuration ──────────────────────────────────────────────────────────

DATA_FILE = Path(__file__).parent / "earnings_data.json"
DATA_PATH_IN_REPO = "earnings_data.json"  # path inside the GitHub repo

STAGES = {
    "screener_flagged": {"label": "📡 Screener Flagged", "color": "#6366f1", "order": 1},
    "v4_analyzing": {"label": "🔬 Running v4.0", "color": "#f59e0b", "order": 2},
    "v4_complete": {"label": "✅ Analysis Done", "color": "#3b82f6", "order": 3},
    "watching": {"label": "👁️ Watching Earnings", "color": "#8b5cf6", "order": 4},
    "entry_signal": {"label": "🎯 Entry Signal!", "color": "#10b981", "order": 5},
    "position_open": {"label": "💰 Position Open", "color": "#06b6d4", "order": 6},
    "sold": {"label": "🏁 Sold", "color": "#6b7280", "order": 7},
    "passed": {"label": "⏭️ Passed", "color": "#374151", "order": 8},
}

EMPTY_STOCK = {
    "ticker": "",
    "name": "",
    "earnings_date": "",
    "timing": "AMC",
    "sector": "",
    "screener_score": None,
    "v4_score": None,
    "v4_confidence": None,
    "v4_direction": "",
    "stage": "screener_flagged",
    "earnings_result": {
        "eps_actual": None,
        "eps_estimate": None,
        "surprise_pct": None,
        "stock_reaction_pct": None,
        "beat": None,
        "selloff": None,
    },
    "position": {
        "entry_date": "",
        "entry_price": None,
        "shares": None,
        "cost_basis": None,
        "target_price": None,
        "stop_loss": None,
        "exit_date": "",
        "exit_price": None,
        "covered_call_income": 0,
    },
    "notes": "",
    "created_at": "",
    "quarter": "",
}


# ─── Data Layer ─────────────────────────────────────────────────────────────
#
# Dual-mode persistence:
#   - If [github] is in Streamlit secrets → read/write via GitHub Contents API
#   - Otherwise → read/write local earnings_data.json
#
# GitHub secrets format (in .streamlit/secrets.toml or Streamlit Cloud UI):
#   [github]
#   token = "ghp_xxxxxxxxxxxx"    # PAT with 'repo' scope
#   repo  = "mojorisn45/earnings-tracker"

EMPTY_DATA = {"stocks": [], "settings": {"default_position_size": 10000}}


def _github_cfg():
    """Return (token, repo) if GitHub secrets are configured, else (None, None)."""
    try:
        gh = st.secrets["github"]
        return gh["token"], gh["repo"]
    except (KeyError, FileNotFoundError):
        return None, None


def _github_headers(token):
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def _github_read(token, repo):
    """Read earnings_data.json from the GitHub repo.  Returns (data_dict, sha)."""
    url = f"https://api.github.com/repos/{repo}/contents/{DATA_PATH_IN_REPO}"
    r = requests.get(url, headers=_github_headers(token), timeout=10)
    if r.status_code == 404:
        return dict(EMPTY_DATA), None          # file doesn't exist yet
    r.raise_for_status()
    payload = r.json()
    content = base64.b64decode(payload["content"]).decode("utf-8")
    return json.loads(content), payload["sha"]


def _github_write(token, repo, data, sha):
    """Write earnings_data.json back to the GitHub repo."""
    url = f"https://api.github.com/repos/{repo}/contents/{DATA_PATH_IN_REPO}"
    content_b64 = base64.b64encode(
        json.dumps(data, indent=2, default=str).encode("utf-8")
    ).decode("utf-8")
    body = {
        "message": f"Update earnings data — {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        "content": content_b64,
    }
    if sha:
        body["sha"] = sha                     # required for updates (not creates)
    r = requests.put(url, headers=_github_headers(token), json=body, timeout=10)
    r.raise_for_status()
    # Update stored SHA so the next save doesn't conflict
    st.session_state["_gh_sha"] = r.json()["content"]["sha"]


def load_data():
    token, repo = _github_cfg()
    if token:
        data, sha = _github_read(token, repo)
        st.session_state["_gh_sha"] = sha      # cache for save_data
        return data
    # Local fallback
    if DATA_FILE.exists():
        with open(DATA_FILE, "r") as f:
            return json.load(f)
    return dict(EMPTY_DATA)


def save_data(data):
    token, repo = _github_cfg()
    if token:
        sha = st.session_state.get("_gh_sha")
        _github_write(token, repo, data, sha)
        return
    # Local fallback
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=2, default=str)


def get_current_quarter():
    now = datetime.now()
    q = (now.month - 1) // 3 + 1
    return f"Q{q} {now.year}"


def parse_date(d):
    if not d:
        return None
    try:
        return datetime.strptime(d, "%Y-%m-%d").date()
    except ValueError:
        return None


# ─── Page Config ────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="Earnings Tracker",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Custom CSS
st.markdown("""
<style>
    .stApp { }
    div[data-testid="stMetric"] {
        background: #1e293b;
        padding: 12px 16px;
        border-radius: 8px;
        border: 1px solid #334155;
    }
    div[data-testid="stMetric"] label {
        color: #94a3b8 !important;
    }
    .action-card {
        background: #0f172a;
        border: 1px solid #1e293b;
        border-radius: 8px;
        padding: 16px;
        margin-bottom: 8px;
    }
    .action-urgent {
        border-left: 4px solid #ef4444;
    }
    .action-today {
        border-left: 4px solid #f59e0b;
    }
    .action-upcoming {
        border-left: 4px solid #3b82f6;
    }
    .stage-badge {
        display: inline-block;
        padding: 2px 10px;
        border-radius: 12px;
        font-size: 12px;
        font-weight: 600;
    }
    .calendar-day {
        padding: 4px;
        min-height: 80px;
        border: 1px solid #1e293b;
        border-radius: 4px;
    }
    .calendar-day-today {
        border: 2px solid #3b82f6;
    }
    .profit { color: #10b981; }
    .loss { color: #ef4444; }
    .neutral { color: #94a3b8; }
</style>
""", unsafe_allow_html=True)


# ─── Load Data ──────────────────────────────────────────────────────────────

data = load_data()
stocks = data.get("stocks", [])
settings = data.get("settings", {"default_position_size": 10000})


# ─── Sidebar Navigation ────────────────────────────────────────────────────

st.sidebar.title("📊 Earnings Tracker")
st.sidebar.caption("Post-Earnings Accumulation Strategy")

page = st.sidebar.radio(
    "Navigate",
    ["🎯 Today's Actions", "📅 Calendar", "🔄 Pipeline", "💰 Positions", "📈 History", "➕ Add Stock"],
    label_visibility="collapsed",
)

st.sidebar.divider()

# Quick stats in sidebar
active = [s for s in stocks if s["stage"] not in ("sold", "passed")]
positions = [s for s in stocks if s["stage"] == "position_open"]
signals = [s for s in stocks if s["stage"] == "entry_signal"]

st.sidebar.metric("Active Watchlist", len(active))
st.sidebar.metric("Entry Signals", len(signals))
st.sidebar.metric("Open Positions", len(positions))

if positions:
    # Quick P&L (requires manual current price updates)
    total_cost = sum(
        (s["position"].get("cost_basis") or 0)
        for s in positions
    )
    st.sidebar.metric("Capital Deployed", f"${total_cost:,.0f}")

st.sidebar.divider()
st.sidebar.caption(f"Quarter: {get_current_quarter()}")
st.sidebar.caption(f"Data: {DATA_FILE.name}")


# ─── Page: Today's Actions ──────────────────────────────────────────────────

if page == "🎯 Today's Actions":
    st.title("🎯 Today's Actions")
    st.caption(f"{datetime.now().strftime('%A, %B %d, %Y')}")
    
    today = date.today()
    tomorrow = today + timedelta(days=1)
    this_week_end = today + timedelta(days=(4 - today.weekday()) if today.weekday() < 5 else 0)
    
    # Categorize actions
    urgent_actions = []
    today_actions = []
    upcoming_actions = []
    
    for s in stocks:
        ed = parse_date(s.get("earnings_date", ""))
        stage = s["stage"]
        
        # Entry signals that need action NOW
        if stage == "entry_signal":
            urgent_actions.append({
                "ticker": s["ticker"],
                "action": f"BUY SIGNAL — {s['ticker']} beat earnings and sold off. Evaluate entry today.",
                "detail": f"Reaction: {s['earnings_result'].get('stock_reaction_pct', '?')}% | Surprise: {s['earnings_result'].get('surprise_pct', '?')}%",
                "type": "urgent"
            })
        
        # Earnings reporting today
        if ed == today and stage in ("v4_complete", "watching"):
            today_actions.append({
                "ticker": s["ticker"],
                "action": f"EARNINGS TODAY — {s['ticker']} reports {s.get('timing', '?')}. Watch results tonight.",
                "detail": f"v4.0 Score: {s.get('v4_score', '?')}/5.0 | Confidence: {s.get('v4_confidence', '?')}%",
                "type": "today"
            })
        
        # Earnings reporting tomorrow
        if ed == tomorrow and stage in ("v4_complete", "watching"):
            today_actions.append({
                "ticker": s["ticker"],
                "action": f"EARNINGS TOMORROW — {s['ticker']} reports {s.get('timing', '?')} tomorrow.",
                "detail": f"v4.0 Score: {s.get('v4_score', '?')}/5.0 | Direction: {s.get('v4_direction', '?')}",
                "type": "today"
            })
        
        # Needs v4.0 analysis and earnings are within 5 days
        if stage == "screener_flagged" and ed and ed <= today + timedelta(days=5):
            today_actions.append({
                "ticker": s["ticker"],
                "action": f"ANALYZE — Run v4.0 on {s['ticker']} (reports {s['earnings_date']} {s.get('timing', '')})",
                "detail": f"Screener Score: {s.get('screener_score', '?')}/5.0",
                "type": "today"
            })
        
        # Open positions — check targets and stops
        if stage == "position_open":
            entry = s["position"].get("entry_price", 0)
            target = s["position"].get("target_price")
            stop = s["position"].get("stop_loss")
            entry_d = parse_date(s["position"].get("entry_date", ""))
            if entry_d:
                days_held = (today - entry_d).days
                if days_held >= 55:
                    urgent_actions.append({
                        "ticker": s["ticker"],
                        "action": f"APPROACHING EXIT — {s['ticker']} held {days_held} days (60-day max approaching)",
                        "detail": f"Entry: ${entry:.2f} | Target: ${target or '?'} | Stop: ${stop or '?'}",
                        "type": "urgent"
                    })
                else:
                    upcoming_actions.append({
                        "ticker": s["ticker"],
                        "action": f"HOLDING — {s['ticker']} (Day {days_held}/60)",
                        "detail": f"Entry: ${entry:.2f} | Target: ${target or '?'} | Stop: ${stop or '?'}",
                        "type": "upcoming"
                    })
        
        # Upcoming earnings this week that need analysis
        if stage == "screener_flagged" and ed and today < ed <= this_week_end:
            upcoming_actions.append({
                "ticker": s["ticker"],
                "action": f"UPCOMING — {s['ticker']} reports {s['earnings_date']}. Consider running v4.0.",
                "detail": f"Screener Score: {s.get('screener_score', '?')}/5.0 | Sector: {s.get('sector', '?')}",
                "type": "upcoming"
            })
    
    # Display actions
    if not urgent_actions and not today_actions and not upcoming_actions:
        st.info("✅ No actions needed today. Check back when earnings season heats up.")
    
    if urgent_actions:
        st.subheader("🔴 Needs Immediate Action")
        for a in urgent_actions:
            st.error(f"**{a['action']}**\n\n{a['detail']}")
    
    if today_actions:
        st.subheader("🟡 Today")
        for a in today_actions:
            st.warning(f"**{a['action']}**\n\n{a['detail']}")
    
    if upcoming_actions:
        st.subheader("🔵 This Week")
        for a in upcoming_actions:
            st.info(f"**{a['action']}**\n\n{a['detail']}")
    
    # Morning screener results import
    st.divider()
    st.subheader("📡 Import Screener Results")
    
    screener_file = st.file_uploader(
        "Upload today's screener top3 file",
        type=["txt"],
        help="Upload the _top3.txt file from ~/screener/logs/"
    )
    
    if screener_file:
        content = screener_file.read().decode("utf-8")
        st.code(content, language="text")
        st.caption("Review the screener output above, then add individual stocks using the ➕ Add Stock page.")


# ─── Page: Calendar ─────────────────────────────────────────────────────────

elif page == "📅 Calendar":
    st.title("📅 Earnings Calendar")
    
    # Month selector
    col1, col2 = st.columns([1, 3])
    with col1:
        selected_month = st.selectbox(
            "Month",
            options=list(range(1, 13)),
            index=datetime.now().month - 1,
            format_func=lambda m: cal.month_name[m]
        )
    with col2:
        selected_year = st.number_input("Year", value=datetime.now().year, min_value=2024, max_value=2030)
    
    # Build calendar data
    month_stocks = {}
    for s in stocks:
        ed = parse_date(s.get("earnings_date", ""))
        if ed and ed.month == selected_month and ed.year == selected_year:
            day = ed.day
            if day not in month_stocks:
                month_stocks[day] = []
            month_stocks[day].append(s)
    
    # Render calendar grid
    month_cal = cal.monthcalendar(selected_year, selected_month)
    
    # Day headers
    day_names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    header_cols = st.columns(7)
    for i, name in enumerate(day_names):
        header_cols[i].markdown(f"**{name}**")
    
    # Calendar weeks
    today = date.today()
    for week in month_cal:
        cols = st.columns(7)
        for i, day in enumerate(week):
            with cols[i]:
                if day == 0:
                    st.write("")
                    continue
                
                current_date = date(selected_year, selected_month, day)
                is_today = current_date == today
                day_stocks = month_stocks.get(day, [])
                
                # Day header
                if is_today:
                    st.markdown(f"**:blue[{day} ←]**")
                else:
                    st.markdown(f"**{day}**")
                
                # Stock entries for this day
                for s in day_stocks:
                    stage_info = STAGES.get(s["stage"], STAGES["screener_flagged"])
                    timing = s.get("timing", "")
                    timing_icon = "☀️" if timing == "BMO" else "🌙" if timing == "AMC" else ""
                    
                    if s["stage"] == "entry_signal":
                        st.success(f"{timing_icon} **{s['ticker']}**")
                    elif s["stage"] == "position_open":
                        st.info(f"{timing_icon} **{s['ticker']}**")
                    elif s["stage"] in ("sold", "passed"):
                        st.caption(f"{timing_icon} ~~{s['ticker']}~~")
                    else:
                        st.write(f"{timing_icon} **{s['ticker']}**")
    
    # Legend
    st.divider()
    legend_cols = st.columns(4)
    legend_cols[0].success("🎯 Entry Signal")
    legend_cols[1].info("💰 Position Open")
    legend_cols[2].write("👁️ Watching")
    legend_cols[3].caption("~~Passed/Sold~~")


# ─── Page: Pipeline ─────────────────────────────────────────────────────────

elif page == "🔄 Pipeline":
    st.title("🔄 Pipeline")
    st.caption("Track stocks through each stage of the post-earnings accumulation workflow")
    
    # Group stocks by stage
    active_stages = ["screener_flagged", "v4_analyzing", "v4_complete", "watching", "entry_signal", "position_open"]
    
    for stage_key in active_stages:
        stage_info = STAGES[stage_key]
        stage_stocks = [s for s in stocks if s["stage"] == stage_key]
        
        if not stage_stocks and stage_key not in ("entry_signal", "position_open"):
            continue
        
        st.subheader(f"{stage_info['label']} ({len(stage_stocks)})")
        
        if not stage_stocks:
            st.caption("None")
            continue
        
        for idx, s in enumerate(stage_stocks):
            # Find original index in full stocks list
            orig_idx = stocks.index(s)
            
            with st.expander(f"**{s['ticker']}** — {s.get('name', '')} | Earnings: {s.get('earnings_date', '?')} {s.get('timing', '')}", expanded=(stage_key == "entry_signal")):
                
                info_col, action_col = st.columns([2, 1])
                
                with info_col:
                    if s.get("screener_score"):
                        st.write(f"Screener Score: **{s['screener_score']}/5.0**")
                    if s.get("v4_score"):
                        st.write(f"v4.0 Score: **{s['v4_score']}/5.0** | Confidence: **{s.get('v4_confidence', '?')}%** | Direction: **{s.get('v4_direction', '?')}**")
                    if s.get("earnings_result", {}).get("eps_actual"):
                        er = s["earnings_result"]
                        st.write(f"Result: EPS ${er['eps_actual']} vs ${er['eps_estimate']} est ({er.get('surprise_pct', '?')}% surprise) | Reaction: {er.get('stock_reaction_pct', '?')}%")
                    if s.get("position", {}).get("entry_price"):
                        pos = s["position"]
                        st.write(f"Position: {pos.get('shares', '?')} shares @ ${pos['entry_price']:.2f} | Target: ${pos.get('target_price', '?')} | Stop: ${pos.get('stop_loss', '?')}")
                    if s.get("notes"):
                        st.caption(f"Notes: {s['notes']}")
                
                with action_col:
                    # Stage transition buttons
                    next_stages = {
                        "screener_flagged": ["v4_analyzing", "passed"],
                        "v4_analyzing": ["v4_complete", "passed"],
                        "v4_complete": ["watching", "passed"],
                        "watching": ["entry_signal", "passed"],
                        "entry_signal": ["position_open", "passed"],
                        "position_open": ["sold"],
                    }
                    
                    available = next_stages.get(stage_key, [])
                    for next_stage in available:
                        next_info = STAGES[next_stage]
                        if st.button(
                            f"→ {next_info['label']}",
                            key=f"move_{orig_idx}_{next_stage}",
                            use_container_width=True,
                        ):
                            stocks[orig_idx]["stage"] = next_stage
                            save_data({"stocks": stocks, "settings": settings})
                            st.rerun()


# ─── Page: Positions ────────────────────────────────────────────────────────

elif page == "💰 Positions":
    st.title("💰 Open Positions")
    
    positions = [s for s in stocks if s["stage"] == "position_open"]
    
    if not positions:
        st.info("No open positions. Positions appear here when you move a stock to 'Position Open' in the Pipeline and enter your trade details.")
    
    for s in positions:
        orig_idx = stocks.index(s)
        pos = s.get("position", {})
        entry_price = pos.get("entry_price", 0)
        shares = pos.get("shares", 0)
        cost_basis = entry_price * shares if entry_price and shares else 0
        target = pos.get("target_price")
        stop = pos.get("stop_loss")
        entry_d = parse_date(pos.get("entry_date", ""))
        days_held = (date.today() - entry_d).days if entry_d else 0
        covered_call = pos.get("covered_call_income", 0)
        
        with st.expander(f"**{s['ticker']}** — {shares or '?'} shares @ ${entry_price or '?':.2f} | Day {days_held}/60", expanded=True):
            
            col1, col2, col3, col4 = st.columns(4)
            col1.metric("Cost Basis", f"${cost_basis:,.2f}")
            col2.metric("Target", f"${target or 0:,.2f}", f"+{((target/entry_price - 1)*100):.1f}%" if target and entry_price else "")
            col3.metric("Stop Loss", f"${stop or 0:,.2f}", f"{((stop/entry_price - 1)*100):.1f}%" if stop and entry_price else "")
            col4.metric("Days Held", f"{days_held}/60", f"{60 - days_held} remaining")
            
            if covered_call > 0:
                st.write(f"Covered Call Income: **${covered_call:,.2f}**")
            
            # Edit position details
            st.divider()
            with st.form(f"edit_pos_{orig_idx}"):
                st.write("**Update Position**")
                fc1, fc2, fc3 = st.columns(3)
                with fc1:
                    new_covered = st.number_input(
                        "Covered Call Income ($)",
                        value=float(covered_call),
                        step=50.0,
                        key=f"cc_{orig_idx}"
                    )
                with fc2:
                    exit_price = st.number_input(
                        "Exit Price (to close position)",
                        value=0.0,
                        step=0.5,
                        key=f"exit_{orig_idx}"
                    )
                with fc3:
                    exit_date = st.date_input(
                        "Exit Date",
                        value=date.today(),
                        key=f"exitd_{orig_idx}"
                    )
                
                new_notes = st.text_input("Notes", value=s.get("notes", ""), key=f"notes_{orig_idx}")
                
                if st.form_submit_button("Update"):
                    stocks[orig_idx]["position"]["covered_call_income"] = new_covered
                    stocks[orig_idx]["notes"] = new_notes
                    
                    if exit_price > 0:
                        stocks[orig_idx]["position"]["exit_price"] = exit_price
                        stocks[orig_idx]["position"]["exit_date"] = exit_date.isoformat()
                        stocks[orig_idx]["stage"] = "sold"
                    
                    save_data({"stocks": stocks, "settings": settings})
                    st.rerun()


# ─── Page: History ──────────────────────────────────────────────────────────

elif page == "📈 History":
    st.title("📈 Trade History")
    
    completed = [s for s in stocks if s["stage"] in ("sold", "passed")]
    sold = [s for s in stocks if s["stage"] == "sold"]
    passed = [s for s in stocks if s["stage"] == "passed"]
    
    if sold:
        st.subheader("Completed Trades")
        
        # Summary stats
        wins = 0
        losses = 0
        total_pnl = 0
        total_cc_income = 0
        
        for s in sold:
            pos = s.get("position", {})
            entry = pos.get("entry_price", 0)
            exit_p = pos.get("exit_price", 0)
            shares = pos.get("shares", 0)
            cc = pos.get("covered_call_income", 0)
            
            if entry and exit_p and shares:
                trade_pnl = (exit_p - entry) * shares + cc
                total_pnl += trade_pnl
                total_cc_income += cc
                if trade_pnl >= 0:
                    wins += 1
                else:
                    losses += 1
        
        total_trades = wins + losses
        
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Total Trades", total_trades)
        col2.metric("Win Rate", f"{(wins/total_trades*100):.0f}%" if total_trades > 0 else "N/A")
        col3.metric("Total P&L", f"${total_pnl:,.2f}", delta=f"${total_pnl:,.2f}")
        col4.metric("Covered Call Income", f"${total_cc_income:,.2f}")
        
        st.divider()
        
        # Trade detail table
        for s in sold:
            pos = s.get("position", {})
            entry = pos.get("entry_price", 0)
            exit_p = pos.get("exit_price", 0)
            shares = pos.get("shares", 0)
            cc = pos.get("covered_call_income", 0)
            
            if entry and exit_p and shares:
                trade_pnl = (exit_p - entry) * shares + cc
                pct_return = ((exit_p - entry) / entry * 100) if entry else 0
                pnl_class = "profit" if trade_pnl >= 0 else "loss"
                icon = "✅" if trade_pnl >= 0 else "❌"
                
                entry_d = pos.get("entry_date", "?")
                exit_d = pos.get("exit_date", "?")
                
                st.write(
                    f"{icon} **{s['ticker']}** — "
                    f"{shares} shares | "
                    f"${entry:.2f} → ${exit_p:.2f} ({pct_return:+.1f}%) | "
                    f"P&L: **${trade_pnl:+,.2f}** | "
                    f"{entry_d} → {exit_d}"
                )
                if cc > 0:
                    st.caption(f"  ↳ Includes ${cc:.2f} covered call income")
    
    if passed:
        st.divider()
        st.subheader(f"Passed ({len(passed)})")
        for s in passed:
            st.caption(f"⏭️ {s['ticker']} — {s.get('earnings_date', '?')} — {s.get('notes', 'No notes')}")
    
    if not completed:
        st.info("No completed trades yet. Trades appear here when you close a position or pass on a stock.")


# ─── Page: Add Stock ────────────────────────────────────────────────────────

elif page == "➕ Add Stock":
    st.title("➕ Add Stock to Tracker")
    
    with st.form("add_stock"):
        st.subheader("Stock Details")
        
        col1, col2, col3 = st.columns(3)
        with col1:
            ticker = st.text_input("Ticker", placeholder="NFLX").upper().strip()
        with col2:
            name = st.text_input("Company Name", placeholder="Netflix")
        with col3:
            sector = st.text_input("Sector", placeholder="Streaming")
        
        col4, col5, col6 = st.columns(3)
        with col4:
            earnings_date = st.date_input("Earnings Date", value=date.today() + timedelta(days=7))
        with col5:
            timing = st.selectbox("Timing", ["BMO", "AMC"])
        with col6:
            stage = st.selectbox(
                "Initial Stage",
                options=list(STAGES.keys()),
                format_func=lambda k: STAGES[k]["label"],
            )
        
        st.subheader("Scores (fill in as available)")
        
        sc1, sc2, sc3, sc4 = st.columns(4)
        with sc1:
            screener_score = st.number_input("Screener Score", min_value=0.0, max_value=5.0, step=0.01, value=0.0)
        with sc2:
            v4_score = st.number_input("v4.0 Score", min_value=0.0, max_value=5.0, step=0.01, value=0.0)
        with sc3:
            v4_confidence = st.number_input("v4.0 Confidence %", min_value=0, max_value=100, step=1, value=0)
        with sc4:
            v4_direction = st.selectbox("Direction", ["", "STRONGLY BULLISH", "LEAN BULLISH", "NO EDGE", "LEAN BEARISH", "STRONGLY BEARISH"])
        
        st.subheader("Earnings Result (fill in after report)")
        
        er1, er2, er3, er4 = st.columns(4)
        with er1:
            eps_actual = st.number_input("Actual EPS", step=0.01, value=0.0)
        with er2:
            eps_estimate = st.number_input("Est. EPS", step=0.01, value=0.0)
        with er3:
            reaction_pct = st.number_input("Stock Reaction %", step=0.1, value=0.0)
        with er4:
            beat = st.selectbox("Beat?", [None, True, False], format_func=lambda x: "TBD" if x is None else ("Yes" if x else "No"))
        
        st.subheader("Position Details (fill in when buying)")
        
        p1, p2, p3, p4 = st.columns(4)
        with p1:
            entry_price = st.number_input("Entry Price", step=0.5, value=0.0)
        with p2:
            shares_count = st.number_input("Shares", step=1, value=0)
        with p3:
            target_price = st.number_input("Target Price", step=0.5, value=0.0)
        with p4:
            stop_loss = st.number_input("Stop Loss", step=0.5, value=0.0)
        
        notes = st.text_area("Notes", placeholder="Key thesis, cross-read notes, risks...")
        
        submitted = st.form_submit_button("Add Stock", type="primary", use_container_width=True)
        
        if submitted and ticker:
            # Check for duplicates in current quarter
            existing = [s for s in stocks if s["ticker"] == ticker and s.get("quarter") == get_current_quarter()]
            if existing:
                st.error(f"{ticker} already exists in {get_current_quarter()}. Edit it in the Pipeline instead.")
            else:
                surprise_pct = 0
                if eps_estimate and eps_actual:
                    surprise_pct = ((eps_actual - eps_estimate) / abs(eps_estimate)) * 100
                
                new_stock = {
                    "ticker": ticker,
                    "name": name,
                    "earnings_date": earnings_date.isoformat(),
                    "timing": timing,
                    "sector": sector,
                    "screener_score": screener_score if screener_score > 0 else None,
                    "v4_score": v4_score if v4_score > 0 else None,
                    "v4_confidence": v4_confidence if v4_confidence > 0 else None,
                    "v4_direction": v4_direction,
                    "stage": stage,
                    "earnings_result": {
                        "eps_actual": eps_actual if eps_actual != 0 else None,
                        "eps_estimate": eps_estimate if eps_estimate != 0 else None,
                        "surprise_pct": round(surprise_pct, 2) if surprise_pct else None,
                        "stock_reaction_pct": reaction_pct if reaction_pct != 0 else None,
                        "beat": beat,
                        "selloff": None,
                    },
                    "position": {
                        "entry_date": "",
                        "entry_price": entry_price if entry_price > 0 else None,
                        "shares": shares_count if shares_count > 0 else None,
                        "cost_basis": (entry_price * shares_count) if entry_price > 0 and shares_count > 0 else None,
                        "target_price": target_price if target_price > 0 else None,
                        "stop_loss": stop_loss if stop_loss > 0 else None,
                        "exit_date": "",
                        "exit_price": None,
                        "covered_call_income": 0,
                    },
                    "notes": notes,
                    "created_at": datetime.now().isoformat(),
                    "quarter": get_current_quarter(),
                }
                
                stocks.append(new_stock)
                save_data({"stocks": stocks, "settings": settings})
                st.success(f"✅ {ticker} added to {STAGES[stage]['label']}")
                st.rerun()
        elif submitted and not ticker:
            st.error("Ticker is required.")
    
    # Quick add from screener
    st.divider()
    st.subheader("⚡ Quick Add Multiple Tickers")
    st.caption("Paste tickers separated by commas. They'll all be added as 'Screener Flagged' with today's date.")
    
    quick_tickers = st.text_input("Tickers", placeholder="DAL, TSM, NFLX, MA, V, SPOT")
    quick_date = st.date_input("Earnings date (approximate)", value=date.today() + timedelta(days=5), key="quick_date")
    
    if st.button("Quick Add All", use_container_width=True):
        if quick_tickers:
            added = 0
            for t in quick_tickers.split(","):
                t = t.strip().upper()
                if not t:
                    continue
                existing = [s for s in stocks if s["ticker"] == t and s.get("quarter") == get_current_quarter()]
                if existing:
                    continue
                
                new_stock = dict(EMPTY_STOCK)
                new_stock["ticker"] = t
                new_stock["earnings_date"] = quick_date.isoformat()
                new_stock["stage"] = "screener_flagged"
                new_stock["created_at"] = datetime.now().isoformat()
                new_stock["quarter"] = get_current_quarter()
                stocks.append(new_stock)
                added += 1
            
            save_data({"stocks": stocks, "settings": settings})
            st.success(f"✅ Added {added} stocks as Screener Flagged")
            st.rerun()
