import os, uuid, json
from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for, send_from_directory, flash, jsonify
from werkzeug.utils import secure_filename
from flask_cors import CORS
import pandas as pd
import subprocess
import sys

# ---------- App init / config ----------
app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY","dev-secret")
app.config["MAX_CONTENT_LENGTH"] = 100 * 1024 * 1024  # 100 MB uploads
CORS(app, resources={r"/api/*": {"origins": [
    "https://app.canopy.yourdomain.com",
    "http://localhost:3000"
]}})

# ---------- Simple bearer auth for API ----------
API_TOKEN = os.environ.get("CANOPY_API_TOKEN")

def require_token():
    if not API_TOKEN:
        return None
    auth = request.headers.get("Authorization","")
    if not auth.startswith("Bearer "):
        return "Missing bearer token"
    if auth.split(" ",1)[1] != API_TOKEN:
        return "Invalid token"
    return None

# ---------- Paths & constants ----------
ROOT = os.path.dirname(os.path.abspath(__file__))
UPLOAD_DIR = os.path.join(ROOT, "uploads")
OUT_DIR = os.path.join(ROOT, "outputs")
os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(OUT_DIR, exist_ok=True)

PIPE_DIR = os.path.join(ROOT, "canopy_pipeline")
VALIDATOR = os.path.join(PIPE_DIR, "validator.py")
AGGREGATOR = os.path.join(PIPE_DIR, "stand_aggregator.py")
REPORTER = os.path.join(PIPE_DIR, "owner_report_build_v3plus.py")
CONTRACT = os.path.join(PIPE_DIR, "treesum_import_contract.json")
ALLOWED_EXTS = {"xlsx","xlsm","csv","json"}

def allowed_file(filename):
    return "." in filename and filename.rsplit(".",1)[1].lower() in ALLOWED_EXTS

# ---------- Shared pipeline runner ----------
def run_pipeline(req):
    tree_file = req.files.get("treesum")
    prices_file = req.files.get("prices")
    cruise_type = req.form.get("cruise_type","Plot")
    size_value = req.form.get("size_value","0.1").strip()
    owner = req.form.get("owner","Owner").strip() or "Owner"
    tract = req.form.get("tract","Tract").strip() or "Tract"
    discount = req.form.get("discount","5").strip() or "5"

    events_file = req.files.get("events")
    calibration_file = req.files.get("calibration")
    species_col = req.form.get("species_col","CalSpecies").strip() or "CalSpecies"

    if not tree_file or not allowed_file(tree_file.filename):
        return {"error":"Please upload a TreeSum file (.xlsx/.xlsm/.csv)."}
    if not prices_file or not allowed_file(prices_file.filename):
        return {"error":"Please upload a prices JSON file."}
    try:
        float(size_value)
    except Exception:
        return {"error":"Plot size (ac) or BAF must be numeric."}

    uid = datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:8]
    workdir = os.path.join(OUT_DIR, uid)
    os.makedirs(workdir, exist_ok=True)

    tree_path = os.path.join(workdir, secure_filename(tree_file.filename)); tree_file.save(tree_path)
    prices_path = os.path.join(workdir, secure_filename(prices_file.filename)); prices_file.save(prices_path)

    events_path = ""
    if events_file and events_file.filename and allowed_file(events_file.filename):
        events_path = os.path.join(workdir, secure_filename(events_file.filename)); events_file.save(events_path)

    calibration_path = ""
    if calibration_file and calibration_file.filename and allowed_file(calibration_file.filename):
        calibration_path = os.path.join(workdir, secure_filename(calibration_file.filename)); calibration_file.save(calibration_path)

    outprefix = os.path.join(workdir, "out")

    # Step 1: validate
    contract_path = CONTRACT
    run1 = subprocess.run([sys.executable, VALIDATOR, tree_path, contract_path, outprefix], capture_output=True, text=True)
    if run1.returncode != 0:
        return {"error":"Validator failed", "stdout":run1.stdout, "stderr":run1.stderr, "job_id":uid}

    # Step 2: aggregate
    size_val = str(float(size_value))
    agg_args = [sys.executable, AGGREGATOR, f"{outprefix}_canopy_treelevel.csv", outprefix, cruise_type, size_val]
    if calibration_path:
        agg_args += ["--calibration", calibration_path, "--species_col", species_col]
    run2 = subprocess.run(agg_args, capture_output=True, text=True)
    if run2.returncode != 0:
        return {"error":"Aggregator failed", "stdout":run2.stdout, "stderr":run2.stderr, "job_id":uid}

    # Step 3: report
    report_path = f"{outprefix}_owner_report.html"
    report_args = [sys.executable, REPORTER, f"{outprefix}_stand_summary.csv", prices_path, report_path]
    report_args.append(events_path if events_path else "")
    report_args += [owner, tract, discount]
    if calibration_path:
        report_args += [calibration_path, species_col]
    run3 = subprocess.run(report_args, capture_output=True, text=True)
    if run3.returncode != 0:
        return {"error":"Report builder failed", "stdout":run3.stdout, "stderr":run3.stderr, "job_id":uid}

    files = []
    for fn in os.listdir(workdir):
        files.append({"name": fn, "url": url_for("download_file", uid=uid, filename=fn)})

    return {
        "error": None,
        "job_id": uid,
        "report_url": url_for("download_file", uid=uid, filename=os.path.basename(report_path)),
        "files": sorted(files, key=lambda x: x["name"]),
        "stdout": "\n".join([run1.stdout, run2.stdout, run3.stdout]),
        "stderr": "\n".join([run1.stderr, run2.stderr, run3.stderr]),
    }

# ---------- Routes ----------
@app.route("/")
def index():
    return render_template("index.html")

@app.route("/process", methods=["POST"])
def process():
    res = run_pipeline(request)
    if res["error"]:
        return render_template("result.html", error=res["error"], stdout=res.get("stdout",""), stderr=res.get("stderr",""), files=[])
    return render_template("result.html", error=None, stdout=res.get("stdout",""), stderr=res.get("stderr",""),
                           files=res["files"], report_url=res["report_url"])

@app.route("/download/<uid>/<path:filename>")
def download_file(uid, filename):
    directory = os.path.join(OUT_DIR, uid)
    return send_from_directory(directory, filename, as_attachment=False)

@app.post("/api/process")
def api_process():
    err = require_token()
    if err:
        return jsonify({"error": err}), 401
    res = run_pipeline(request)
    status = 200 if not res["error"] else 400
    if res.get("report_url"):
        res["report_url"] = request.url_root.rstrip("/") + res["report_url"]
        for f in res.get("files", []):
            f["url"] = request.url_root.rstrip("/") + f["url"]
    return jsonify(res), status

@app.route("/health")
def health():
    return {"ok": True, "time": datetime.utcnow().isoformat()}

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8000"))
    app.run(host="0.0.0.0", port=port, debug=False)

