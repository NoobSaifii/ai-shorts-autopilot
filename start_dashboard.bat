@echo off
cd /d "%~dp0"
echo Starting Analytics Dashboard...
echo Open browser at: http://localhost:8081
python -m uvicorn dashboard.app:app --port 8081 --log-level warning
pause
