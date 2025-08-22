
import os, uuid, json, tempfile, zipfile
from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for, send_from_directory, flash
from werkzeug.utils import secure_filename
import pandas as pd
import subprocess
import sys

# Paths
ROOT = os.path.dirname(os.path.abspath(__file__))
UPLOAD_DIR = os.path.join(ROOT, "uploads")
OUT_DIR = os.path.join(ROOT, "outputs")
os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(OUT_DIR, exist_ok=True)

# Python scripts in pipeline
PIPE_DIR = os.path.join(ROOT, "canopy_pipeline")
VALIDATOR = os.path.join(PIPE_DIR, "validator.py")
AGGREGATOR = os.path.join(PIPE_DIR, "stand_aggregator.py")
REPORTER = os.path.join(PIPE_DIR, "owner_report_build_v3plus.py")

ALLOWED_EXTS = {"xlsx","xlsm","csv","json"}

def allowed_file(filename):
    return "." in filename and filename.rsplit(".",1)[1].lower() in ALLOWED_EXTS

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY","dev-secret")

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/process", methods=["POST"])
def process():
    # Required files and params
    tree_file = request.files.get("treesum")
    prices_file = request.files.get("prices")
    cruise_type = request.form.get("cruise_type","Plot")
    size_value = request.form.get("size_value","0.1").strip()
    owner = request.form.get("owner","Owner").strip() or "Owner"
    tract = request.form.get("tract","Tract").strip() or "Tract"
    discount = request.form.get("discount","5").strip() or "5"

    # Optional
    events_file = request.files.get("events")
    calibration_file = request.files.get("calibration")
    species_col = request.form.get("species_col","CalSpecies").strip() or "CalSpecies"

    # Validate required inputs
    if not tree_file or not allowed_file(tree_file.filename):
        flash("Please upload a TreeSum file (.xlsx/.xlsm/.csv).")
        return redirect(url_for("index"))
    if not prices_file or not allowed_file(prices_file.filename):
        flash("Please upload a prices JSON file.")
        return redirect(url_for("index"))
    try:
        float(size_value)
    except:
        flash("Plot size (ac) or BAF must be numeric.")
        return redirect(url_for("index"))

    # Save uploads
    uid = datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:8]
    workdir = os.path.join(OUT_DIR, uid)
    os.makedirs(workdir, exist_ok=True)

    tree_path = os.path.join(workdir, secure_filename(tree_file.filename))
    tree_file.save(tree_path)

    prices_path = os.path.join(workdir, secure_filename(prices_file.filename))
    prices_file.save(prices_path)

    events_path = ""
    if events_file and events_file.filename and allowed_file(events_file.filename):
        events_path = os.path.join(workdir, secure_filename(events_file.filename))
        events_file.save(events_path)

    calibration_path = ""
    if calibration_file and calibration_file.filename and allowed_file(calibration_file.filename):
        calibration_path = os.path.join(workdir, secure_filename(calibration_file.filename))
        calibration_file.save(calibration_path)

    outprefix = os.path.join(workdir, "out")

    # Step 1: Validate & normalize
    contract_path = os.path.join(ROOT, "canopy_pipeline", "treesum_import_contract.json")
    if not os.path.exists(contract_path):
        # copy bundled contract into pipeline dir on first run
        bundled = os.path.join(ROOT, "treesum_import_contract.json")
        if os.path.exists(bundled):
            contract_path = bundled
        else:
            # write a minimal contract if missing
            with open(os.path.join(ROOT,"canopy_pipeline","treesum_import_contract.json"),"w") as f:
                f.write('{"required_columns":["TractName","StandID","StandAcres","CruiseDate","CruiseType","Size_BAF","PlotNum","PlotID","Species","DBH","MerchHt","TopDIB","TreeClass"],"mapping_to_canopy":{"stand_id":"StandID"}}')
            contract_path = os.path.join(ROOT,"canopy_pipeline","treesum_import_contract.json")

    cmd_validate = [sys.executable, VALIDATOR, tree_path, contract_path, outprefix]
    run1 = subprocess.run(cmd_validate, capture_output=True, text=True)
    if run1.returncode != 0:
        return render_template("result.html", error="Validator failed", stdout=run1.stdout, stderr=run1.stderr, files=[])

    # Step 2: Aggregate (with optional calibration)
    size_val = str(float(size_value))
    agg_args = [sys.executable, AGGREGATOR, f"{outprefix}_canopy_treelevel.csv", outprefix, cruise_type, size_val]
    if calibration_path:
        agg_args += ["--calibration", calibration_path, "--species_col", species_col]
    run2 = subprocess.run(agg_args, capture_output=True, text=True)
    if run2.returncode != 0:
        return render_template("result.html", error="Aggregator failed", stdout=run2.stdout, stderr=run2.stderr, files=[])

    # Step 3: Build report (auto-events if none)
    report_path = f"{outprefix}_owner_report.html"
    report_args = [sys.executable, REPORTER, f"{outprefix}_stand_summary.csv", prices_path, report_path]
    # events (optional)
    if events_path:
        report_args.append(events_path)
    else:
        report_args.append("")  # placeholder
    report_args += [owner, tract, discount]
    # pass calibration & species for product scaling
    if calibration_path:
        report_args += [calibration_path, species_col]

    run3 = subprocess.run(report_args, capture_output=True, text=True)
    if run3.returncode != 0:
        return render_template("result.html", error="Report builder failed", stdout=run3.stdout, stderr=run3.stderr, files=[])

    # Collect output files to show links
    files = []
    for fn in os.listdir(workdir):
        files.append({"name": fn, "url": url_for("download_file", uid=uid, filename=fn)})
    files = sorted(files, key=lambda x: x["name"])
    return render_template("result.html",
                           error=None,
                           stdout="\n".join([run1.stdout, run2.stdout, run3.stdout]),
                           stderr="\n".join([run1.stderr, run2.stderr, run3.stderr]),
                           files=files,
                           report_url=url_for("download_file", uid=uid, filename=os.path.basename(report_path)))

@app.route("/download/<uid>/<path:filename>")
def download_file(uid, filename):
    directory = os.path.join(OUT_DIR, uid)
    return send_from_directory(directory, filename, as_attachment=False)

@app.route("/health")
def health():
    return {"ok": True, "time": datetime.utcnow().isoformat()}

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8000"))
    app.run(host="0.0.0.0", port=port, debug=False)
