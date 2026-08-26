# ---------------------------------------------------------------------------
#  Launch the TJR paper demo, independent of any Claude Code session.
#
#  A demo started from a working session dies when that session ends. That is
#  what happened on 2026-08-25: both runners were gone the next morning and the
#  log stopped at its launch moment, so a whole trading window was lost and the
#  zero trades it recorded proved nothing.
#
#  This replaces an earlier .bat version that used `wmic` for the date stamp.
#  wmic has been REMOVED in Windows 11 build 26200, so that launcher failed
#  silently with no log and no process. PowerShell gets the date natively.
#
#  Times are South African (UTC+2); New York is SAST minus 6.
#    London opens    03:00 NY = 09:00 SAST
#    New York closes 16:00 NY = 22:00 SAST
#  Started 08:55 SAST for 790 minutes, this covers the whole window.
# ---------------------------------------------------------------------------

$py   = "C:\Users\chris\AppData\Local\Python\pythoncore-3.14-64\python.exe"
$root = "C:\Users\chris\AITrader"
$logs = Join-Path $root "results\demo_logs"

if (-not (Test-Path $logs)) { New-Item -ItemType Directory -Path $logs -Force | Out-Null }

Set-Location $root
$stamp = Get-Date -Format "yyyy-MM-dd"
$log   = Join-Path $logs "demo_$stamp.txt"

"=== launched $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') ===" | Out-File -FilePath $log -Append -Encoding utf8

& $py demo_today.py `
    --window london_ny `
    --symbols mnq,mes `
    --equity 50000 `
    --risk 0.726 `
    --poll 60 `
    --minutes 790 *>> $log
