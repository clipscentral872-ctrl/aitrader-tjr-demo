@echo off
REM One window with all three tabs. Rebuilds the pages first so the Diary picks
REM up any new exports, then serves them so the Demo tab can reach live prices.
title Traders Diary
cd /d "C:\Users\chris\AITrader"

echo.
echo   Building the tabs...
echo.
python build_all.py
if errorlevel 1 goto failed

python app.py
goto :eof

:failed
echo.
echo   Something went wrong above. Leave this window open and send me the text.
pause
