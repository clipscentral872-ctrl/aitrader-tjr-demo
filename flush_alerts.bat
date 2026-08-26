@echo off
REM Sends anything that was raised while Chris was outside 15:00-21:30 SAST.
cd /d "C:\Users\chris\AITrader"
python notify.py --flush >> "results\alerts.log" 2>&1
