"""
slot.py
--------
GitHub's scheduler runs cron jobs HOURS late (your Tuesday post, scheduled for
8:00 PM IST, started at 1:00 AM IST). So the workflow is triggered EARLY and this
script makes the job publish at exactly the posting time instead.

  python scripts/slot.py gate   # should this run post today at all?  (writes proceed=true|false)
  python scripts/slot.py wait   # sleep until the posting time (returns at once if already past)

Rules for scheduled runs (manual runs always proceed and never wait):
  - only on posting days (Sat, Sun, Mon, Wed, Fri)
  - never twice in one IST day (two early triggers exist for redundancy)
  - if the posting time is more than MAX_WAIT_MIN away, skip: a later trigger will handle it
    (a job may not run longer than 6 hours)
"""
import json
import os
import sys
import time
from datetime import datetime, time as dtime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")
POST_DAYS = {5, 6, 0, 2, 4}      # Mon=0 ... Sat=5, Sun=6  ->  Sat, Sun, Mon, Wed, Fri
TARGET = dtime(20, 0)            # 8:00 PM IST
MAX_WAIT_MIN = 330
STATE_FILE = Path("content/state.json")


def target_for(now_ist):
    return datetime.combine(now_ist.date(), TARGET, tzinfo=IST)


def seconds_until_slot(now_ist):
    return max(0.0, (target_for(now_ist) - now_ist).total_seconds())


def decide(now_ist, event, last_posted_ist, max_wait_min=MAX_WAIT_MIN):
    """Returns (proceed, reason)."""
    if event != "schedule":
        return True, f"manual run ({event}): posting immediately"
    if now_ist.weekday() not in POST_DAYS:
        return False, f"{now_ist:%A} is not a posting day"
    if last_posted_ist == now_ist.date().isoformat():
        return False, "already posted today (IST)"
    wait_min = seconds_until_slot(now_ist) / 60
    if wait_min > max_wait_min:
        return False, (f"too early: {wait_min / 60:.1f}h until 8:00 PM IST; "
                       f"a later trigger will post")
    if wait_min > 0:
        return True, f"will wait {wait_min:.0f} min until 8:00 PM IST"
    late = (now_ist - target_for(now_ist)).total_seconds() / 60
    return True, f"already past 8:00 PM IST by {late:.0f} min: posting now"


def write_output(proceed):
    out = os.environ.get("GITHUB_OUTPUT")
    if out:
        with open(out, "a") as f:
            f.write(f"proceed={'true' if proceed else 'false'}\n")


def gate():
    state = json.loads(STATE_FILE.read_text()) if STATE_FILE.exists() else {}
    now = datetime.now(IST)
    proceed, reason = decide(now, os.environ.get("GITHUB_EVENT_NAME", "schedule"),
                             state.get("last_posted_ist"))
    print(f"[{now:%a %Y-%m-%d %H:%M} IST] proceed={proceed}: {reason}")
    write_output(proceed)


def wait():
    now = datetime.now(IST)
    left = seconds_until_slot(now)
    if left <= 0:
        print(f"[{now:%H:%M} IST] posting time already reached; not waiting.")
        return
    print(f"[{now:%H:%M} IST] waiting {left / 60:.0f} min for 8:00 PM IST...")
    while True:
        left = seconds_until_slot(datetime.now(IST))
        if left <= 0:
            break
        time.sleep(min(left, 300))
    print(f"[{datetime.now(IST):%H:%M:%S} IST] posting time reached.")


if __name__ == "__main__":
    {"gate": gate, "wait": wait}[sys.argv[1]]()
