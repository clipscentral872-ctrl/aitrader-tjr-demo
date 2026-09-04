@echo off
REM Daily top-up of market data. Yahoo only hands out about a week of
REM one-minute bars, so anything not collected inside that window is gone for
REM good. Run by Task Scheduler; also runs whenever the app is launched.
cd /d "C:\Users\chris\AITrader"
python collect_bars.py >> "data\collected\collect.log" 2>&1
