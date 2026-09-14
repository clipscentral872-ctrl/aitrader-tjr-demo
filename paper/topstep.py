"""Topstep's $50K Trading Combine, played by its own rules on the paper account.

WHY THIS EXISTS
---------------
Chris asked what it would cost to run this for real and how much to put in. The
cheapest real route is a prop firm evaluation: the most that can be lost is the
fee. But a prop account is not a normal account with a smaller balance. It is
killed by a trailing drawdown of $2,000, which is four losing trades at the size
the main paper book trades. So before anyone pays, the robot plays the Combine
by the letter, on the same bars as the other books, and we watch it pass or
fail.

THE RULES, FROM TOPSTEP'S HELP CENTRE (checked 14 September 2026)
----------------------------------------------------------------
  Start           $50,000
  Profit target   $3,000
  Max Loss Limit  $2,000 below the start, so $48,000. It TRAILS the end of day
                  balance, never moves down, and locks for good once it reaches
                  the starting balance. It is watched in real time, open losses
                  included, and touching it ends the attempt at once.
  Daily Loss      $1,000. Optional in the Combine, and used here because it only
  Limit           ever protects. Hitting it flattens you for the rest of the day
                  and is NOT a failure.
  Consistency     the best day must be no more than half the total profit. A big
                  day does not fail you; it raises the target to twice that day.
  Size            50 micro contracts at most.
  Trading day     5 PM to 3:10 PM Central, which is 18:00 to 16:10 New York.
                  Anything still open at 16:10 is flattened.
  Passing         in as few as two trading days, once the target is met.
  Price           $49 a month, $49 a reset, and one free reset each time the
                  subscription renews. $149 to activate once passed.

Everything here is pure: it takes the book and a time and changes the book. It
never fetches, so it can be tested on made up days.
"""
import datetime as dt
import math

START = 50_000.0
TARGET = 3_000.0
MLL_GAP = 2_000.0
DLL = 1_000.0
MAX_MICROS = 50
DAY_START_H = 18              # New York hour the Topstep day begins, 5 PM Central
FLAT_BY = dt.time(16, 10)     # New York, 3:10 PM Central
MIN_DAYS = 2
MONTHLY_FEE = 49.0
RESET_FEE = 49.0
ACTIVATION_FEE = 149.0


def ts_day(when_ny):
    """The Topstep trading day a New York time belongs to. The day starts at
    18:00 the evening before, so 20:00 on a Monday is Tuesday's session."""
    return (when_ny + dt.timedelta(hours=24 - DAY_START_H)).date()


def must_be_flat(when_ny):
    """From 16:10 to the 18:00 open nothing may be held or opened."""
    t = when_ny.time()
    return FLAT_BY <= t < dt.time(DAY_START_H, 0)


def fresh(book, attempt, when_iso):
    """A new attempt: the account back to $50,000 and every limit reset."""
    book["equity"] = START
    book["position"] = None
    book["ts"] = {
        "attempt": attempt, "status": "active", "reason": None,
        "attempt_started": when_iso, "mll": START - MLL_GAP,
        "day": None, "day_start": START, "best_day": 0.0,
        "days_traded": 0, "traded_today": False, "dll_hit": False,
        "trades_in_attempt": 0,
        "history": (book.get("ts") or {}).get("history", []),
        "first_started": (book.get("ts") or {}).get("first_started", when_iso),
    }
    return book


def need(ts):
    """The profit target after the consistency rule: never below $3,000, and
    twice the best day once a day has earned more than half of it."""
    return max(TARGET, 2 * ts["best_day"])


def close_day(book):
    """Settle the day that is ending: trail the loss limit, note the best day,
    and see whether the target has been met."""
    ts = book["ts"]
    # Once a day only. Settling the same day twice counted it as two trading
    # days and could pass an attempt a day early.
    if ts["day"] is None or ts.get("settled") == ts["day"]:
        return None
    ts["settled"] = ts["day"]
    pnl = book["equity"] - ts["day_start"]
    if ts["traded_today"]:
        ts["days_traded"] += 1
    ts["best_day"] = max(ts["best_day"], pnl)
    # It follows the end of day balance up and never down, and it stops for
    # good at the starting balance.
    ts["mll"] = max(ts["mll"], min(book["equity"] - MLL_GAP, START))
    if ts["status"] == "active":
        profit = book["equity"] - START
        if profit >= need(ts) and ts["days_traded"] >= MIN_DAYS:
            ts["status"] = "passed"
            ts["reason"] = (f"profit ${profit:,.0f} met the ${need(ts):,.0f} target "
                            f"in {ts['days_traded']} trading days")
            return "passed"
    return None


