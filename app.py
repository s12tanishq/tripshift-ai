"""TripShift competition dashboard. Run with: streamlit run app.py"""
from __future__ import annotations

from datetime import datetime, timezone
from html import escape
import os
from pathlib import Path

from dotenv import load_dotenv
import streamlit as st

from tripshift.agent import AgentWorkflowError, draft_messages, run_trip_agent
from tripshift.core import Validation, load_scenario
from tripshift.inventory import IndiaTravelSearch, InventorySnapshot, assess_flight_offers, search_guidance
from tripshift.scenario_io import MODES, PROVIDERS as SETUP_PROVIDERS, SavedSetup, load_setup, save_setup

DATA = Path(__file__).parent / "data" / "nagpur_demo.json"

st.set_page_config(page_title="TripShift | Journey recovery", page_icon="↗", layout="wide", initial_sidebar_state="collapsed")

st.markdown("""
<style>
:root { --bg:#090B0D; --surface:#111619; --surface2:#151C1E; --line:#26332F; --text:#F3F6F5; --muted:#95A5A3; --mint:#78F5C6; --amber:#F6C76B; --red:#FF827D; --ease-out:cubic-bezier(.22,1,.36,1); --ease-tap:cubic-bezier(.2,.8,.2,1); }
html, body, [class*="css"], .stApp { font-family: Inter, ui-sans-serif, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }
.stApp { background:var(--bg); color:var(--text); }
.block-container { max-width:1500px; padding:2rem 2.4rem 4rem; }
header[data-testid="stHeader"], #MainMenu, footer { visibility:hidden; }
[data-testid="stVerticalBlock"] { gap:.9rem; }
h1,h2,h3,p { color:var(--text); }
.brand { display:flex; align-items:center; justify-content:space-between; gap:1rem; padding-bottom:1.6rem; border-bottom:1px solid var(--line); }
.brand-name { font-size:1.16rem; font-weight:800; letter-spacing:-.05em; }
.brand-mark { display:inline-flex; align-items:center; justify-content:center; width:29px; height:29px; margin-right:.48rem; color:var(--bg); background:var(--mint); border-radius:8px; font-size:1.25rem; }
.brand-meta { color:var(--muted); font-size:.76rem; text-transform:uppercase; letter-spacing:.13em; }
.hero { padding:2.3rem 0 1rem; animation:rise .34s var(--ease-out) both; }
.eyebrow { color:var(--mint); text-transform:uppercase; letter-spacing:.16em; font-weight:700; font-size:.72rem; }
.hero h1 { font-size:clamp(2rem,4vw,3.45rem); line-height:1.08; letter-spacing:-.065em; margin:.55rem 0 .65rem; }
.hero p { color:var(--muted); font-size:1rem; max-width:720px; line-height:1.58; }
.section-heading { display:flex; justify-content:space-between; align-items:baseline; margin:1.35rem 0 .55rem; }
.section-heading h2 { font-size:1rem; font-weight:700; letter-spacing:-.02em; margin:0; }
.section-heading span { color:var(--muted); font-size:.77rem; }
.panel, .plan-card, .draft-card { background:var(--surface); border:1px solid var(--line); border-radius:16px; padding:1.15rem 1.2rem; transition:transform .16s var(--ease-tap), border-color .2s ease, background .2s ease; animation:rise .32s var(--ease-out) both; }
.panel:hover, .plan-card:hover, .draft-card:hover { transform:translateY(-2px); border-color:#385D4F; background:var(--surface2); }
.panel-title { font-size:.72rem; color:var(--muted); text-transform:uppercase; letter-spacing:.13em; font-weight:700; margin-bottom:.6rem; }
.hero-metric { font-size:2.1rem; letter-spacing:-.06em; font-weight:800; line-height:1.1; }
.hero-metric small { font-size:.85rem; color:var(--muted); font-weight:500; letter-spacing:0; }
.footnote { font-size:.78rem; color:var(--muted); line-height:1.5; }
.timeline-item { display:grid; grid-template-columns:12px 1fr auto; gap:.72rem; min-height:72px; position:relative; }
.timeline-item:not(:last-child)::before { content:""; position:absolute; left:5px; top:18px; height:calc(100% - 15px); width:1px; background:var(--line); }
.dot { width:11px; height:11px; border-radius:50%; margin-top:6px; background:var(--mint); box-shadow:0 0 0 3px rgba(120,245,198,.09); }
.dot.at-risk { background:var(--amber); box-shadow:0 0 0 3px rgba(246,199,107,.1); }
.dot.broken { background:var(--red); box-shadow:0 0 0 3px rgba(255,130,125,.1); }
.item-name { font-size:.91rem; font-weight:650; }
.item-place { font-size:.74rem; color:var(--muted); margin-top:.18rem; }
.item-time { color:var(--text); font-size:.77rem; font-variant-numeric:tabular-nums; white-space:nowrap; text-align:right; line-height:1.45; }
.impact-row { padding:.72rem 0; border-bottom:1px solid var(--line); }
.impact-row:last-child { border-bottom:0; }
.impact-head { display:flex; align-items:center; justify-content:space-between; gap:.5rem; font-size:.87rem; font-weight:650; }
.impact-reason { color:var(--muted); font-size:.77rem; margin-top:.3rem; line-height:1.45; }
.cause-path { color:var(--mint); opacity:.8; font-size:.7rem; margin-top:.32rem; line-height:1.4; }
.badge { font-size:.72rem; text-transform:uppercase; letter-spacing:.075em; padding:.25rem .48rem; border-radius:999px; font-weight:750; white-space:nowrap; }
.badge.broken { color:var(--red); background:rgba(255,130,125,.1); }
.badge.at-risk { color:var(--amber); background:rgba(246,199,107,.1); }
.badge.unaffected, .badge.valid { color:var(--mint); background:rgba(120,245,198,.1); }
.badge.invalid { color:var(--red); background:rgba(255,130,125,.1); }
.badge.changed { color:var(--mint); background:rgba(120,245,198,.1); }
.plan-card { margin-bottom:.7rem; }
.plan-card.featured { border-color:#3D7E64; background:linear-gradient(135deg,#14201B,#111619 68%); }
.plan-top { display:flex; align-items:center; justify-content:space-between; gap:.8rem; }
.plan-title { font-size:.94rem; font-weight:750; letter-spacing:-.02em; }
.plan-summary { color:var(--muted); font-size:.77rem; line-height:1.5; margin:.45rem 0 .7rem; }
.plan-stats { display:flex; gap:1.2rem; flex-wrap:wrap; color:var(--muted); font-size:.75rem; }
.plan-stats strong { display:block; color:var(--text); font-size:.85rem; margin-top:.16rem; }
.callout { border:1px solid #365D4B; background:#112019; border-radius:14px; padding:1rem 1.1rem; margin-top:.6rem; }
.callout strong { color:var(--mint); font-size:.82rem; }
.callout p { color:#B9CFC4; font-size:.78rem; line-height:1.55; margin:.3rem 0 0; }
.draft-card { margin-bottom:.7rem; }
.draft-meta { display:flex; justify-content:space-between; color:var(--mint); font-size:.7rem; text-transform:uppercase; letter-spacing:.08em; font-weight:750; }
.draft-subject { font-size:.92rem; font-weight:700; margin:.55rem 0 .3rem; }
.draft-body { color:var(--muted); font-size:.8rem; line-height:1.5; }
.log-row { display:grid; grid-template-columns:22px 1fr; gap:.6rem; padding:.58rem 0; border-bottom:1px solid var(--line); }
.log-row:last-child { border:0; }
.log-number { color:var(--mint); font-size:.7rem; font-weight:800; }
.log-tool { color:var(--text); font-size:.75rem; font-weight:700; }
.log-detail { color:var(--muted); font-size:.72rem; line-height:1.35; margin-top:.14rem; }
.stButton > button[kind="primary"] { background:var(--mint); color:var(--bg); border:0; border-radius:10px; font-weight:750; min-height:44px; transition:transform .15s var(--ease-tap), box-shadow .2s ease; }
.stButton > button[kind="primary"]:hover { background:#9BFFD8; color:var(--bg); transform:translateY(-2px); box-shadow:0 8px 24px rgba(120,245,198,.13); }
.stButton > button[kind="primary"]:active { transform:scale(.98); }
.stButton > button[kind="primary"] p { color:var(--bg)!important; font-weight:750; }
.stButton > button:not([kind="primary"]) { background:var(--surface); color:var(--text); border:1px solid var(--line); border-radius:10px; min-height:44px; transition:transform .15s var(--ease-tap), border-color .2s ease; }
.stButton > button:not([kind="primary"]):hover { border-color:var(--mint); color:var(--mint); transform:translateY(-1px); }
[data-baseweb="input"] input, [data-baseweb="select"] > div { background:var(--surface)!important; color:var(--text)!important; border-color:var(--line)!important; }
[data-testid="stSlider"] [role="slider"] { background:var(--mint)!important; }
.stButton > button:focus-visible, [data-testid="stFileUploader"] button:focus-visible, [data-baseweb="input"] input:focus-visible, [data-baseweb="select"] [role="combobox"]:focus-visible, [data-testid="stSlider"] [role="slider"]:focus-visible { outline:3px solid var(--mint)!important; outline-offset:3px!important; }
[data-testid="stSlider"] [data-baseweb="slider"] > div > div { background-color:var(--mint); }
@keyframes rise { from { opacity:0; transform:translateY(8px); } to { opacity:1; transform:translateY(0); } }
@media(max-width:900px) { .block-container { padding:1.2rem 1rem 3rem; } .brand-meta { display:none; } .hero { padding:1.8rem 0 .7rem; } }
@media(max-width:600px) { .timeline-item { grid-template-columns:12px minmax(0,1fr); gap:.45rem .7rem; padding-bottom:.8rem; } .item-time { grid-column:2; text-align:left; white-space:normal; } .section-heading { align-items:flex-start; flex-wrap:wrap; gap:.25rem .7rem; } .impact-head, .plan-top { flex-wrap:wrap; } .hero h1 { font-size:2.15rem; } }
@media(prefers-reduced-motion:reduce) { *,*::before,*::after { animation-duration:.01ms!important; transition-duration:.01ms!important; scroll-behavior:auto!important; } }
</style>
""", unsafe_allow_html=True)


