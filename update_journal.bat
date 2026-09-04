@echo off
REM One click after each session: read any new TradingView exports sitting in
REM journal_data, fold them into the running record, redraw the page, open it.
title Trade Blotter
cd /d "C:\Users\chris\AITrader"

echo.
echo   Reading exports from journal_data ...
echo.
python tradejournal.py
if errorlevel 1 goto failed

python journal_render.py
if errorlevel 1 goto failed

start "" "C:\Users\chris\AITrader\journal_data\journal.html"
echo.
echo   Done. The journal is open in your browser.
timeout /t 6 >nul
exit /b 0

:failed
echo.
echo   Something went wrong above. Leave this window open and send me the text.
pause
exit /b 1
