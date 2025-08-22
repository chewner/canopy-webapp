
import sys, json, pandas as pd, numpy as np

def load_calibration(cal_path):
    if not cal_path:
        return {}
    with open(cal_path) as f:
        return json.load(f)

def get_factor(factors, group, name):
    # factors: {"ALL": {"ba_factor":1.0,...}, "LP": {...}}
    if isinstance(factors, dict):
        if group in factors and name in factors[group]:
            return float(factors[group][name])
        if "ALL" in factors and name in factors["ALL"]:
            return float(factors["ALL"][name])
    return 1.0

def aggregate(tree_csv, outprefix, cruise_type="Plot", plot_size_ac=None, baf=None,
              calibration_json=None, species_col=None):
    df = pd.read_csv(tree_csv)
    if "stand_id" not in df.columns:
        raise ValueError("Missing stand_id column")
    factors = load_calibration(calibration_json)
    results = []
    grouped = df.groupby("stand_id")
    for sid, g in grouped:
        acres = g["acres"].iloc[0] if "acres" in g.columns and not pd.isna(g["acres"].iloc[0]) else np.nan
        # Choose group key for calibration
        if species_col and species_col in g.columns and pd.notna(g[species_col]).any():
            grp_key = str(g[species_col].dropna().iloc[0])
        else:
            grp_key = "ALL"
        # Count trees
        n_trees = len(g)
        # Expansion factor: Plot vs Point
        if cruise_type=="Plot":
            if not plot_size_ac:
                raise ValueError("Need plot_size_ac for Plot cruises")
            exp_factor = 1.0/plot_size_ac
            tpa = n_trees * exp_factor
            ba = (np.pi*(g["dbh_in"]**2)/144.0).sum() * exp_factor
        elif cruise_type=="Point":
            if not baf:
                raise ValueError("Need BAF for Point cruises")
            # Each tree represents BAF/BA_t of TPA
            tpa = (baf / (0.005454*g["dbh_in"]**2)).sum()
            ba = baf * n_trees
        else:
            raise ValueError("CruiseType must be Plot or Point")
        # QMD pre-calibration
        qmd = np.sqrt((ba*144.0)/(0.005454*len(g))) if len(g)>0 else np.nan

        # Apply calibration factors (if provided)
        ba *= get_factor(factors, grp_key, "ba_factor")
        qmd *= get_factor(factors, grp_key, "qmd_factor")
        tpa *= get_factor(factors, grp_key, "tpa_factor")

        results.append({
            "stand_id": sid,
            "acres": acres,
            "trees_observed": n_trees,
            "tpa_live": tpa,
            "ba_sqft_ac": ba,
            "qmd_in": qmd,
            "calibration_group": grp_key
        })
    out = pd.DataFrame(results)
    out_csv = f"{outprefix}_stand_summary.csv"
    out.to_csv(out_csv, index=False)
    print(f"Saved stand summary: {out_csv}")
    return out

if __name__=="__main__":
    # Backward-compatible CLI:
    # python stand_aggregator.py <treelevel.csv> <outprefix> <CruiseType> <PlotSize|BAF> [--calibration path.json] [--species_col Species]
    import argparse
    ap = argparse.ArgumentParser(description="Aggregate tree-level data to stand summaries with optional calibration factors.")
    ap.add_argument("tree_csv")
    ap.add_argument("outprefix")
    ap.add_argument("cruise_type", choices=["Plot","Point"])
    ap.add_argument("size_value", type=float, help="PlotSize acres for Plot OR BAF for Point")
    ap.add_argument("--calibration", default=None, help="Path to calibration_factors.json")
    ap.add_argument("--species_col", default=None, help="Column name to use for per-species calibration groups (e.g., 'species_code' or 'CalSpecies')")
    args = ap.parse_args()

    if args.cruise_type=="Plot":
        aggregate(args.tree_csv, args.outprefix, cruise_type="Plot", plot_size_ac=args.size_value,
                  calibration_json=args.calibration, species_col=args.species_col)
    else:
        aggregate(args.tree_csv, args.outprefix, cruise_type="Point", baf=args.size_value,
                  calibration_json=args.calibration, species_col=args.species_col)
