
import sys, json, pandas as pd, numpy as np, io, base64, math
import matplotlib.pyplot as plt
from datetime import date, datetime

TODAY_YEAR = datetime.today().year

def fig_to_base64_png(fig):
    buf = io.BytesIO()
    fig.savefig(buf, format='png', dpi=120, bbox_inches='tight')
    plt.close(fig)
    buf.seek(0)
    return "data:image/png;base64," + base64.b64encode(buf.read()).decode("ascii")

def auto_event_years(age, thin1_age=15, thin2_age=21, final_age=30):
    if pd.isna(age):
        return TODAY_YEAR+2, TODAY_YEAR+8, TODAY_YEAR+15
    y1 = max(TODAY_YEAR, TODAY_YEAR + int(round(thin1_age - age)))
    y2 = max(y1+1, TODAY_YEAR + int(round(thin2_age - age)))
    yf = max(y2+1, TODAY_YEAR + int(round(final_age - age)))
    return y1, y2, yf

def product_split_from_qmd(qmd):
    if pd.isna(qmd): qmd = 7.0
    if qmd < 6: return {"pulp":0.9,"cns":0.1,"saw":0.0,"export":0.0}
    if qmd < 8: return {"pulp":0.5,"cns":0.4,"saw":0.1,"export":0.0}
    if qmd < 10: return {"pulp":0.3,"cns":0.4,"saw":0.3,"export":0.0}
    return {"pulp":0.2,"cns":0.3,"saw":0.4,"export":0.1}

def estimate_tons(ba, acres, event_type, removal_pct=0.28, yield_per_ba=0.12, final_tons_bounds=(60,150)):
    if pd.isna(ba) or pd.isna(acres) or acres<=0:
        return 0.0
    if event_type in ("first_thin","second_thin"):
        t = float(ba) * float(removal_pct) * float(yield_per_ba) * float(acres)
        return max(t, 0.0)
    tons_per_ac = max(final_tons_bounds[0], min(final_tons_bounds[1], float(ba) * 1.2))
    return tons_per_ac * float(acres)

def allocate_products(total_tons, split):
    return {
        "pulp_t": total_tons * split["pulp"],
        "cns_t": total_tons * split["cns"],
        "saw_t": total_tons * split["saw"],
        "export_t": total_tons * split["export"],
    }

def load_calibration(path):
    if not path:
        return {}
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return {}

def get_factor(factors, group, name):
    if isinstance(factors, dict):
        if group in factors and name in factors[group]:
            return float(factors[group][name])
        if "ALL" in factors and name in factors["ALL"]:
            return float(factors["ALL"][name])
    return 1.0

def compute_cashflows(events_df, prices, costs=None, discount_rate=0.05):
    if costs is None: costs = {}
    cf = []
    for _,r in events_df.iterrows():
        year = int(r["year"])
        tons = {"pulp":r["pulp_t"], "cns":r["cns_t"], "saw":r["saw_t"], "export":r["export_t"]}
        gross = sum(tons[k]*prices.get(k,0.0) for k in tons.keys())
        logging = sum(tons[k]*costs.get(f"logging_per_ton_{k}", 0.0) for k in tons.keys())
        trucking = sum(tons[k]*costs.get("trucking_per_ton", 0.0) for k in tons.keys())
        consulting = (costs.get("consulting_pct", 0.0)/100.0) * gross
        net = gross - logging - trucking - consulting
        years_from_now = max(0, year - date.today().year)
        cf.append({"year": year, "gross": gross, "net": net, "years_from_now": years_from_now})
    npv = sum(c["net"] / ((1+discount_rate)**c["years_from_now"]) for c in cf)
    # IRR support
    max_h = max([c["years_from_now"] for c in cf]+[0])
    series = [0.0]*(max_h+1)
    for c in cf:
        series[c["years_from_now"]] += c["net"]
    try:
        irr = np.irr(series) * 100.0 if hasattr(np, "irr") else float("nan")
    except Exception:
        irr = float("nan")
    return cf, npv, irr

