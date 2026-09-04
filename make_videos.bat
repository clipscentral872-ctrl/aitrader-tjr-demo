@echo off
REM Rebuilds the For Learning video library. This one is slow, minutes per cut,
REM so it is kept separate from the everyday journal update.
title Traders Diary - Build Videos
cd /d "C:\Users\chris\AITrader"

echo.
echo   Building the For Learning library. This takes a while.
echo.
python tradejournal.py
if errorlevel 1 goto failed

python journal_render.py
python replay\make_videos.py
if errorlevel 1 goto failed

start "" "C:\Users\chris\AITrader\For Learning"
echo.
echo   Done.
pause
exit /b 0

:failed
echo.
echo   Something went wrong above. Leave this window open and send me the text.
pause
exit /b 1
