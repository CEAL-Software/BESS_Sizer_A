import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import plotly.express as px
from plotly.subplots import make_subplots
import anthropic
import json
import os

# ── Page config ──────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="BESS Sizing Tool — Mavuno Foods",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Custom CSS ────────────────────────────────────────────────────────────────
st.markdown("""
<style>
    .main-header {
        background: linear-gradient(135deg, #1a3c5e 0%, #2e7d32 100%);
        padding: 1.5rem 2rem;
        border-radius: 10px;
        margin-bottom: 1.5rem;
        color: white;
    }
    .main-header h1 { margin: 0; font-size: 1.8rem; }
    .main-header p  { margin: 0.3rem 0 0 0; opacity: 0.85; font-size: 0.95rem; }

    .metric-card {
        background: #f8f9fa;
        border: 1px solid #e0e0e0;
        border-radius: 8px;
        padding: 1rem;
        text-align: center;
    }
    .metric-card .label { font-size: 0.8rem; color: #666; text-transform: uppercase; letter-spacing: 0.05em; }
    .metric-card .value { font-size: 1.6rem; font-weight: 700; color: #1a3c5e; }
    .metric-card .unit  { font-size: 0.85rem; color: #888; }

    .scenario-card {
        border-radius: 10px;
        padding: 1.4rem;
        margin-bottom: 0.8rem;
        border: 2px solid transparent;
    }
    .scenario-conservative { background: #e8f5e9; border-color: #66bb6a; }
    .scenario-recommended  { background: #e3f2fd; border-color: #1976d2; }
    .scenario-aggressive   { background: #fff3e0; border-color: #f57c00; }
    .scenario-card h3 { margin: 0 0 0.8rem 0; }
    .scenario-grid { display: grid; grid-template-columns: repeat(2, 1fr); gap: 0.5rem; }
    .scenario-stat .s-label { font-size: 0.75rem; color: #555; }
    .scenario-stat .s-value { font-size: 1.1rem; font-weight: 600; }

    .reasoning-box {
        background: #fafafa;
        border-left: 4px solid #1976d2;
        padding: 0.8rem 1rem;
        border-radius: 0 6px 6px 0;
        font-size: 0.9rem;
        color: #333;
        margin-top: 0.8rem;
    }

    .stTabs [data-baseweb="tab-list"] { gap: 8px; }
    .stTabs [data-baseweb="tab"] { border-radius: 6px 6px 0 0; padding: 0.4rem 1rem; }
</style>
""", unsafe_allow_html=True)

# ── Data loading ──────────────────────────────────────────────────────────────
XLSX_PATH = os.path.join(os.path.dirname(__file__), "mavuno_foods_bess_challenge.xlsx")

@st.cache_data
def load_data():
    df_hourly = pd.read_excel(XLSX_PATH, sheet_name="Hourly Data")
    df_monthly = pd.read_excel(XLSX_PATH, sheet_name="Monthly Billing")
    df_monthly = df_monthly.dropna(subset=["Month"])
    return df_hourly, df_monthly

df_hourly, df_monthly = load_data()

# ── Sidebar — Inputs ──────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("## ⚙️ Tool Inputs")
    st.caption("Pre-filled from dataset — adjust as needed")

    st.markdown("**Load & Tariff**")
    avg_monthly_kwh       = st.number_input("Avg Monthly Consumption (kWh)", value=68900, step=100)
    peak_demand_kva       = st.number_input("Avg Peak Demand (kVA)", value=100, step=1)
    contracted_kva        = st.number_input("Contracted Power (kVA)", value=110, step=1)
    tariff_peak           = st.number_input("Peak Tariff (KES/kWh)", value=25.0, step=0.1)
    tariff_offpeak        = st.number_input("Off-peak Tariff (KES/kWh)", value=13.7, step=0.1)
    demand_charge         = st.number_input("Demand Charge (KES/kVA/month)", value=850, step=10)

    st.markdown("**PV System**")
    pv_kwp                = st.number_input("Installed PV (kWp)", value=200, step=5)
    avg_daily_pv          = st.number_input("Avg Daily PV Generation (kWh)", value=200, step=5)
    avg_daily_surplus     = st.number_input("Avg Daily PV Surplus (kWh)", value=70, step=5)
    feed_in_tariff        = st.number_input("Feed-in Tariff (KES/kWh)", value=5.0, step=0.5)

    st.markdown("**Project Constraints**")
    critical_load_kw      = st.number_input("Critical Backup Load (kW)", value=45, step=1)
    backup_hours          = st.number_input("Backup Autonomy Target (hrs)", value=2, step=1)
    max_payback           = st.number_input("Max Acceptable Payback (years)", value=8, step=1)
    bess_cost_eur_kwh     = st.number_input("BESS Cost (EUR/kWh installed)", value=180, step=5)
    exchange_rate         = st.number_input("Exchange Rate (KES/EUR)", value=129.5, step=0.5)
    project_lifetime      = st.number_input("Project Lifetime (years)", value=15, step=1)
    tariff_escalation_pct = st.number_input("Annual Tariff Escalation (%)", value=6.0, step=0.5)

    st.markdown("---")
    api_key = st.text_input("Anthropic API Key", type="password", help="Your key is never stored")