def roll(book, day, when_iso):
    """Move the book onto Topstep day `day`, settling the one before it. An
    attempt that passed or failed is filed away and a fresh one starts with the
    new day, the way a reset gives you a fresh $50,000 at the next session."""
    ts = book["ts"]
    if ts["day"] == day:
        return None
    event = close_day(book)
    if ts["status"] != "active":
        ts["history"].append({
            "attempt": ts["attempt"], "result": ts["status"],
            "reason": ts["reason"], "started": ts["attempt_started"],
            "ended": when_iso, "days": ts["days_traded"],
            "trades": ts["trades_in_attempt"],
            "pnl": round(book["equity"] - START, 2),
        })
        fresh(book, ts["attempt"] + 1, when_iso)
        ts = book["ts"]
    ts["day"] = day
    ts["day_start"] = book["equity"]
    ts["traded_today"] = False
    ts["dll_hit"] = False
    return event


def gate(book, when_ny):
    """Whether this account may open a trade now, and if not, why."""
    ts = book["ts"]
    if ts["status"] == "failed":
        return False, "Combine failed: waiting for the reset at the next session"
    if ts["status"] == "passed":
        return False, "Combine passed: a new attempt starts at the next session"
    if ts["dll_hit"]:
        return False, "daily loss limit hit, done until the next session"
    if must_be_flat(when_ny):
        return False, "after 16:10 New York, when Topstep flattens everything"
    return True, "ok"


def contracts(risk_cash, per_contract_risk):
    """How many micros a trade gets: what the risk allows, never more than 50,
    and none at all if even one would risk more than it should."""
    if per_contract_risk <= 0:
        return 0
    return int(min(MAX_MICROS, risk_cash // per_contract_risk))


def limit_prices(book, pos, point_value):
    """The prices at which this position would touch the Max Loss Limit and
    the Daily Loss Limit, counting the open loss the way Topstep does."""
    ts = book["ts"]
    per_point = pos["size"] * point_value
    if per_point <= 0:
        return None, None
    room_mll = book["equity"] - ts["mll"]
    room_dll = DLL + (book["equity"] - ts["day_start"])
    sign = -1 if pos["side"] == "long" else 1
    mll_px = pos["entry"] + sign * room_mll / per_point
    dll_px = pos["entry"] + sign * room_dll / per_point
    return mll_px, dll_px


def after_close(book, outcome):
    """Record what a close means for the Combine."""
    ts = book["ts"]
    ts["trades_in_attempt"] += 1
    if outcome == "mll" or book["equity"] <= ts["mll"]:
        ts["status"] = "failed"
        ts["reason"] = (f"touched the Max Loss Limit at ${ts['mll']:,.0f} "
                        f"with the account at ${book['equity']:,.0f}")
    elif outcome == "dll" or book["equity"] - ts["day_start"] <= -DLL:
        ts["dll_hit"] = True


def fees(book, now_iso):
    """What these attempts would have cost for real: $49 a month, and $49 for
    each reset beyond the free one that comes with every renewal."""
    ts = book["ts"]
    try:
        t0 = dt.datetime.fromisoformat(ts["first_started"])
        t1 = dt.datetime.fromisoformat(now_iso)
        months = max(1, math.ceil((t1 - t0).days / 30 + 1e-9))
    except Exception:                                        # noqa: BLE001
        months = 1
    fails = sum(1 for h in ts["history"] if h["result"] == "failed")
    if ts["status"] == "failed":
        fails += 1
    paid_resets = max(0, fails - (months - 1))
    return {"months": months, "fails": fails,
            "subscription": months * MONTHLY_FEE,
            "resets": paid_resets * RESET_FEE,
            "total": months * MONTHLY_FEE + paid_resets * RESET_FEE}


def summary(book, now_iso):
    """The small public view the web app shows."""
    ts = book["ts"]
    hist = ts["history"]
    return {
        "attempt": ts["attempt"], "status": ts["status"], "reason": ts["reason"],
        "equity": round(book["equity"], 2), "mll": round(ts["mll"], 2),
        "room": round(book["equity"] - ts["mll"], 2),
        "profit": round(book["equity"] - START, 2), "need": round(need(ts), 2),
        "best_day": round(ts["best_day"], 2), "days_traded": ts["days_traded"],
        "day_pnl": round(book["equity"] - ts["day_start"], 2),
        "dll_hit": ts["dll_hit"], "trades": ts["trades_in_attempt"],
        "passes": sum(1 for h in hist if h["result"] == "passed"),
        "fails": sum(1 for h in hist if h["result"] == "failed"),
        "history": hist[-10:], "fees": fees(book, now_iso),
        "started": ts["attempt_started"],
    }
