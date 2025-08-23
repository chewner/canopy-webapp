
- app.py (adds /api/process, token auth, CORS, shared runner)
- requirements.txt (adds Flask-Cors + numpy-financial)

On Render set:
- SECRET_KEY = <random string>
- CANOPY_API_TOKEN = <random string>

Deploy:
- Manual Deploy → Clear build cache & deploy

Test:
- POST to /api/process with Authorization: Bearer <CANOPY_API_TOKEN>
- Include form-data: treesum, prices, (optional events, calibration), cruise_type, size_value, owner, tract, discount, species_col
