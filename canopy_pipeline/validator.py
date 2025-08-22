
import sys, json, pandas as pd, numpy as np

def load_contract(path):
    with open(path) as f: return json.load(f)

def normalize(df, contract):
    df = df.copy()
    # Trim whitespace
    if contract["normalization"].get("strip_whitespace", False):
        for c in df.columns:
            if df[c].dtype == object:
                df[c] = df[c].astype(str).str.strip()
    # Uppercase species
    if contract["normalization"].get("upper_species_codes", False) and "Species" in df.columns:
        df["Species"] = df["Species"].astype(str).str.upper()
    # Standardize dates (best-effort)
    if "CruiseDate" in df.columns:
        df["CruiseDate"] = pd.to_datetime(df["CruiseDate"], errors="coerce").dt.strftime("%Y-%m-%d")
    return df

def validate(df, contract):
    errors, warnings = [], []
    cols = set(df.columns)
    for req in contract["required_columns"]:
        if req not in cols:
            errors.append(f"Missing required column: {req}")
    # Constraints (best-effort)
    if "StandAcres" in cols and (df["StandAcres"].dropna() <= 0).any():
        errors.append("StandAcres must be > 0")
    if "DBH" in cols:
        bad_dbh = df["DBH"].dropna()
        if ((bad_dbh < 1) | (bad_dbh > 60)).any():
            warnings.append("Some DBH values are outside 1–60 inches")
    if "TopDIB" in cols and "DBH" in cols:
        mask = (df["TopDIB"].notna()) & (df["DBH"].notna()) & (df["TopDIB"] > df["DBH"])
        if mask.any():
            warnings.append("Some TopDIB > DBH rows found")
    if "Defect" in cols:
        bad_def = df["Defect"].dropna()
        if ((bad_def < 0) | (bad_def > 100)).any():
            warnings.append("Some Defect values outside 0–100%")
    if "CruiseType" in cols:
        bad = ~df["CruiseType"].astype(str).isin(["Plot","Point"])
        if bad.any():
            warnings.append("CruiseType contains values other than 'Plot' or 'Point'")
    return errors, warnings

def remap(df, contract):
    out = pd.DataFrame()
    m = contract["mapping_to_canopy"]
    for dst, src in m.items():
        out[dst] = df[src] if src in df.columns else np.nan
    return out

def main():
    if len(sys.argv) < 4:
        print("Usage: python validator.py <TreeSum.xlsx|.csv> <contract.json> <output_prefix>")
        sys.exit(1)
    infile, contract_path, outprefix = sys.argv[1], sys.argv[2], sys.argv[3]
    contract = load_contract(contract_path)
    # Load tree-level data (TreeSum sheet if Excel)
    if infile.lower().endswith((".xlsx",".xlsm",".xls")):
        df = pd.read_excel(infile, sheet_name="TreeSum")
    else:
        df = pd.read_csv(infile)
    df = normalize(df, contract)
    errors, warnings = validate(df, contract)
    report = {
        "rows": int(len(df)),
        "columns": list(df.columns),
        "errors": errors,
        "warnings": warnings,
        "stands_detected": sorted([str(s) for s in df["StandID"].dropna().unique()]) if "StandID" in df.columns else []
    }
    out_csv = f"{outprefix}_treesum_normalized.csv"
    out_json = f"{outprefix}_import_report.json"
    # Save normalized TreeSum (original columns) and remapped Canopy version
    df.to_csv(out_csv, index=False)
    canopy_df = remap(df, contract)
    canopy_csv = f"{outprefix}_canopy_treelevel.csv"
    canopy_df.to_csv(canopy_csv, index=False)
    with open(out_json, "w") as f:
        json.dump(report, f, indent=2)
    print(json.dumps(report, indent=2))
    print(f"Saved: {out_csv}, {canopy_csv}, {out_json}")

if __name__ == "__main__":
    main()
