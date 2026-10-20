# RoadLens Chennai (prototype v0.2)

Pick an area of Chennai, see its road types, likely bottlenecks and one suggested fix for each.

## Run (Windows PowerShell)
    python -m pip install -r requirements.txt
    python -m streamlit run app.py
Then open http://localhost:8501

## Notes
- The first time you open an area it downloads OpenStreetMap data (internet needed, 20-60 seconds). It is then saved in data/ and works offline.
- Before the demo, click each area you plan to show once, so it is cached.
- Technical settings, local data entry and method notes are in the "Technical details" tab.
- Screening prototype only. Not field-validated. Map data (c) OpenStreetMap contributors.
