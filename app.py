from __future__ import annotations
import streamlit as st
import pandas as pd
import altair as alt
import io
from datetime import date, timedelta
from logic import (
    Config, StageParams, SoilParams, NDVI2Kc,
    decide_T2, decide_T3, decide_T4_strict, PLOTS
)
from data_io import append_rows, read_sheet, ensure_headers
from emailer import send_email_with_pdf

st.set_page_config(page_title="Smart Irrigation – Flat", layout="wide")
ensure_headers(st.secrets["gsheets"]["daily_inputs_ws"],
               ["date","plot","theta_vwc","rain_obs","rain_fcst_24h","ndvi","eto","notes"])
ensure_headers(st.secrets["gsheets"]["decisions_ws"],
               ["date","plot","treatment","decision","reason","Dr","RAW","theta","theta_trigger","ndvi","Kc","rain_fcst","irr_mm","irr_L"])
ensure_headers(st.secrets["gsheets"]["plant_ws"],
               ["date","plot","plant_id","height_cm"])
ensure_headers(st.secrets["gsheets"]["metadata_ws"],
               ["key","value","timestamp"])

st.title("🌿 Smart Irrigation — Spinach (Utsunomiya) – Flat App")
tab_dashboard, tab_admin, tab_analytics, tab_reports = st.tabs(
    ["🏠 Dashboard", "⚙️ Admin", "📊 Analytics", "🧾 Reports"]
)