# ── Header ────────────────────────────────────────────────────────────────────
st.markdown("""
<div class="main-header">
  <h1>⚡ BESS Sizing Tool</h1>
  <p>Mavuno Foods Ltd · Nairobi Industrial Area · 200 kWp Solar + Battery Storage Analysis</p>
</div>
""", unsafe_allow_html=True)

# ── Derived stats (used across tabs) ─────────────────────────────────────────
bess_cost_kes_kwh = bess_cost_eur_kwh * exchange_rate

# Hourly computed
df_h = df_hourly.copy()
df_h["Net Load (kW)"]     = df_h["Load (kW)"] - df_h["PV Gen (kW)"]
df_h["Grid Import (kW)"]  = df_h["Net Load (kW)"].clip(lower=0)
df_h["PV Surplus (kW)"]   = (-df_h["Net Load (kW)"]).clip(lower=0)
df_h["is_peak"]           = df_h["Hour"].between(6, 21)
df_h["Hour Label"]        = df_h["Time"].astype(str)

avg_hourly_load = df_h.groupby("Hour")["Load (kW)"].mean()
avg_hourly_pv   = df_h.groupby("Hour")["PV Gen (kW)"].mean()
avg_hourly_surplus = df_h.groupby("Hour")["PV Surplus (kW)"].mean()
avg_hourly_import  = df_h.groupby("Hour")["Grid Import (kW)"].mean()

daily_surplus_kwh = df_h.groupby("Day Type")["PV Surplus (kW)"].sum()
peak_demand_by_day = df_h[df_h["is_peak"]].groupby("Day Type")["Load (kW)"].max()

# Monthly totals
total_annual_bill = df_monthly["Total Bill (KES)"].sum()
total_diesel      = df_monthly["Diesel (KES)"].sum()
total_demand_bill = df_monthly["Demand Bill (KES)"].sum()
total_pv_surplus_kwh = (df_monthly["PV Gen (kWh)"] - df_monthly["PV Self-use (kWh)"]).sum()

# Key metrics row
c1, c2, c3, c4, c5 = st.columns(5)
def metric_card(col, label, value, unit):
    col.markdown(f"""
    <div class="metric-card">
      <div class="label">{label}</div>
      <div class="value">{value}</div>
      <div class="unit">{unit}</div>
    </div>""", unsafe_allow_html=True)

metric_card(c1, "Annual Energy Bill",   f"KES {total_annual_bill/1e6:.1f}M", "per year")
metric_card(c2, "Annual Diesel Cost",   f"KES {total_diesel/1e6:.1f}M",      "per year")
metric_card(c3, "Demand Charges",       f"KES {total_demand_bill/1e6:.1f}M", "per year")
metric_card(c4, "Wasted PV (annual)",   f"{total_pv_surplus_kwh:,.0f} kWh",  "exported @ KES 5")
metric_card(c5, "Tariff Spread",        f"KES {tariff_peak - tariff_offpeak:.1f}",  "/kWh arbitrage")

st.markdown("<br>", unsafe_allow_html=True)

