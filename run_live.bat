@echo off
REM Paper-trades QQQ on the REAL Alpaca paper account across TJR's full
REM New York session, 15:30-22:00 SAST. The window MUST match the one the
REM backtest used; the engine default is a narrow three-hour slice and
REM trading a different window than the one measured makes the measurement
REM irrelevant.
REM
REM This is a test of the plumbing, not of the strategy. Nothing has cleared
REM evaluate.py, so the results here say whether orders fill, reconcile and
REM report correctly. They say nothing about whether this is profitable.
cd /d "C:\Users\chris\AITrader"
echo. >> "results\live.log"
echo ===== run started %DATE% %TIME% ===== >> "results\live.log"

python status.py >> "results\live.log" 2>&1

python live.py --mode live --broker alpaca --alpaca-symbol QQQ ^
  --window "TJR New York (08:30-18:00)" ^
  --equity 100000 --risk 0.5 --minutes 400 >> "results\live.log" 2>&1

REM close anything still open, write the day up, and send it
python -c "import sys; sys.path.insert(0,'.'); from paper.live_broker import LiveBroker; b=LiveBroker(symbol='QQQ'); b.api.cancel_all(); b.api.close_all(); print('book flattened')" >> "results\live.log" 2>&1
python report.py --days 1 --save >> "results\live.log" 2>&1
python notify.py --daily >> "results\live.log" 2>&1

echo ===== run ended %DATE% %TIME% ===== >> "results\live.log"