with tab_dashboard:
    st.subheader("📝 Daily Inputs & Decisions")
    TRANSPLANT = date(2025, 11, 6)
    cfg = Config(transplant_date=TRANSPLANT)

    st.sidebar.header("Runtime configuration")
    cfg.efficiency = st.sidebar.slider("Application efficiency η", 0.5, 0.98, cfg.efficiency, 0.01)
    cfg.soil.theta_fc = st.sidebar.number_input("θ_fc (m³/m³)", 0.10, 0.60, cfg.soil.theta_fc, 0.01)
    cfg.soil.theta_wp = st.sidebar.number_input("θ_wp (m³/m³)", 0.02, 0.40, cfg.soil.theta_wp, 0.01)
    cfg.soil.alpha   = st.sidebar.slider("α for θ_trigger", 0.2, 0.8, cfg.soil.alpha, 0.05)
    cfg.ndvi2kc.a    = st.sidebar.number_input("NDVI→Kc a", 0.0, 3.0, cfg.ndvi2kc.a, 0.05)
    cfg.ndvi2kc.b    = st.sidebar.number_input("NDVI→Kc b", -0.5, 1.0, cfg.ndvi2kc.b, 0.05)
    cfg.ndvi2kc.active_gate = st.sidebar.slider("Active canopy gate (Kc)", 0.5, 1.2, cfg.ndvi2kc.active_gate, 0.01)
    cfg.rain_skip_mm = st.sidebar.slider("Rain forecast skip ≥ (mm)", 0.0, 10.0, cfg.rain_skip_mm, 0.5)

    c1, c2, c3, c4, c5 = st.columns(5)
    d = c1.date_input("Date", value=date.today())
    eto = c2.number_input("ETo (mm/day)", 0.0, 10.0, 3.0, 0.1)
    rain_obs = c3.number_input("Rain observed (mm)", 0.0, 100.0, 0.0, 0.1)
    rain_fc  = c4.number_input("Rain forecast next 24h (mm)", 0.0, 100.0, 0.0, 0.1)
    note = c5.text_input("Notes", "")

    st.markdown("#### Per-plot measurements")
    rows = []
    plot_inputs = {}
    for p in PLOTS:
        with st.expander(f"{p} measurements"):
            theta = st.number_input(f"{p} θ VWC (m³/m³)", 0.00, 0.60, 0.0, 0.001, key=f"theta_{p}")
            ndvi  = st.number_input(f"{p} NDVI (optional)", 0.0, 1.0, 0.0, 0.01, key=f"ndvi_{p}")
            plot_inputs[p] = dict(theta=None if theta==0 else float(theta),
                                  ndvi=None if ndvi==0 else float(ndvi))
            rows.append([d.isoformat(), p, plot_inputs[p]["theta"], rain_obs, rain_fc, plot_inputs[p]["ndvi"], eto, note])

    if st.button("Save inputs to Google Sheet"):
        append_rows(st.secrets["gsheets"]["daily_inputs_ws"], rows)
        st.success("Daily inputs saved.")

    st.markdown("---")
    st.subheader("📏 Weekly Plant Heights (6 plants/plot)")
    ph_rows = []
    ph_date = st.date_input("Height date", value=date.today(), key="height_date")
    for p in PLOTS:
        with st.expander(f"{p} heights"):
            for pid in range(1, 7):
                h = st.number_input(f"{p} Plant {pid} height (cm)", 0.0, 100.0, 0.0, 0.1, key=f"h_{p}_{pid}")
                if h > 0:
                    ph_rows.append([ph_date.isoformat(), p, pid, h])
    if st.button("Save plant heights"):
        append_rows(st.secrets["gsheets"]["plant_ws"], ph_rows)
        st.success("Plant heights saved.")

    st.markdown("---")
    st.subheader("🧮 Compute decisions (T2, T3, T4)")
    if "Dr" not in st.session_state:
        st.session_state.Dr = {p: 0.0 for p in PLOTS}

    def compute_and_log_decisions():
        decision_rows = []
        for p in PLOTS:
            if p == "T1":
                decision_rows.append([d.isoformat(), p, "T1", "Manual", "Farmer", "", "", "", "", "", rain_fc, "", ""])
                continue

            Dr_start = st.session_state.Dr.get(p, 0.0)
            theta = plot_inputs[p]["theta"]
            ndvi = plot_inputs[p]["ndvi"]

            if p == "T2":
                out = decide_T2(d, eto, rain_obs, rain_fc, theta, Dr_start, cfg)
            elif p == "T3":
                out = decide_T3(d, eto, rain_obs, rain_fc, ndvi, Dr_start, cfg)
            else:
                out = decide_T4_strict(d, eto, rain_obs, rain_fc, ndvi, theta, Dr_start, cfg)

            st.session_state.Dr[p] = 0.0 if out["decision"] == "Irrigate" else out["Dr_end"]

            decision_rows.append([
                d.isoformat(), p, out["plot"], out["decision"], out["reason"],
                round(out["Dr_start"],1), round(out["RAW"],1),
                ("" if "theta_vwc" not in out or out["theta_vwc"] is None else round(out["theta_vwc"],3)),
                ("" if "theta_trigger" not in out else round(out["theta_trigger"],3)),
                ("" if "ndvi" not in out or out["ndvi"] is None else round(out["ndvi"],2)),
                round(out["kc"],2) if "kc" in out else "",
                rain_fc,
                round(out["irr_gross_mm"],1) if out["decision"]=="Irrigate" else "",
                round(out["irr_liters"],1) if out["decision"]=="Irrigate" else "",
            ])
        append_rows(st.secrets["gsheets"]["decisions_ws"], decision_rows)
        return decision_rows

    if st.button("Compute & save today’s decisions"):
        rows2 = compute_and_log_decisions()
        st.success("Decisions computed & saved.")
        st.dataframe(pd.DataFrame(rows2, columns=[
            "date","plot","treatment","decision","reason","Dr","RAW","theta","theta_trigger","ndvi","Kc","rain_fcst","irr_mm","irr_L"
        ]), use_container_width=True)

