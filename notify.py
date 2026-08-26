"""Telegram alerts, with quiet hours enforced rather than suggested.

Chris takes pings between 15:00 and 21:30 SAST. Anything raised outside that
window is queued to a file and flushed at the next opening, so a message is
never lost and never lands at 04:00.

One deliberate exception: a message marked urgent goes straight out. Urgent
means the system has stopped or is doing something it should not be, not that
a trade closed. Routine is not urgent, and treating it as urgent is how a
notification channel becomes noise that gets muted.

    python notify.py --test
    python notify.py --flush
    python notify.py --daily
"""
import argparse, json, os, sys
import datetime as dt
import urllib.request as u
import urllib.parse as up

ROOT = os.path.dirname(os.path.abspath(__file__))
QUEUE = os.path.join(ROOT, "config", "queued_alerts.json")
CFG = os.path.join(ROOT, "config", "telegram.json")

QUIET_START = dt.time(15, 0)     # SAST
QUIET_END = dt.time(21, 30)
SAST = dt.timezone(dt.timedelta(hours=2))


def creds():
    if os.path.exists(CFG):
        d = json.load(open(CFG, encoding="utf-8"))
        if d.get("token") and d.get("chat_id"):
            return d["token"], str(d["chat_id"])
    tok = os.environ.get("TELEGRAM_BOT_TOKEN")
    cid = os.environ.get("TELEGRAM_CHAT_ID")
    if tok and cid:
        return tok, cid
    # Chris already runs a bot for another project on this machine. Reusing it
    # saves a setup step; the token never leaves the machine except to Telegram.
    for p in (r"C:\Users\chris\clipfarmer\.env",):
        if os.path.exists(p):
            d = {}
            for line in open(p, encoding="utf-8", errors="ignore"):
                if "=" in line and not line.strip().startswith("#"):
                    k, v = line.split("=", 1)
                    d[k.strip()] = v.strip().strip('"').strip("'")
            if d.get("TELEGRAM_BOT_TOKEN") and d.get("TELEGRAM_CHAT_ID"):
                return d["TELEGRAM_BOT_TOKEN"], d["TELEGRAM_CHAT_ID"]
    return None, None


def in_window(now=None):
    t = (now or dt.datetime.now(SAST)).time()
    return QUIET_START <= t <= QUIET_END


def _queue_load():
    if os.path.exists(QUEUE):
        try:
            return json.load(open(QUEUE, encoding="utf-8"))
        except Exception:
            return []
    return []


def _queue_save(items):
    os.makedirs(os.path.dirname(QUEUE), exist_ok=True)
    json.dump(items, open(QUEUE, "w", encoding="utf-8"), indent=1)


def _send_now(text):
    tok, cid = creds()
    if not tok:
        print("no Telegram credentials; message not sent")
        return False
    body = up.urlencode({"chat_id": cid, "text": text[:4000],
                         "disable_web_page_preview": "true"}).encode()
    try:
        u.urlopen(u.Request(f"https://api.telegram.org/bot{tok}/sendMessage",
                            data=body), timeout=20).read()
        return True
    except Exception as e:
        print(f"telegram send failed: {type(e).__name__}: {str(e)[:80]}")
        return False


def send(text, urgent=False):
    """Send if the window is open, otherwise hold it for later."""
    if urgent or in_window():
        return _send_now(text)
    q = _queue_load()
    q.append({"at": dt.datetime.now(SAST).isoformat(), "text": text})
    _queue_save(q)
    print(f"outside the window, queued ({len(q)} waiting)")
    return False


def flush():
    """Send everything that has been waiting. Run this at the top of the window."""
    q = _queue_load()
    if not q:
        print("nothing queued")
        return 0
    if not in_window():
        print("still outside the window, holding")
        return 0
    joined = "\n\n".join(f"[{i['at'][11:16]}] {i['text']}" for i in q)
    header = f"{len(q)} update(s) from while you were away\n\n"
    if _send_now(header + joined):
        _queue_save([])
        print(f"sent {len(q)} queued message(s)")
        return len(q)
    return 0


def daily():
    """The end-of-day summary, short enough to read on a phone."""
    from report import build
    text = build(1, source="live")
    lines = [l for l in text.splitlines()
             if l.strip() and not l.startswith("=") and "generated" not in l]
    return send("\n".join(lines)[:3500])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--test", action="store_true")
    ap.add_argument("--flush", action="store_true")
    ap.add_argument("--daily", action="store_true")
    ap.add_argument("--message", default=None)
    ap.add_argument("--urgent", action="store_true")
    a = ap.parse_args()

    now = dt.datetime.now(SAST)
    print(f"SAST now {now:%H:%M}, window {'OPEN' if in_window(now) else 'CLOSED'} "
          f"({QUIET_START:%H:%M}-{QUIET_END:%H:%M})")
    tok, _ = creds()
    print(f"credentials: {'found' if tok else 'MISSING'}")

    if a.test:
        send("AITrader is connected. This is a test message, nothing has traded.")
    elif a.flush:
        flush()
    elif a.daily:
        daily()
    elif a.message:
        send(a.message, urgent=a.urgent)


if __name__ == "__main__":
    main()