def heading(title: str, note: str = "") -> None:
    st.markdown(f'<div class="section-heading"><h2>{escape(title)}</h2><span>{escape(note)}</span></div>', unsafe_allow_html=True)


def badge(status: str) -> str:
    css = status.replace(" ", "-")
    return f'<span class="badge {css}">{escape(status)}</span>'


def timeline(report: Validation) -> None:
    rows = []
    for row in report.items.values():
        rows.append(f'<div class="timeline-item"><div class="dot {row.status.replace(" ", "-")}"></div><div><div class="item-name">{escape(row.title)}</div><div class="item-place">{escape(row.location)}' + (' · shifted' if row.changed else '') + f'</div></div><div class="item-time">{row.start:%d %b %H:%M %Z}<br>{row.end:%d %b %H:%M %Z}</div></div>')
    st.markdown('<div class="panel"><div class="panel-title">Current timeline</div>' + ''.join(rows) + '</div>', unsafe_allow_html=True)


def impact_list(report: Validation) -> None:
    rows = []
    for row in report.items.values():
        path = '<div class="cause-path">' + escape(' → '.join(row.cause_path)) + '</div>' if len(row.cause_path) > 1 and row.status != 'unaffected' else ''
        rows.append(f'<div class="impact-row"><div class="impact-head"><span>{escape(row.title)}</span>{badge(row.status)}</div><div class="impact-reason">{escape(row.reason)}' + (f' · slack {row.slack_minutes:+d} min' if row.slack_minutes is not None else '') + '</div>' + path + '</div>')
    st.markdown('<div class="panel"><div class="panel-title">Dependency diagnosis</div>' + ''.join(rows) + '</div>', unsafe_allow_html=True)