def build_report_v3plus(stand_summary_csv, prices_json, out_html,
                        events_csv=None, owner_name="Owner", tract_name="Tract", discount_rate=0.05,
                        calibration_json=None, species_col=None):
    stands = pd.read_csv(stand_summary_csv)
    with open(prices_json) as f: raw_prices = json.load(f)
    prices = {"pulp": raw_prices.get("pulp", 0), "cns": raw_prices.get("cns", 0), "saw": raw_prices.get("saw", 0), "export": raw_prices.get("export", 0)}
    costs = {
        "logging_per_ton_pulp": raw_prices.get("logging_cost_per_ton_pulp", 0),
        "logging_per_ton_cns": raw_prices.get("logging_cost_per_ton_cns", 0),
        "logging_per_ton_saw": raw_prices.get("logging_cost_per_ton_saw", 0),
        "logging_per_ton_export": raw_prices.get("logging_cost_per_ton_export", 0),
        "trucking_per_ton": raw_prices.get("trucking_rate_per_ton", 0),
        "consulting_pct": raw_prices.get("consulting_fee_pct", 0),
    }

    cal = load_calibration(calibration_json)

    # Build/Load events
    if events_csv:
        events = pd.read_csv(events_csv)
        # Apply ONLY global product factors if available (no stand/species info here)
        for k in ["pulp","cns","saw","export"]:
            fac = get_factor(cal, "ALL", f"{k}_factor")
            col = f"{k}_t"
            if col in events.columns:
                events[col] = events[col] * fac
    else:
        rows = []
        for _,r in stands.iterrows():
            sid = r["stand_id"]
            acres = r.get("acres", np.nan)
            ba = r.get("ba_sqft_ac", np.nan)
            qmd = r.get("qmd_in", np.nan)
            age = r.get("age", np.nan) if "age" in stands.columns else np.nan
            group = r.get(species_col, "ALL") if (species_col and species_col in r.index) else "ALL"
            y1, y2, yf = auto_event_years(age)
            split = product_split_from_qmd(qmd)
            # Estimate tons per event
            t1 = estimate_tons(ba, acres, "first_thin", removal_pct=0.28)
            t2 = estimate_tons(ba, acres, "second_thin", removal_pct=0.33)
            tf = estimate_tons(ba, acres, "final")
            for (evt, yr, t) in [("first_thin", y1, t1), ("second_thin", y2, t2), ("final", yf, tf)]:
                alloc = allocate_products(t, split)
                # Apply per-group product scaling factors
                for k in ["pulp","cns","saw","export"]:
                    alloc[f"{k}_t"] *= get_factor(cal, group, f"{k}_factor")
                row = {"stand_id": sid, "event": evt, "year": yr, "group": group}
                row.update(alloc)
                rows.append(row)
        events = pd.DataFrame(rows)
        # Aggregate to tract totals by event-year for charts
        events = events.groupby(["event","year"], as_index=False)[["pulp_t","cns_t","saw_t","export_t"]].sum()

    # Charts
    total_tons = {k: float(events[f"{k}_t"].sum()) for k in ["pulp","cns","saw","export"]}
    fig_exposure = plt.figure(figsize=(4.5,4.5))
    vals = [total_tons[k] for k in ["pulp","cns","saw","export"]]
    plt.pie(vals, labels=["Pulp","CNS","Saw","Export"], autopct="%1.0f%%")
    plt.title("Market Exposure (tons)")
    chart_exposure = fig_to_base64_png(fig_exposure)

    fig_ba = plt.figure(figsize=(6,3))
    plt.bar(stands["stand_id"].astype(str), stands["ba_sqft_ac"])
    plt.ylabel("BA (ft²/ac)"); plt.title("Basal Area by Stand")
    chart_ba = fig_to_base64_png(fig_ba)

    ev_gross = events.assign(gross = events["pulp_t"]*prices["pulp"] + events["cns_t"]*prices["cns"] + events["saw_t"]*prices["saw"] + events["export_t"]*prices["export"])
    fig_tl = plt.figure(figsize=(6,3))
    plt.bar(ev_gross["year"].astype(int).astype(str), ev_gross["gross"])
    plt.title("Harvest Timeline (Gross $)"); plt.ylabel("USD")
    chart_timeline = fig_to_base64_png(fig_tl)

    # ROI
    cashflows, npv, irr = compute_cashflows(ev_gross, prices, costs=costs, discount_rate=discount_rate)

    # HTML
    today = str(date.today())
    html = f"""<!doctype html>
<html>
<head>
  <meta charset="utf-8"/>
  <title>Canopy Owner Report — {tract_name}</title>
  <style>
    body {{ font-family: Arial, Helvetica, sans-serif; margin: 24px; color: #222; }}
    h1 {{ margin: 0 0 8px 0; }}
    h2 {{ margin: 18px 0 8px 0; border-bottom: 2px solid #eee; padding-bottom: 4px; }}
    table {{ border-collapse: collapse; width:100%; margin: 10px 0 18px 0; }}
    th, td {{ border: 1px solid #e8e8e8; padding: 8px; font-size: 13px; }}
    th {{ background:#f7f7f7; text-align:left; }}
    .grid {{ display: grid; grid-template-columns: repeat(2, 1fr); gap: 16px; }}
    .card {{ border:1px solid #eee; border-radius: 10px; padding: 12px; background: #fff; }}
    img.chart {{ max-width: 100%; height: auto; border:1px solid #eee; border-radius: 6px; padding: 4px; background: #fff; }}
    .small {{ font-size: 12px; color:#666; }}
  </style>
</head>
<body>
  <h1>Owner Report — {tract_name}</h1>
  <div class="small">Owner: {owner_name} • Generated: {today}</div>

  <h2>ROI Snapshot</h2>
  <table>
    <tr><th>Discount Rate</th><td>{discount_rate*100:.1f}%</td></tr>
    <tr><th>NPV (net)</th><td>${npv:,.0f}</td></tr>
    <tr><th>IRR</th><td>{'' if np.isnan(irr) else f'{irr:.1f}%'} </td></tr>
  </table>

  <h2>Stand Summary</h2>
  <table>
    <tr><th>Stand</th><th>Acres</th><th>TPA</th><th>BA (ft²/ac)</th><th>QMD (in)</th></tr>
  """
    for _,r in stands.iterrows():
        acres = r["acres"] if "acres" in r and not pd.isna(r["acres"]) else ""
        tpa = r["tpa_live"] if "tpa_live" in r else np.nan
        ba = r["ba_sqft_ac"] if "ba_sqft_ac" in r else np.nan
        qmd = r["qmd_in"] if "qmd_in" in r else np.nan
        html += f"<tr><td>{r['stand_id']}</td><td>{acres}</td><td>{tpa:.1f}</td><td>{ba:.1f}</td><td>{qmd:.1f}</td></tr>"
    html += "</table>"

    html += f"<h2>Charts</h2><div class='grid'><div class='card'><strong>Basal Area by Stand</strong><br/><img class='chart' src='{chart_ba}'/></div>"
    html += f"<div class='card'><strong>Market Exposure (tons)</strong><br/><img class='chart' src='{chart_exposure}'/></div></div>"
    html += f"<div class='card' style='margin-top:16px;'><strong>Harvest Timeline (Gross $)</strong><br/><img class='chart' src='{chart_timeline}'/></div>"

    html += "<h2>Event Schedule (Totals)</h2><table><tr><th>Event</th><th>Year</th><th>Pulp (t)</th><th>CNS (t)</th><th>Saw (t)</th><th>Export (t)</th><th>Gross ($)</th></tr>"
    for _,e in ev_gross.iterrows():
        html += f"<tr><td>{e['event']}</td><td>{int(e['year'])}</td><td>{e['pulp_t']:,.0f}</td><td>{e['cns_t']:,.0f}</td><td>{e['saw_t']:,.0f}</td><td>{e['export_t']:,.0f}</td><td>${e['gross']:,.0f}</td></tr>"
    html += "</table>"

    html += "<h2>Assumptions</h2><ul>"
    html += "<li>Thin1 ~28% BA, Thin2 ~33% BA; Final at target rotation ~30 (auto if ages unknown).</li>"
    html += "<li>Product splits estimated from QMD; override by supplying events.csv with product tons.</li>"
    html += "<li>Calibration product factors applied per species (auto-events) or global factors (provided totals).</li>"
    html += "<li>Costs from prices.json (logging/trucking/consulting) if provided; otherwise $0.</li>"
    html += "<li>Estimation factors are placeholders; run calibration helper to align with your gold standard.</li>"
    html += "</ul>"

    html += "</body></html>"
    with open(out_html,"w",encoding="utf-8") as f:
        f.write(html)
    print(f"Saved {out_html}")

if __name__=="__main__":
    if len(sys.argv) < 4:
        print("Usage: python owner_report_build_v3plus.py <stand_summary.csv> <prices.json> <out.html> [events.csv] [owner_name] [tract_name] [discount_rate_percent] [calibration.json] [species_col]")
        sys.exit(1)
    stand_summary_csv, prices_json, out_html = sys.argv[1], sys.argv[2], sys.argv[3]
    events_csv = sys.argv[4] if len(sys.argv)>=5 and sys.argv[4] else None
    owner = sys.argv[5] if len(sys.argv)>=6 else "Owner"
    tract = sys.argv[6] if len(sys.argv)>=7 else "Tract"
    dr = float(sys.argv[7])/100.0 if len(sys.argv)>=8 else 0.05
    cal_json = sys.argv[8] if len(sys.argv)>=9 and sys.argv[8] else None
    sp_col = sys.argv[9] if len(sys.argv)>=10 and sys.argv[9] else None
    build_report_v3plus(stand_summary_csv, prices_json, out_html, events_csv, owner, tract, discount_rate=dr, calibration_json=cal_json, species_col=sp_col)