# ── Tabs ──────────────────────────────────────────────────────────────────────
tab1, tab2, tab3 = st.tabs(["📊 Load Profile Analysis", "📅 Monthly Billing", "🔋 BESS Recommendation"])

# ════════════════════════════════════════════════════════════════════════════
# TAB 1 — Load Profile
# ════════════════════════════════════════════════════════════════════════════
with tab1:
    st.subheader("Hourly Load vs PV Generation (weekly average)")

    day_filter = st.selectbox(
        "Filter by day", 
        ["All Days (Average)"] + list(df_h["Day Type"].unique()),
        index=0
    )

    if day_filter == "All Days (Average)":
        plot_load    = df_h.groupby("Hour")["Load (kW)"].mean()
        plot_pv      = df_h.groupby("Hour")["PV Gen (kW)"].mean()
        plot_surplus = df_h.groupby("Hour")["PV Surplus (kW)"].mean()
        plot_import  = df_h.groupby("Hour")["Grid Import (kW)"].mean()
    else:
        sub = df_h[df_h["Day Type"] == day_filter]
        plot_load    = sub.groupby("Hour")["Load (kW)"].mean()
        plot_pv      = sub.groupby("Hour")["PV Gen (kW)"].mean()
        plot_surplus = sub.groupby("Hour")["PV Surplus (kW)"].mean()
        plot_import  = sub.groupby("Hour")["Grid Import (kW)"].mean()

    hours = list(range(24))
    hour_labels = [f"{h:02d}:00" for h in hours]

    fig = make_subplots(
        rows=2, cols=1,
        shared_xaxes=True,
        row_heights=[0.65, 0.35],
        vertical_spacing=0.08,
        subplot_titles=("Load vs PV Generation", "Grid Import & PV Surplus")
    )

    fig.add_trace(go.Scatter(
        x=hour_labels, y=plot_load.values,
        name="Load (kW)", line=dict(color="#1a3c5e", width=2.5),
        fill=None
    ), row=1, col=1)

    fig.add_trace(go.Scatter(
        x=hour_labels, y=plot_pv.values,
        name="PV Generation (kW)", line=dict(color="#f9a825", width=2.5),
        fill="tonexty", fillcolor="rgba(249,168,37,0.08)"
    ), row=1, col=1)

    # Shade peak hours
    fig.add_vrect(x0="06:00", x1="22:00", fillcolor="rgba(255,152,0,0.06)",
                  line_width=0, annotation_text="Peak hours", annotation_position="top left",
                  row=1, col=1)

    fig.add_trace(go.Bar(
        x=hour_labels, y=plot_import.values,
        name="Grid Import (kW)", marker_color="#e53935", opacity=0.75
    ), row=2, col=1)

    fig.add_trace(go.Bar(
        x=hour_labels, y=plot_surplus.values,
        name="PV Surplus (kW)", marker_color="#43a047", opacity=0.75
    ), row=2, col=1)

    fig.update_layout(
        height=550, hovermode="x unified",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        margin=dict(l=0, r=0, t=40, b=0),
        barmode="overlay"
    )
    fig.update_yaxes(title_text="kW", row=1, col=1)
    fig.update_yaxes(title_text="kW", row=2, col=1)
    st.plotly_chart(fig, use_container_width=True)

    # Surplus & demand stats per day
    st.markdown("#### Daily PV Surplus & Peak Demand by Day Type")
    col_a, col_b = st.columns(2)

    with col_a:
        fig2 = px.bar(
            x=daily_surplus_kwh.index, y=daily_surplus_kwh.values,
            labels={"x": "Day", "y": "Daily Surplus (kWh)"},
            color=daily_surplus_kwh.values,
            color_continuous_scale="Greens",
            title="PV Surplus by Day of Week"
        )
        fig2.update_coloraxes(showscale=False)
        fig2.update_layout(margin=dict(l=0, r=0, t=40, b=0), height=320)
        st.plotly_chart(fig2, use_container_width=True)

    with col_b:
        fig3 = px.bar(
            x=peak_demand_by_day.index, y=peak_demand_by_day.values,
            labels={"x": "Day", "y": "Peak Load (kW)"},
            color=peak_demand_by_day.values,
            color_continuous_scale="Reds",
            title="Peak Demand by Day of Week"
        )
        fig3.update_coloraxes(showscale=False)
        fig3.update_layout(margin=dict(l=0, r=0, t=40, b=0), height=320)
        st.plotly_chart(fig3, use_container_width=True)

    # Optimal charge/discharge window summary
    surplus_hours   = sorted(avg_hourly_surplus[avg_hourly_surplus > 5].index.tolist())
    highload_hours  = sorted(avg_hourly_import[avg_hourly_import > avg_hourly_import.mean()].index.tolist())

    st.markdown("#### Derived Charge / Discharge Windows")
    w1, w2, w3 = st.columns(3)
    w1.info(f"**⬆️ Optimal Charge Window**\n\nHours {surplus_hours[0]:02d}:00 – {surplus_hours[-1]:02d}:00  \nAbsorb surplus PV generation")
    w2.warning(f"**⬇️ Peak Discharge Window**\n\nHours {highload_hours[0]:02d}:00 – {highload_hours[-1]:02d}:00  \nShave peak demand & reduce grid import")
    w3.success(f"**🌙 Off-peak Charge Window**\n\n00:00 – 06:00  \nCharge at {tariff_offpeak} KES/kWh, discharge at {tariff_peak} KES/kWh")


