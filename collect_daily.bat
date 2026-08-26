@echo off
REM Harvests the rolling 60-day futures window into the permanent store.
REM Safe to run any number of times - bars are de-duplicated by timestamp.
cd /d "C:\Users\chris\AITrader"
python collector.py >> "data\store\collector.log" 2>&1
