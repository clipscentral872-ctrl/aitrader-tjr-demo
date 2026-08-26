@echo off
REM Sequential overnight data run. Scheduled rather than backgrounded, because
REM background jobs die when the Claude session ends and this must survive it.
cd /d "C:\Users\chris\AITrader"
echo. >> "results\overnight.log"
echo ===== overnight started %DATE% %TIME% ===== >> "results\overnight.log"
python overnight.py >> "results\overnight.log" 2>&1
echo ===== overnight ended %DATE% %TIME% ===== >> "results\overnight.log"