with tab_admin:
    st.subheader("⚙️ Admin – Configuration & Calibration")
    from data_io import read_sheet, _open_ws
    from datetime import date as _d

    try:
        df_meta = read_sheet(st.secrets["gsheets"]["metadata_ws"])
        current = {r["key"]: r["value"] for _, r in df_meta.iterrows()} if not df_meta.empty else {}
    except Exception:
        df_meta = pd.DataFrame()
        current = {}

    c1, c2, c3 = st.columns(3)
    theta_fc = c1.number_input("θ_fc (m³/m³)", 0.1, 0.6, float(current.get("theta_fc", 0.30)), 0.01)
    theta_wp = c2.number_input("θ_wp (m³/m³)", 0.02, 0.4, float(current.get("theta_wp", 0.12)), 0.01)
    alpha = c3.slider("α for θ_trigger", 0.2, 0.8, float(current.get("alpha", 0.6)), 0.05)

    c1, c2, c3, c4 = st.columns(4)
    a = c1.number_input("NDVI→Kc a", 0.0, 3.0, float(current.get("a", 1.25)), 0.05)
    b = c2.number_input("NDVI→Kc b", -0.5, 1.0, float(current.get("b", 0.20)), 0.05)
    kc_min = c3.number_input("Kc_min", 0.1, 1.0, float(current.get("kc_min", 0.3)), 0.05)
    kc_max = c4.number_input("Kc_max", 0.5, 1.5, float(current.get("kc_max", 1.1)), 0.05)
    active_gate = st.slider("Active canopy gate (Kc)", 0.5, 1.2, float(current.get("active_gate", 0.8)), 0.01)

    c1, c2, c3 = st.columns(3)
    eta = c1.number_input("Application efficiency η", 0.5, 0.98, float(current.get("eta", 0.85)), 0.01)
    rain_skip = c2.number_input("Rain forecast skip ≥ (mm)", 0.0, 10.0, float(current.get("rain_skip", 2.0)), 0.5)
    transplant_str = current.get("transplant_date", str(_d(2025, 11, 6)))
    transplant_date = c3.date_input("Transplant date", value=_d.fromisoformat(transplant_str))

    if st.button("💾 Save settings (append history)"):
        ws = _open_ws(st.secrets["gsheets"]["metadata_ws"])
        now = _d.today().isoformat()
        rows = [
            ["theta_fc", theta_fc, now],
            ["theta_wp", theta_wp, now],
            ["alpha", alpha, now],
            ["a", a, now],
            ["b", b, now],
            ["kc_min", kc_min, now],
            ["kc_max", kc_max, now],
            ["active_gate", active_gate, now],
            ["eta", eta, now],
            ["rain_skip", rain_skip, now],
            ["transplant_date", transplant_date.isoformat(), now],
        ]
        vals = ws.get_all_values()
        if not vals:
            ws.append_row(["key","value","timestamp"], value_input_option="USER_ENTERED")
        ws.append_rows(rows, value_input_option="USER_ENTERED")
        st.success("Settings saved to metadata history.")

with tab_analytics:
    st.subheader("📊 Analytics & Visualization")
    try:
        df_in = read_sheet(st.secrets["gsheets"]["daily_inputs_ws"])
        df_dec = read_sheet(st.secrets["gsheets"]["decisions_ws"])
        df_h = read_sheet(st.secrets["gsheets"]["plant_ws"])
    except Exception as e:
        st.error(f"Error reading data: {e}")
        df_in=df_dec=df_h=pd.DataFrame()

    if df_in.empty or df_dec.empty:
        st.info("Add some data first to see analytics.")
    else:
        for df in [df_in, df_dec]:
            if "date" in df.columns:
                df["date"] = pd.to_datetime(df["date"], errors="coerce")
        df_dec["irr_mm"] = pd.to_numeric(df_dec.get("irr_mm", 0), errors="coerce").fillna(0)
        df_dec["irr_L"] = pd.to_numeric(df_dec.get("irr_L", 0), errors="coerce").fillna(0)
        df_in["theta_vwc"] = pd.to_numeric(df_in.get("theta_vwc", 0), errors="coerce").fillna(0)
        df_in["ndvi"] = pd.to_numeric(df_in.get("ndvi", 0), errors="coerce").fillna(0)

        plots = sorted(df_dec["plot"].dropna().unique())
        selected_plots = st.multiselect("Select plot(s)", plots, default=plots)
        df_dec_filt = df_dec[df_dec["plot"].isin(selected_plots)]
        df_in_filt = df_in[df_in["plot"].isin(selected_plots)]

        st.markdown("### 🌿 NDVI & Soil Moisture vs Irrigation")
        df_merge = pd.merge(df_in_filt, df_dec_filt[["date","plot","decision","irr_mm"]], on=["date","plot"], how="left")
        for p in selected_plots:
            st.markdown(f"#### Plot {p}")
            df_p = df_merge[df_merge["plot"] == p].sort_values("date")
            if df_p.empty:
                st.info(f"No data for {p}")
                continue
            base = alt.Chart(df_p).encode(x="date:T")
            ndvi_line = base.mark_line(color="green").encode(y=alt.Y("ndvi:Q", title="NDVI"))
            soil_line = base.mark_line(color="steelblue").encode(y=alt.Y("theta_vwc:Q", title="Soil moisture (m³/m³)"))
            irr_bars = base.mark_bar(color="orange", opacity=0.4).encode(y=alt.Y("irr_mm:Q", title="Irrigation (mm)"))
            chart = alt.layer(ndvi_line, soil_line, irr_bars).resolve_scale(y="independent").properties(height=300)
            st.altair_chart(chart, use_container_width=True)

        st.markdown("### 💧 Water-Use Efficiency (WUE)")
        if not df_h.empty and not df_dec.empty:
            df_h["date"] = pd.to_datetime(df_h["date"], errors="coerce")
            df_h["height_cm"] = pd.to_numeric(df_h["height_cm"], errors="coerce")
            h_agg = df_h.groupby("plot")["height_cm"].agg(["min","max"]).reset_index()
            irr_agg = df_dec.groupby("plot")["irr_L"].sum().reset_index()
            wue = pd.merge(h_agg, irr_agg, on="plot", how="left")
            wue["WUE (cm/L)"] = (wue["max"] - wue["min"]) / wue["irr_L"].replace(0, pd.NA)
            st.dataframe(wue.round(3), use_container_width=True)