def plan_cards(run) -> None:
    for plan in run.plans:
        selected = run.selected and plan.plan_id == run.selected.plan_id
        css = 'plan-card featured' if selected else 'plan-card'
        stats = f'<div class="plan-stats"><span>Extra cost<strong>₹{plan.cost_delta_inr:,}</strong></span><span>Arrival shift<strong>{plan.arrival_delay_minutes} min</strong></span><span>Edits<strong>{plan.changes_count}</strong></span></div>'
        reason = '<div class="impact-reason">' + escape('; '.join(plan.violations)) + '</div>' if plan.violations else ''
        st.markdown(f'<div class="{css}"><div class="plan-top"><div class="plan-title">{escape(plan.title)}</div>{badge("valid" if plan.valid else "invalid")}</div><div class="plan-summary">{escape(plan.summary)}</div>{stats}{reason}</div>', unsafe_allow_html=True)
        if plan.valid and st.button('Review this plan' if not selected else 'Review recommended plan', key=f'review_{plan.plan_id}', use_container_width=True):
            st.session_state.review_plan_id = plan.plan_id


def provider_evidence(snapshot: InventorySnapshot, scenario, delay_minutes: int | None) -> None:
    heading("Provider evidence", "India travel search · indicative prices")
    if st.session_state.get("inventory_needs_analysis"):
        st.info("Provider results changed. Analyze the journey again if you want the model to read this evidence.")
    left, right = st.columns(2, gap="medium")
    with left:
        result = snapshot.flights
        created = f' · Provider created {result.provider_created_at:%d %b %H:%M UTC}' if result.provider_created_at else ''
        guidance = search_guidance(result)
        rows = [f'<div class="panel-title">Flights · {escape(result.mode)} mode · {escape(result.state.replace("_", " "))}</div><div class="footnote">Observed {result.observed_at:%d %b %H:%M UTC}{created} · {escape(result.message)}</div>']
        if guidance:
            rows.append(f'<div class="impact-reason">Next step: {escape(guidance)}</div>')
        checks = {row.offer.id: row for row in assess_flight_offers(scenario, delay_minutes, result)} if delay_minutes is not None else {}
        for offer in result.offers[:5]:
            check = checks.get(offer.id)
            expired = offer.expires_at is not None and offer.expires_at <= datetime.now(timezone.utc)
            proof = "Offer expired; search again" if expired else check.issue if check and check.issue else check.condition if check and check.condition else "Schedule fits known rules" if check and check.validation and check.validation.valid else "; ".join(check.validation.violations) if check and check.validation else "Analyze journey for schedule check"
            status = "at-risk" if expired or not check or check.issue or check.condition else "valid" if check.validation and check.validation.valid else "broken"
            rows.append(f'<div class="impact-row"><div class="impact-head"><span>{escape(", ".join(offer.operating_carriers))}</span><span class="badge {status}">{"expired" if expired else "timing fits" if status == "valid" else "timing blocked" if status == "broken" else "conditional" if check and check.condition else "unchecked"}</span></div><div class="impact-reason">{offer.departure:%d %b %H:%M %Z} → {offer.arrival:%d %b %H:%M %Z} · {offer.connections} connection(s) · {escape(offer.currency)} {escape(str(offer.amount))}</div><div class="footnote">{escape(proof)} · recheck price and seat before booking</div></div>')
        rows.append('<div class="footnote" style="margin-top:.65rem">A passing schedule check does not confirm the fare, rebooking cost, or a seat at checkout. Search prices are indicative.</div>')
        st.markdown('<div class="panel">' + ''.join(rows) + '</div>', unsafe_allow_html=True)
    with right:
        result = snapshot.hotels
        created = f' · Provider created {result.provider_created_at:%d %b %H:%M UTC}' if result.provider_created_at else ''
        guidance = search_guidance(result)
        rows = [f'<div class="panel-title">Hotels · {escape(result.mode)} mode · {escape(result.state.replace("_", " "))}</div><div class="footnote">Observed {result.observed_at:%d %b %H:%M UTC}{created} · {escape(result.message)}</div>']
        if guidance:
            rows.append(f'<div class="impact-reason">Next step: {escape(guidance)}</div>')
        for offer in result.offers[:5]:
            expired = offer.expires_at is not None and offer.expires_at <= datetime.now(timezone.utc)
            expiry = f' · result expires {offer.expires_at:%d %b %H:%M UTC}' if offer.expires_at else ''
            rows.append(f'<div class="impact-row"><div class="impact-head"><span>{escape(offer.name)}</span><span class="badge {"at-risk" if expired else "changed"}">{"expired" if expired else "result"}</span></div><div class="impact-reason">{offer.check_in_date:%d %b} – {offer.check_out_date:%d %b} · {escape(offer.currency)} {escape(str(offer.amount))}</div><div class="footnote">Search result only{expiry}</div></div>')
        rows.append('<div class="footnote" style="margin-top:.65rem">A room result does not verify a late check-in exception at the traveller’s existing hotel.</div>')
        st.markdown('<div class="panel">' + ''.join(rows) + '</div>', unsafe_allow_html=True)


