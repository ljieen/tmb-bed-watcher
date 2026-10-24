#!/usr/bin/env python3
"""Watch montourdumontblanc.com hut availability and email when a watched night opens up.

Usage:
  python3 watch.py                 # normal run: fetch, compare with state, email on openings, save state
  python3 watch.py --dry-run       # fetch and print watched nights; no email, no state saved
  python3 watch.py --test-email    # send a sample email with the current status of watched nights
  python3 watch.py --simulate      # pretend every currently-available watched night was full, run the
                                   # real alert path (sends email), don't save state

Email settings come from env vars: GMAIL_USER, GMAIL_APP_PASSWORD, ALERT_TO (defaults to GMAIL_USER).
"""
import argparse
import csv
import html
import json
import os
import re
import smtplib
import sys
import time
import urllib.request
from datetime import datetime, timezone
from email.message import EmailMessage
from pathlib import Path

URL = "https://www.montourdumontblanc.com/en/availability"
SITE = "https://www.montourdumontblanc.com"
HERE = Path(__file__).resolve().parent
WATCH_FILE = HERE / "watch.json"
STATE_FILE = HERE / "state.txt"        # every hut/night status, one per line (for diffing)
CHANGES_FILE = HERE / "changes.csv"    # every change seen across all huts (for spotting release patterns)

CARD_RE = re.compile(r'<h3 class="refuge-card__title font-titre">([^<]+)</h3>')
CELL_RE = re.compile(
    r'<(?:a|span) class="cal-cell cal-cell--(\w+)"(?: href="([^"]+)")? title="(\d\d/\d\d/\d{4}) — ([^"]+)"'
)


def fetch(retries=3):
    req = urllib.request.Request(URL, headers={"User-Agent": "Mozilla/5.0 (tmb-bed-watcher; personal use)"})
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                return r.read().decode("utf-8", errors="ignore")
        except Exception as e:
            if attempt == retries - 1:
                raise
            print(f"fetch failed ({e}), retrying...")
            time.sleep(20)


def parse(page):
    """-> {(hut, 'DD/MM/YYYY'): (status, title_text, booking_url_or_'')}"""
    cells = {}
    cards = list(CARD_RE.finditer(page))
    for i, card in enumerate(cards):
        hut = html.unescape(card.group(1)).strip()
        end = cards[i + 1].start() if i + 1 < len(cards) else len(page)
        for status, href, date, text in CELL_RE.findall(page, card.end(), end):
            if status in ("past", "empty"):
                continue
            cells[(hut, date)] = (status, html.unescape(text), SITE + href if href else "")
    if len(cells) < 1000:
        sys.exit(f"Only parsed {len(cells)} cells - the site layout probably changed. Fix the regexes.")
    return cells


def load_state():
    state = {}
    if STATE_FILE.exists():
        for line in STATE_FILE.read_text(encoding="utf-8").splitlines():
            hut, date, text = line.split("\t")
            state[(hut, date)] = text
    return state


def save_state(cells):
    lines = sorted(f"{h}\t{d}\t{v[1]}" for (h, d), v in cells.items())
    STATE_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")


def log_changes(old, cells):
    if not old:
        return 0
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    rows = [(now, h, d, old.get((h, d), ""), v[1]) for (h, d), v in cells.items() if old.get((h, d)) != v[1]]
    new_file = not CHANGES_FILE.exists()
    with CHANGES_FILE.open("a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if new_file:
            w.writerow(["seen_at_utc", "hut", "night", "before", "after"])
        w.writerows(sorted(rows))
    return len(rows)


def send_email(subject, body):
    user, pw = os.environ.get("GMAIL_USER"), os.environ.get("GMAIL_APP_PASSWORD")
    to = os.environ.get("ALERT_TO") or user
    if not (user and pw):
        print("GMAIL_USER / GMAIL_APP_PASSWORD not set - would have sent:\n" + subject + "\n" + body)
        return
    msg = EmailMessage()
    msg["Subject"], msg["From"], msg["To"] = subject, user, to
    msg.set_content(body)
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as s:
        s.login(user, pw)
        s.send_message(msg)
    print(f"Email sent to {to}: {subject}")


def describe(w, cell):
    status, text, link = cell if cell else ("missing", "not listed", "")
    line = f"{w['date']}  {w['hut']}  ({w.get('note', '')}): {text}"
    return line + (f"\n    Book: {link}" if link else "")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--test-email", action="store_true")
    ap.add_argument("--simulate", action="store_true")
    args = ap.parse_args()

    watch = json.loads(WATCH_FILE.read_text(encoding="utf-8"))["watch"]
    cells = parse(fetch())
    old = load_state()
    if args.simulate:
        old = dict(old)
        for w in watch:
            c = cells.get((w["hut"], w["date"]))
            if c and c[0] == "dispo":
                old[(w["hut"], w["date"])] = "Fully booked"

    summary = "\n".join(describe(w, cells.get((w["hut"], w["date"]))) for w in watch)
    print(summary)
    for w in watch:
        if (w["hut"], w["date"]) not in cells:
            print(f"WARNING: no cell for {w['hut']} on {w['date']} - check the name/date in watch.json")

    if args.dry_run:
        return
    if args.test_email:
        send_email("[TMB watcher] Test email - it works", "Current status of your watched nights:\n\n" + summary)
        return

    # A watched night "opens" when it is bookable now but wasn't at the last check.
    # No previous state (very first run) means no alerts, just a baseline.
    openings = []
    for w in watch:
        key = (w["hut"], w["date"])
        c = cells.get(key)
        before = old.get(key)
        if c and c[0] == "dispo" and before is not None and not before.endswith("available"):
            openings.append(describe(w, c) + f"\n    (was: {before})")

    if openings:
        body = (
            "Beds just opened up - book fast, they can go within minutes.\n\n"
            + "\n\n".join(openings)
            + "\n\nAll watched nights right now:\n\n" + summary
        )
        send_email(f"[TMB watcher] {len(openings)} bed opening(s)!", body)
    else:
        print("No new openings on watched nights.")

    if not args.simulate:
        n = log_changes(old, cells)
        print(f"{n} change(s) across all huts since last check.")
        save_state(cells)


if __name__ == "__main__":
    main()