with tab_reports:
    st.subheader("🧾 Weekly PDF Report & Email")
    today = date.today()
    week_start = today - timedelta(days=7)

    try:
        df_in = read_sheet(st.secrets["gsheets"]["daily_inputs_ws"])
        df_dec = read_sheet(st.secrets["gsheets"]["decisions_ws"])
        df_ph = read_sheet(st.secrets["gsheets"]["plant_ws"])
    except Exception as e:
        st.error(f"Error reading data: {e}")
        df_in=df_dec=df_ph=pd.DataFrame()

    for df in (df_in, df_dec, df_ph):
        if not df.empty and "date" in df.columns:
            df["date"] = pd.to_datetime(df["date"], errors="coerce")

    df_in_w  = df_in[df_in["date"].between(week_start, today)].copy() if not df_in.empty else pd.DataFrame()
    df_dec_w = df_dec[df_dec["date"].between(week_start, today)].copy() if not df_dec.empty else pd.DataFrame()
    df_ph_w  = df_ph[df_ph["date"].between(week_start, today)].copy() if not df_ph.empty else pd.DataFrame()

    irr_chart = alt.Chart(df_dec_w).mark_bar().encode(
        x="plot:N", y="sum(irr_L):Q", color="plot:N", tooltip=["plot", "sum(irr_L)"]
    ).properties(title="Total Irrigation (L) – This Week", height=300)

    ndvi_chart = alt.Chart(df_in_w).mark_circle(size=60).encode(
        x=alt.X("theta_vwc:Q", title="Soil Moisture (m³/m³)"),
        y=alt.Y("ndvi:Q", title="NDVI"),
        color="plot:N",
        tooltip=["plot","date","theta_vwc","ndvi"]
    ).properties(title="NDVI vs Soil Moisture", height=300)

    st.altair_chart(irr_chart, use_container_width=True)
    st.altair_chart(ndvi_chart, use_container_width=True)

    if not df_ph_w.empty:
        df_hm = df_ph_w.groupby(["date","plot"], as_index=False)["height_cm"].mean()
        height_chart = alt.Chart(df_hm).mark_line(point=True).encode(
            x="date:T", y=alt.Y("height_cm:Q", title="Mean height (cm)"), color="plot:N",
            tooltip=["plot","date","height_cm"]
        ).properties(title="Plant Height Trend (mean of 6 plants)", height=300)
        st.altair_chart(height_chart, use_container_width=True)
    else:
        height_chart = None
        st.info("No plant height data this week.")

    if not df_ph_w.empty and not df_dec_w.empty:
        h_mean = df_ph_w.groupby("plot", as_index=False)["height_cm"].mean().rename(columns={"height_cm":"height_mean"})
        irr_sum = df_dec_w.groupby("plot", as_index=False)["irr_L"].sum().rename(columns={"irr_L":"irr_L_week"})
        wue = h_mean.merge(irr_sum, on="plot", how="left")
        wue["WUE_cm_per_L"] = wue["height_mean"] / wue["irr_L_week"].replace(0, pd.NA)
        wue_chart = alt.Chart(wue.fillna(0)).mark_bar().encode(
            x="plot:N", y=alt.Y("WUE_cm_per_L:Q", title="WUE (cm/L)"),
            color="plot:N", tooltip=["plot","height_mean","irr_L_week","WUE_cm_per_L"]
        ).properties(title="Water-Use Efficiency (this week)", height=300)
        st.altair_chart(wue_chart, use_container_width=True)
    else:
        wue_chart = None

    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Image as RLImage, Table, TableStyle
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib import colors
    from reportlab.lib.units import cm

    def chart_to_image(chart):
        import altair_saver
        return io.BytesIO(chart.save(None, format='png'))

    def make_pdf(buffer, df_dec, df_in, charts_images):
        doc = SimpleDocTemplate(buffer, pagesize=A4, topMargin=1.5*cm, bottomMargin=1.5*cm)
        styles = getSampleStyleSheet()
        styles.add(ParagraphStyle(name='CenterTitle', alignment=1, fontSize=18, spaceAfter=20))
        styles.add(ParagraphStyle(name='SectionHeader', fontSize=14, textColor=colors.HexColor('#006400'), spaceAfter=10))
        story = []
        story.append(Paragraph("<b>Smart Irrigation System – Weekly Report</b>", styles['CenterTitle']))
        story.append(Paragraph("<b>Crop:</b> Spinach  &nbsp;&nbsp;  <b>Site:</b> Utsunomiya, Japan", styles['Normal']))
        story.append(Paragraph(f"<b>Period:</b> {week_start} – {today}", styles['Normal']))
        story.append(Paragraph("<b>Prepared by:</b> Patrick Habyarimana<br/><b>Verified by:</b> Supervisor / Advisor", styles['Normal']))
        story.append(Spacer(1, 20))
        story.append(Paragraph("Executive Summary", styles['SectionHeader']))
        try:
            total_irr = df_dec.groupby("plot")["irr_L"].sum().to_dict()
            mean_ndvi = df_in.groupby("plot")["ndvi"].mean().to_dict()
            best_eff = min(total_irr, key=total_irr.get) if total_irr else None
            highest_ndvi = max(mean_ndvi, key=mean_ndvi.get) if mean_ndvi else None
            diff_ratio = (1 - (total_irr.get("T3", 0) / (total_irr.get("T2", 1) + 1e-6))) * 100
            summary_text = f"""During {week_start}–{today}, plot <b>{best_eff}</b> used the least water ({total_irr.get(best_eff,0):.1f} L),
            while plot <b>{highest_ndvi}</b> achieved the highest mean NDVI ({mean_ndvi.get(highest_ndvi,0):.2f}).
            T3 used {diff_ratio:.1f}% less water than T2 with comparable canopy vigor."""
            story.append(Paragraph(summary_text, styles['Normal']))
        except Exception as e:
            story.append(Paragraph(f"<i>Summary unavailable (data incomplete): {e}</i>", styles['Normal']))
        story.append(Spacer(1, 12))
        story.append(Paragraph("Irrigation & NDVI Analysis", styles['SectionHeader']))
        for img in charts_images:
            story.append(RLImage(img, width=15*cm, height=8*cm))
            story.append(Spacer(1, 10))
        irr_tbl = df_dec.groupby("plot")["irr_L"].sum().reset_index()
        ndvi_tbl = df_in.groupby("plot")["ndvi"].mean().reset_index()
        merged = pd.merge(irr_tbl, ndvi_tbl, on="plot", how="left").round(2)
        data = [["Plot", "Irrigation (L)", "Mean NDVI"]] + merged.values.tolist()
        table = Table(data)
        story.append(table)
        doc.build(story)
        buffer.seek(0)
        return buffer

    charts = [irr_chart, ndvi_chart]
    if height_chart is not None:
        charts.append(height_chart)
    if wue_chart is not None:
        charts.append(wue_chart)
    imgs = [chart_to_image(c) for c in charts]
    buffer = io.BytesIO()
    pdf = make_pdf(buffer, df_dec_w, df_in_w, imgs)
    st.download_button("Download Weekly_Report.pdf", pdf, file_name=f"Weekly_Report_{today}.pdf")

    if st.button("Send Report Now"):
        try:
            msg_id = send_email_with_pdf(pdf, filename=f"Weekly_Report_{today}.pdf")
            st.success(f"Email sent! Gmail Message ID: {msg_id}")
        except Exception as e:
            st.error(f"Failed to send email: {e}")