scenario = load_scenario(DATA)
st.markdown('<div class="brand"><div class="brand-name"><span class="brand-mark">↗</span>TripShift</div><div class="brand-meta">Travel disruption control · simulated demo</div></div>', unsafe_allow_html=True)
st.markdown('<div class="hero"><div class="eyebrow">Journey recovery</div><h1>One change. A clearer way forward.</h1><p>Trace the consequences of a disrupted flight, compare checked recovery paths, and prepare the next move with full context.</p></div>', unsafe_allow_html=True)

defaults = {"ui_delay": 210, "ui_description": "", "ui_mode": MODES[0], "ui_provider": SETUP_PROVIDERS[0], "ui_setup_name": "Nagpur recovery"}
for key, value in defaults.items():
    st.session_state.setdefault(key, value)
if "pending_setup" in st.session_state:
    loaded = st.session_state.pop("pending_setup")
    st.session_state.ui_delay = loaded.delay_minutes
    st.session_state.ui_description = loaded.description
    st.session_state.ui_mode = loaded.mode
    st.session_state.ui_provider = loaded.provider
    st.session_state.ui_setup_name = loaded.name
    for key in ("run", "run_inputs", "run_error", "run_error_hint", "inventory", "review_plan_id"):
        st.session_state.pop(key, None)

