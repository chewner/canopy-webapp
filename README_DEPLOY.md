
# Canopy Cruise → Report (Hosted Web App)

## Quick Deploy Options

### Option A — Render.com (no-Docker)
1. Create a **New Web Service**.
2. Connect your repo or upload this folder as a repo.
3. **Runtime:** Python 3.11
4. **Build Command:** `pip install -r requirements.txt`
5. **Start Command:** `gunicorn app:app -c gunicorn.conf.py`
6. **Instance Type:** pick any (x-small works to start).
7. Add env var: `SECRET_KEY` (random string).

### Option B — Railway.app / Fly.io / Heroku
- Use the provided `Procfile`, `gunicorn.conf.py`, and `requirements.txt`.
- Start command: `gunicorn app:app -c gunicorn.conf.py`
- Set environment variable `SECRET_KEY`.

### Option C — Docker anywhere (AWS/EC2, Lightsail, Azure, GCP)
```bash
docker build -t canopy-web .
docker run -p 8000:8000 -e SECRET_KEY=$(python -c "import secrets; print(secrets.token_hex(16))") canopy-web
```
Visit http://localhost:8000

## Using the App
1. Open `/` and upload:
   - **TreeSum** file (.xlsx/.xlsm/.csv)
   - **Prices** JSON (edit your numbers)
   - Optional: **Events CSV**, **Calibration JSON**
2. Choose **Cruise Type** (Plot/Point) and enter **Plot Size (ac)** or **BAF**.
3. Enter **Owner**, **Tract**, **Discount %**.
4. Click **Generate Report**.
5. You’ll get links to the owner HTML report and intermediate CSVs.

## Files & Folders
- `app.py` — Flask server (web UI)
- `canopy_pipeline/` — pipeline scripts:
  - `validator.py`
  - `stand_aggregator.py`
  - `owner_report_build_v3plus.py`
  - `treesum_import_contract.json`
- `templates/` — index & results pages
- `static/style.css` — minimal styling
- `requirements.txt` — Python deps
- `Procfile`, `gunicorn.conf.py` — production server
- `Dockerfile` — containerized deployment

## Persistence & Storage
- Uploaded files and outputs go to `./uploads` and `./outputs`.
- For production, mount persistent volumes or wire S3 for long-term storage (optional).

## Security Notes
- This app processes files server-side. Restrict access if needed (basic auth or IP allowlist).
- Consider private deployments for customer data.

## Version
- Engine: v3plus (auto-events, NPV/IRR, calibration with product scaling, QA appendix)