# ════════════════════════════════════════════════════════════════════════════
# TAB 2 — Monthly Billing
# ════════════════════════════════════════════════════════════════════════════
with tab2:
    st.subheader("Monthly Energy & Cost Breakdown")

    months = df_monthly["Month"].tolist()

    fig4 = go.Figure()
    fig4.add_trace(go.Bar(x=months, y=df_monthly["Energy Bill (KES)"], name="Energy Charges", marker_color="#1565c0"))
    fig4.add_trace(go.Bar(x=months, y=df_monthly["Demand Bill (KES)"], name="Demand Charges", marker_color="#7b1fa2"))
    fig4.add_trace(go.Bar(x=months, y=df_monthly["Diesel (KES)"],      name="Diesel Costs",  marker_color="#c62828"))
    fig4.add_trace(go.Bar(x=months, y=df_monthly["Fixed (KES)"],       name="Fixed Charges", marker_color="#37474f"))
    fig4.update_layout(
        barmode="stack", height=380, hovermode="x unified",
        yaxis_title="KES", legend=dict(orientation="h", yanchor="bottom", y=1.02),
        margin=dict(l=0, r=0, t=10, b=0)
    )
    st.plotly_chart(fig4, use_container_width=True)

    col_x, col_y = st.columns(2)
    with col_x:
        fig5 = go.Figure()
        fig5.add_trace(go.Scatter(x=months, y=df_monthly["PV Gen (kWh)"],      name="PV Generated", line=dict(color="#f9a825", width=2)))
        fig5.add_trace(go.Scatter(x=months, y=df_monthly["PV Self-use (kWh)"], name="PV Self-Used",  line=dict(color="#43a047", width=2)))
        fig5.add_trace(go.Scatter(
            x=months,
            y=(df_monthly["PV Gen (kWh)"] - df_monthly["PV Self-use (kWh)"]),
            name="Surplus (exported)", fill="tozeroy", line=dict(color="#ef9a9a", width=1.5)
        ))
        fig5.update_layout(height=320, yaxis_title="kWh", hovermode="x unified", margin=dict(l=0, r=0, t=10, b=0))
        st.plotly_chart(fig5, use_container_width=True)

    with col_y:
        fig6 = go.Figure()
        fig6.add_trace(go.Scatter(x=months, y=df_monthly["Peak Demand (kVA)"],
                                  name="Peak Demand", line=dict(color="#e53935", width=2.5),
                                  fill="tozeroy", fillcolor="rgba(229,57,53,0.1)"))
        fig6.add_hline(y=contracted_kva, line_dash="dash", line_color="#1a3c5e",
                       annotation_text=f"Contracted: {contracted_kva} kVA")
        fig6.update_layout(height=320, yaxis_title="kVA", margin=dict(l=0, r=0, t=10, b=0))
        st.plotly_chart(fig6, use_container_width=True)

    # Summary table
    st.markdown("#### Monthly Billing Summary")
    display_cols = ["Month", "Total Cons (kWh)", "PV Gen (kWh)", "Grid Import (kWh)", "Peak Demand (kVA)", "Total Bill (KES)"]
    st.dataframe(
        df_monthly[display_cols].set_index("Month").style.format({
            "Total Cons (kWh)": "{:,.0f}",
            "PV Gen (kWh)":     "{:,.0f}",
            "Grid Import (kWh)":"{:,.0f}",
            "Peak Demand (kVA)":"{:.0f}",
            "Total Bill (KES)": "KES {:,.0f}",
        }),
        use_container_width=True
    )