input_a, input_b, input_c = st.columns([1.25, 1.55, 1.2], gap="medium")
with input_a:
    delay = st.slider("Flight arrival delay", min_value=0, max_value=360, step=15, format="%d min", key="ui_delay")
with input_b:
    natural_text = st.text_input("Or describe the disruption", placeholder="Flight delayed by 3 hours 30 minutes", max_chars=500, key="ui_description")
with input_c:
    shock = st.selectbox("Scenario mode", MODES, key="ui_mode")
    provider = st.selectbox("Model provider", SETUP_PROVIDERS, key="ui_provider", help="Auto tries Gemini, then Groq if needed.")

with st.expander("Save or open a demo setup", expanded=False):
    st.caption("Save the current inputs as a JSON file, then open it on another device. Keys, search results, and model outputs are never included.")
    st.text_input("Setup name", max_chars=80, key="ui_setup_name")
    try:
        saved_bytes = save_setup(SavedSetup(st.session_state.ui_setup_name, delay, natural_text, shock, provider))
    except ValueError as exc:
        st.warning(str(exc))
    else:
        st.download_button("Download setup", data=saved_bytes, file_name="tripshift-setup.json", mime="application/json", use_container_width=True)
    uploaded = st.file_uploader("Open a TripShift setup", type=["json"], key="ui_upload")
    if st.button("Load setup", disabled=uploaded is None, use_container_width=True):
        try:
            st.session_state.pending_setup = load_setup(uploaded.getvalue())
        except ValueError as exc:
            st.error(str(exc))
        else:
            st.rerun()

current_inputs = (delay, natural_text.strip(), shock, provider)
if st.session_state.get("run_inputs") not in (None, current_inputs):
    for key in ("run", "run_inputs", "run_error", "run_error_hint", "review_plan_id"):
        st.session_state.pop(key, None)
    st.info("Inputs changed. Analyze the journey again to see a current recommendation.")

