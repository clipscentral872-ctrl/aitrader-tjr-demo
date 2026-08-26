@echo off
REM ---------------------------------------------------------------------------
REM  Launch the TJR paper demo, independent of any Claude Code session.
REM
REM  A demo started from a working session dies when that session ends. That is
REM  what happened on 2026-08-25: both runners were gone the next morning and
REM  the log stopped at its launch moment, so a full trading window was lost and
REM  the zero trades it recorded proved nothing. This runs from Task Scheduler
REM  instead, so it survives.
REM
REM  Times are South African (UTC+2). New York is SAST minus 6.
REM    London opens   03:00 NY = 09:00 SAST
REM    New York closes 16:00 NY = 22:00 SAST
REM  Started 08:55 SAST for 790 minutes, this covers the whole London+NY window
REM  with a few minutes either side.
REM ---------------------------------------------------------------------------

set PY=C:\Users\chris\AppData\Local\Python\pythoncore-3.14-64\python.exe
set ROOT=C:\Users\chris\AITrader

cd /d "%ROOT%"

REM one log per day, so a bad session can be compared against a good one
for /f "tokens=2 delims==" %%I in ('wmic os get localdatetime /value') do set DT=%%I
set STAMP=%DT:~0,4%-%DT:~4,2%-%DT:~6,2%

"%PY%" demo_today.py ^
  --window london_ny ^
  --symbols mnq,mes ^
  --equity 50000 ^
  --risk 0.726 ^
  --poll 60 ^
  --minutes 790 ^
  >> "%ROOT%\results\demo_logs\demo_%STAMP%.txt" 2>&1