# ════════════════════════════════════════════════════════════════════════════
# TAB 3 — BESS Recommendation
# ════════════════════════════════════════════════════════════════════════════
with tab3:
    st.subheader("AI-Powered BESS Sizing Recommendation")

    st.markdown("""
    The analysis below is generated by Claude using your dataset inputs plus the hourly profile statistics.
    Three scenarios are returned: **Conservative** (backup focus), **Recommended** (balanced), and **Aggressive** (maximum savings).
    """)

    def build_prompt():
        surplus_window_str  = f"{surplus_hours[0]:02d}:00–{surplus_hours[-1]:02d}:00"
        discharge_window_str = f"{highload_hours[0]:02d}:00–{highload_hours[-1]:02d}:00"
        daily_avg_surplus   = df_h.groupby("Day")["PV Surplus (kW)"].sum().mean()
        daily_avg_load      = df_h.groupby("Day")["Load (kW)"].sum().mean() / 24

        return f"""You are an expert energy storage engineer specialising in commercial & industrial (C&I) battery energy storage systems (BESS) in sub-Saharan Africa.

Design a BESS solution for Mavuno Foods Ltd, a food processing company in Nairobi's Industrial Area.

## Site Profile
- 200 kWp rooftop mono-PERC solar PV (south-facing, 15° tilt), installed Nov 2022
- Grid: 33kV/415V KPLC supply, SC5 tariff category
- Operating hours: Mon–Sat 05:00–22:00, reduced Sunday 06:00–14:00

## Load Data (from 168-hour weekly profile)
- Average daily consumption: {avg_monthly_kwh/30:.0f} kWh/day
- Average hourly load: {daily_avg_load:.1f} kW
- Peak load (peak hours): ~{peak_demand_by_day.max():.0f} kW
- Off-peak baseload (00:00–05:00): ~42 kW

## PV & Surplus Analysis
- Average daily PV generation: {avg_daily_pv} kWh
- Average daily PV surplus (currently wasted/exported): {avg_daily_surplus} kWh (~35% of generation)
- Optimal BESS charge window (PV surplus): {surplus_window_str}
- Peak demand discharge window: {discharge_window_str}
- Off-peak grid charge opportunity: 00:00–06:00

## Tariff Structure (KPLC SC5)
- Peak tariff (06:00–22:00): KES {tariff_peak}/kWh
- Off-peak tariff (22:00–06:00): KES {tariff_offpeak}/kWh
- Tariff arbitrage spread: KES {tariff_peak - tariff_offpeak:.1f}/kWh
- Demand charge: KES {demand_charge}/kVA/month
- Feed-in tariff (current): KES {feed_in_tariff}/kWh (very low — storage is preferred)
- Annual tariff escalation: {tariff_escalation_pct}%

## Financial Context
- Current annual electricity bill: KES {total_annual_bill:,.0f}
- Annual diesel generator costs: KES {total_diesel:,.0f}
- Annual demand charges alone: KES {total_demand_bill:,.0f}
- BESS installed cost reference: EUR {bess_cost_eur_kwh}/kWh (LFP, installed) = KES {bess_cost_kes_kwh:,.0f}/kWh
- Maximum acceptable payback: {max_payback} years
- Project lifetime: {project_lifetime} years

## Backup Requirements
- Critical load (cold storage + controls): {critical_load_kw} kW — must remain powered
- Minimum backup autonomy: {backup_hours} hours during grid outages

## Technical Assumptions (use these)
- LFP chemistry
- Round-trip efficiency: 90%
- Usable depth of discharge (DoD): 80%
- Cycle lifetime: 6,000 cycles
- O&M: 1% of CapEx per year

## Your Task
Design three BESS scenarios. For each, provide:
1. Rated power (kW AC)
2. Rated energy capacity (kWh)
3. Usable energy (= capacity × DoD)
4. Primary use cases (list the 2–3 top value drivers)
5. Annual savings breakdown (KES): solar self-consumption gain, peak tariff arbitrage, demand charge reduction, diesel avoided
6. Total annual savings (KES)
7. CapEx (KES)
8. Simple payback (years)
9. NPV over project lifetime at 6% discount rate (KES)
10. Brief engineering reasoning (2–3 sentences explaining the sizing logic)

Return your answer as a JSON object with this exact structure:
{{
  "scenarios": [
    {{
      "name": "Conservative",
      "subtitle": "Backup & Solar Capture Focus",
      "power_kw": <int>,
      "energy_kwh": <int>,
      "usable_kwh": <float>,
      "use_cases": ["...", "...", "..."],
      "savings": {{
        "solar_self_consumption_kes": <int>,
        "tariff_arbitrage_kes": <int>,
        "demand_reduction_kes": <int>,
        "diesel_avoided_kes": <int>,
        "total_kes": <int>
      }},
      "capex_kes": <int>,
      "payback_years": <float>,
      "npv_kes": <int>,
      "reasoning": "..."
    }},
    {{ "name": "Recommended", ... }},
    {{ "name": "Aggressive", ... }}
  ],
  "overall_recommendation": "2–3 sentences on which scenario you recommend for Mavuno Foods and why."
}}

Return ONLY the JSON object. No markdown fences, no preamble."""

    if "bess_result" not in st.session_state:
        st.session_state.bess_result = None
    if "bess_error" not in st.session_state:
        st.session_state.bess_error = None

    col_btn, col_info = st.columns([1, 3])
    with col_btn:
        run_btn = st.button("🔋 Run BESS Analysis", type="primary", use_container_width=True)

    if run_btn:
        key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")
        if not key:
            st.error("Please enter your Anthropic API key in the sidebar.")
        else:
            with st.spinner("Claude is sizing the BESS system…"):
                try:
                    client = anthropic.Anthropic(api_key=key)
                    message = client.messages.create(
                        model="claude-sonnet-4-6",
                        max_tokens=2048,
                        messages=[{"role": "user", "content": build_prompt()}]
                    )
                    raw = message.content[0].text.strip()
                    # Strip markdown code fences if present
                    if raw.startswith("```"):
                        raw = raw.split("```")[1]
                        if raw.startswith("json"):
                            raw = raw[4:]
                    st.session_state.bess_result = json.loads(raw)
                    st.session_state.bess_error  = None
                except json.JSONDecodeError as e:
                    st.session_state.bess_error = f"JSON parse error: {e}\n\nRaw response:\n{raw}"
                except Exception as e:
                    st.session_state.bess_error = str(e)

    if st.session_state.bess_error:
        st.error(st.session_state.bess_error)

    if st.session_state.bess_result:
        result = st.session_state.bess_result
        scenarios = result.get("scenarios", [])

        # ── Scenario cards ────────────────────────────────────────────────
        style_map = {
            "Conservative": ("scenario-conservative", "🟢"),
            "Recommended":  ("scenario-recommended",  "🔵"),
            "Aggressive":   ("scenario-aggressive",   "🟠"),
        }

        cols = st.columns(len(scenarios))
        for col, sc in zip(cols, scenarios):
            css_class, emoji = style_map.get(sc["name"], ("scenario-recommended", "⚡"))
            savings = sc.get("savings", {})
            with col:
                st.markdown(f"""
<div class="scenario-card {css_class}">
  <h3>{emoji} {sc['name']}</h3>
  <p style="margin:0 0 0.8rem 0; font-size:0.85rem; color:#555">{sc.get('subtitle','')}</p>
  <div class="scenario-grid">
    <div class="scenario-stat"><div class="s-label">Power</div><div class="s-value">{sc['power_kw']} kW</div></div>
    <div class="scenario-stat"><div class="s-label">Capacity</div><div class="s-value">{sc['energy_kwh']} kWh</div></div>
    <div class="scenario-stat"><div class="s-label">Usable</div><div class="s-value">{sc['usable_kwh']:.0f} kWh</div></div>
    <div class="scenario-stat"><div class="s-label">Payback</div><div class="s-value">{sc['payback_years']:.1f} yrs</div></div>
  </div>
  <hr style="margin:0.8rem 0; border-color: rgba(0,0,0,0.1)">
  <div class="s-label">Annual Savings</div>
  <div style="font-size:1.25rem; font-weight:700; color:#1a3c5e">KES {savings.get('total_kes',0):,.0f}</div>
  <div style="font-size:0.8rem; color:#555; margin-top:0.3rem">CapEx: KES {sc['capex_kes']:,.0f}</div>
  <div class="reasoning-box">{sc['reasoning']}</div>
</div>
                """, unsafe_allow_html=True)

        # ── Savings waterfall chart ────────────────────────────────────────
        st.markdown("#### Savings Breakdown by Scenario")

        saving_labels = ["Solar Self-Consumption", "Tariff Arbitrage", "Demand Reduction", "Diesel Avoided"]
        saving_keys   = ["solar_self_consumption_kes", "tariff_arbitrage_kes", "demand_reduction_kes", "diesel_avoided_kes"]
        colors        = ["#43a047", "#1976d2", "#7b1fa2", "#e53935"]

        fig_sav = go.Figure()
        for label, key, color in zip(saving_labels, saving_keys, colors):
            values = [sc["savings"].get(key, 0) for sc in scenarios]
            fig_sav.add_trace(go.Bar(
                name=label,
                x=[sc["name"] for sc in scenarios],
                y=values,
                marker_color=color,
                text=[f"KES {v:,.0f}" for v in values],
                textposition="inside",
                textfont=dict(color="white", size=11)
            ))
        fig_sav.update_layout(
            barmode="stack", height=380,
            yaxis_title="Annual Savings (KES)",
            legend=dict(orientation="h", yanchor="bottom", y=1.02),
            margin=dict(l=0, r=0, t=10, b=0)
        )
        st.plotly_chart(fig_sav, use_container_width=True)

        # ── Payback & NPV comparison ───────────────────────────────────────
        col_p, col_n = st.columns(2)
        with col_p:
            fig_pb = go.Figure(go.Bar(
                x=[sc["name"] for sc in scenarios],
                y=[sc["payback_years"] for sc in scenarios],
                marker_color=["#43a047", "#1976d2", "#f57c00"],
                text=[f"{sc['payback_years']:.1f} yrs" for sc in scenarios],
                textposition="outside"
            ))
            fig_pb.add_hline(y=max_payback, line_dash="dash", line_color="#c62828",
                             annotation_text=f"Max acceptable: {max_payback} yrs")
            fig_pb.update_layout(height=320, yaxis_title="Years", margin=dict(l=0,r=0,t=10,b=0),
                                 title="Simple Payback Period")
            st.plotly_chart(fig_pb, use_container_width=True)

        with col_n:
            npv_vals = [sc.get("npv_kes", 0) for sc in scenarios]
            fig_npv = go.Figure(go.Bar(
                x=[sc["name"] for sc in scenarios],
                y=npv_vals,
                marker_color=["#43a047" if v >= 0 else "#c62828" for v in npv_vals],
                text=[f"KES {v/1e6:.1f}M" for v in npv_vals],
                textposition="outside"
            ))
            fig_npv.add_hline(y=0, line_color="#333", line_width=1)
            fig_npv.update_layout(height=320, yaxis_title="KES", margin=dict(l=0,r=0,t=10,b=0),
                                  title=f"NPV over {project_lifetime} Years (6% discount)")
            st.plotly_chart(fig_npv, use_container_width=True)

        # ── Overall recommendation ────────────────────────────────────────
        rec = result.get("overall_recommendation", "")
        if rec:
            st.success(f"**💡 Claude's Recommendation:** {rec}")

        # ── Raw JSON expander ─────────────────────────────────────────────
        with st.expander("View raw JSON response"):
            st.json(result)