run_col, offer_col, note_col = st.columns([1, 1.18, 2.35], gap="medium")
with run_col:
    analyze = st.button("Analyze journey", type="primary", use_container_width=True)
with offer_col:
    search_offers = st.button("Search India travel", use_container_width=True)
with note_col:
    st.markdown('<div class="footnote" style="padding-top:.7rem">Provider search is optional and read-only. If searched, the model can inspect that evidence, while recommendations remain checked against the simulated journey. No bookings or messages are sent.</div>', unsafe_allow_html=True)

if search_offers and scenario.inventory_search:
    load_dotenv(Path(__file__).parent / ".env", override=True)
    query = scenario.inventory_search
    inventory_client = IndiaTravelSearch(os.getenv("SERPAPI_API_KEY"))
    try:
        with st.spinner("Searching provider flights and hotels..."):
            flights = inventory_client.search_flights(query.origin_iata, query.destination_iata, query.departure_date)
            hotels = inventory_client.search_hotels(query.hotel_latitude, query.hotel_longitude, query.hotel_check_in, query.hotel_check_out, query.hotel_radius_km)
            st.session_state.inventory = InventorySnapshot(flights, hotels)
            st.session_state.inventory_needs_analysis = True
            for key in ("run", "run_inputs", "review_plan_id"):
                st.session_state.pop(key, None)
    finally:
        inventory_client.close()

if analyze:
    request = natural_text.strip() or f"The flight to Nagpur is delayed by {delay} minutes. Analyze the full journey and recommend a checked recovery."
    unavailable = {"flight-b"} if shock.startswith("Second shock") else {"flight-a", "flight-b", "late-checkin"} if shock.startswith("Impossible") else set()
    try:
        with st.spinner("Agent calling travel tools and checking plans..."):
            st.session_state.run = run_trip_agent(scenario, request, unavailable, provider.lower(), inventory=st.session_state.get("inventory"))
        st.session_state.active_shock = shock
        st.session_state.inventory_needs_analysis = False
        st.session_state.review_plan_id = st.session_state.run.selected.plan_id if st.session_state.run.selected else None
        st.session_state.run_error = None
        st.session_state.run_error_hint = None
        st.session_state.run_inputs = current_inputs
    except AgentWorkflowError as exc:
        st.session_state.run = None
        st.session_state.run_error = str(exc)
        st.session_state.run_error_hint = exc.recovery_hint

run = st.session_state.get("run")
snapshot = st.session_state.get("inventory")
if snapshot:
    provider_evidence(snapshot, scenario, run.delay_minutes if run else None)
if run is None:
    if st.session_state.get("run_error"):
        st.error(st.session_state.run_error)
        if st.session_state.get("run_error_hint"):
            st.info("Next step: " + st.session_state.run_error_hint)
    st.markdown('<div class="panel" style="margin-top:1.5rem"><div class="panel-title">Ready for analysis</div><div class="item-name">The model will inspect the journey, call travel tools, validate options, and prepare a fallback.</div><div class="footnote" style="margin-top:.55rem">Choose a provider and press Analyze journey. The demo uses simulated availability and waits for a model result before showing a recommendation.</div></div>', unsafe_allow_html=True)
    st.stop()

st.markdown(f'<div class="footnote" style="margin-top:.8rem">Model: {escape(run.provider.title())} · {escape(run.model)} · {len(run.trace)} observable tool steps</div>', unsafe_allow_html=True)
if st.session_state.get("active_shock", "").startswith("Second shock"):
    st.info("Second shock injected: the lower-cost replacement flight is unavailable. The agent checked the remaining plans and selected the next valid recovery.")
elif st.session_state.get("active_shock", "").startswith("Impossible"):
    st.info("Impossible-case demo: every replacement or exception is unavailable. The agent must show blockers instead of recommending a plan.")
