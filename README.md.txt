# Fed Tone Scanner

Local Streamlit app that:
- uploads TXT/PDF/DOCX
- extracts text
- scans hawkish/dovish phrases (overlapping matches supported)
- outputs scores + hit tables
- optional baseline diff
- downloads JSON and CSV

## 1) Setup (Python 3.11+)

Create a folder (example: `fed-tone-scanner`) and put these files inside:
- app.py
- scanner.py
- extractors.py
- keywords.yaml
- requirements.txt

## 2) Create a virtual environment

### Windows (PowerShell or cmd)
```bash
python -m venv .venv
.venv\Scripts\activate
