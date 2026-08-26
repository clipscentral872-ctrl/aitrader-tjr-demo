@echo off
REM Waits for the 1-minute evaluation, then runs step 4, then writes a summary.
REM Scheduled rather than backgrounded so it survives the Claude session ending.
cd /d "C:\Users\chris\AITrader"
set AITRADER_SCRATCH=C:\Users\chris\AppData\Local\Temp\claude\C--Users-chris--claude\e3b2b8e5-4fad-4b68-9c3d-f3fb91d3cb1a\scratchpad
python morning_report.py >> "results\morning_run.log" 2>&1