broken_count = sum(row.status == "broken" for row in run.impact.items.values())
risk_count = sum(row.status == "at risk" for row in run.impact.items.values())
metrics = st.columns(4, gap="medium")
metric_data = [("Disruption", f"+{run.delay_minutes} min", "arrival delay"), ("Broken", str(broken_count), "hard rule conflicts"), ("At risk", str(risk_count), "thin buffer / dependency"), ("Valid recoveries", str(sum(p.valid for p in run.plans)), "checked against fixture")]
for col, (label, value, note) in zip(metrics, metric_data):
    with col:
        st.markdown(f'<div class="panel"><div class="panel-title">{escape(label)}</div><div class="hero-metric">{escape(value)}</div><div class="footnote">{escape(note)}</div></div>', unsafe_allow_html=True)

left, middle, right = st.columns([1.02, 1.05, 1.18], gap="medium")
with left:
    heading("Journey", "After disruption")
    timeline(run.impact)
with middle:
    heading("Impact", "Rule-backed diagnosis")
    impact_list(run.impact)
with right:
    heading("Recovery options", "Validated before recommendation")
    plan_cards(run)
    if run.selected:
        fallback = f'<strong>Recovery Ladder</strong><p>Primary: {escape(run.selected.title)}. Next candidate: {escape(run.fallback.title)}. If conditions change, analyze again before acting.</p>' if run.fallback else '<strong>Recovery Ladder</strong><p>No checked fallback is available in this scenario snapshot.</p>'
        st.markdown(f'<div class="callout">{fallback}</div>', unsafe_allow_html=True)
    else:
        st.markdown('<div class="callout"><strong>No feasible plan</strong><p>Every available candidate violates a hard rule or requires an unavailable option. Review the blockers above and resolve them with a human.</p></div>', unsafe_allow_html=True)

reviewed = next((p for p in run.plans if p.plan_id == st.session_state.get("review_plan_id") and p.valid), run.selected)
if reviewed:
    heading("Selected plan", "Simulation proof")
    diff_rows = []
    for row in reviewed.items.values():
        if row.changed:
            diff_rows.append(f'<div class="impact-row"><div class="impact-head"><span>{escape(row.title)}</span>{badge("changed" if row.status == "unaffected" else row.status)}</div><div class="impact-reason">{row.original_start:%d %b %H:%M %Z} → {row.start:%d %b %H:%M %Z} · {escape(row.reason)}</div></div>')
    st.markdown(f'<div class="panel"><div class="panel-title">{escape(reviewed.title)} · all hard checks passed</div>' + ''.join(diff_rows) + '<div class="footnote" style="margin-top:.7rem">Valid only against this simulated snapshot; external availability and stakeholder acceptance remain unconfirmed.</div></div>', unsafe_allow_html=True)
    if run.selection_reason and reviewed.plan_id == (run.selected.plan_id if run.selected else None):
        st.markdown(f'<div class="footnote" style="padding:.45rem 0">Model choice: {escape(run.selection_reason)}</div>', unsafe_allow_html=True)

bottom_l, bottom_r = st.columns([1.45, 1], gap="medium")
with bottom_l:
    heading("Messages", "Drafts for human review")
    messages = draft_messages(run.impact, reviewed)
    if not messages:
        st.markdown('<div class="panel"><div class="footnote">No stakeholder update is needed for this checked plan.</div></div>', unsafe_allow_html=True)
    for msg in messages:
        st.markdown(f'<div class="draft-card"><div class="draft-meta"><span>{escape(msg["recipient"])}</span><span>{escape(msg["status"])}</span></div><div class="draft-subject">{escape(msg["subject"])}</div><div class="draft-body">{escape(msg["body"])}</div></div>', unsafe_allow_html=True)
with bottom_r:
    heading("Agent action log", "Observable steps")
    log_html = ''.join(f'<div class="log-row"><div class="log-number">{event.step:02d}</div><div><div class="log-tool">{escape(event.tool.replace("_", " ").title())}</div><div class="log-detail">{escape(event.detail)}</div></div></div>' for event in run.trace)
    st.markdown('<div class="panel">' + log_html + '</div>', unsafe_allow_html=True)

st.markdown('<div class="footnote" style="text-align:center;padding-top:2rem">TripShift · TECHNOVA ’26 · Simulated plans and optional provider evidence · No bookings or messages sent</div>', unsafe_allow_html=True)
