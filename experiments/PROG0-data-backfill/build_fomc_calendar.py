#!/usr/bin/env python3
"""PROG-0 — build the FOMC event calendar 2020-2025 from the Federal Reserve's
own published pages (directly reachable from this box):

  - https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm
    (2021-2027 meeting panels)
  - https://www.federalreserve.gov/monetarypolicy/fomchistorical2020.htm
    (2020, incl. the March unscheduled meetings and the cancelled Mar 17-18)

Convention (matches committed fomc_2026.csv): each row is the SECOND DAY of a
two-day meeting — the statement/press-conference day — which is the event day
for the entry_gate fomc_blackout. 2020's single-day unscheduled emergency
meetings (Mar 2, Mar 15) are included as their own dates, marked unscheduled;
the cancelled Mar 17-18 meeting is excluded; notation votes are excluded
(administrative actions, not statement-day events — the Mar-23-2020 facilities
announcement is noted in a comment for researchers).

Validation: exactly 8 scheduled meetings per year; every event date is
weekday-checked (2020-03-15 was a Sunday — kept, flagged in notes, since the
market event window is the next session); the 2026 panel parsed from the same
page must exactly match the committed fomc_2026.csv (cross-check).

Usage: python3 experiments/PROG0-data-backfill/build_fomc_calendar.py
"""
from __future__ import annotations

import re
import sys
import urllib.request
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
OUT = ROOT / "compass" / "orchestrator" / "calendars" / "fomc_2020_2025.csv"
EXISTING_2026 = ROOT / "compass" / "orchestrator" / "calendars" / "fomc_2026.csv"

CAL = "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm"
HIST2020 = "https://www.federalreserve.gov/monetarypolicy/fomchistorical2020.htm"

MONTHS = {m: i + 1 for i, m in enumerate(
    ["January", "February", "March", "April", "May", "June", "July",
     "August", "September", "October", "November", "December"])}
MONTHS.update({m[:3]: v for m, v in list(MONTHS.items())})  # Jan/Feb style abbreviations


def fetch(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read().decode("utf-8", errors="ignore")


def parse_calendars(page: str) -> dict:
    """-> {year: [(iso_second_day, 'Mon d1-d2' label, sep_flag)]} for 2021+."""
    out = {}
    sections = re.split(r"(20\d\d) FOMC Meetings", page)
    for i in range(1, len(sections) - 1, 2):
        year = int(sections[i])
        body = sections[i + 1]
        meetings = []
        pairs = re.findall(
            r'fomc-meeting__month[^>]*>\s*(?:<strong>)?([A-Za-z/]+)(?:</strong>)?\s*</div>'
            r'.*?fomc-meeting__date[^>]*>([^<]+)<',
            body, re.S)
        for mon, dd in pairs:
            dd = dd.strip()
            sep = "*" in dd
            dd_clean = dd.replace("*", "").strip()
            if "unscheduled" in dd_clean.lower() or "notation" in dd_clean.lower():
                continue
            m = re.match(r"^(\d{1,2})-(\d{1,2})$", dd_clean)
            if not m:
                continue
            d2 = int(m.group(2))
            mon2 = mon.split("/")[-1]  # cross-month meetings end in the second month
            if mon2 not in MONTHS:
                continue
            meetings.append((date(year, MONTHS[mon2], d2).isoformat(),
                             f"{mon} {dd_clean}", sep))
        out[year] = meetings
    return out


def parse_2020(page: str) -> list:
    """-> [(iso_event_day, label, unscheduled_flag)] from the historical page."""
    out = []
    for h in re.findall(r"<h5[^>]*>(.*?)</h5>", page, re.S):
        h = re.sub(r"<[^>]+>", "", h).strip()
        m = re.match(r"^([A-Za-z]+) ([\d-]+)( \((unscheduled|cancelled|notation vote)\))?"
                     r"( Meeting)? - 2020$", h)
        if not m:
            continue
        mon, days, _, kind = m.group(1), m.group(2), m.group(3), m.group(4)
        if kind in ("cancelled", "notation vote"):
            continue
        d2 = int(days.split("-")[-1])
        out.append((date(2020, MONTHS[mon], d2).isoformat(),
                    f"{mon} {days}", kind == "unscheduled"))
    return out


def main() -> None:
    cal = parse_calendars(fetch(CAL))
    y2020 = parse_2020(fetch(HIST2020))

    # ── validation ──
    sched_2020 = [e for e in y2020 if not e[2]]
    assert len(sched_2020) == 7, f"2020: {len(sched_2020)} scheduled (7 expected — Mar cancelled)"
    assert len([e for e in y2020 if e[2]]) == 2, "2020: expected 2 unscheduled meetings"
    for y in range(2021, 2026):
        n = len(cal.get(y, []))
        assert n == 8, f"{y}: {n} meetings parsed (8 expected)"

    # cross-check parsed 2026 vs committed fomc_2026.csv
    committed = [l.split(",")[0] for l in EXISTING_2026.read_text().splitlines()
                 if l.startswith("20")]
    parsed_2026 = sorted(d for d, _, _ in cal.get(2026, []))
    if parsed_2026 != sorted(committed):
        print(f"FATAL: 2026 cross-check failed:\n parsed   {parsed_2026}\n committed {sorted(committed)}",
              file=sys.stderr)
        sys.exit(1)
    print(f"[xcheck] 2026 panel matches committed fomc_2026.csv 8/8")

    rows = []
    for d, label, unsched in sorted(y2020):
        note = f"FOMC meeting ({label})"
        if unsched:
            wd = date.fromisoformat(d).weekday()
            note = f"FOMC UNSCHEDULED emergency meeting ({label} 2020)"
            if wd >= 5:
                note += " — Sunday announcement; market event window = next session"
        rows.append((d, note))
    for y in range(2021, 2026):
        for d, label, sep in sorted(cal[y]):
            rows.append((d, f"FOMC meeting ({label})" + (" + SEP" if sep else "")))

    # weekday sanity (allow the flagged 2020-03-15 Sunday)
    for d, note in rows:
        if date.fromisoformat(d).weekday() >= 5:
            assert "Sunday" in note, f"unexpected weekend event {d}"

    lines = [
        "# compass/orchestrator/calendars/fomc_2020_2025.csv",
        "# Source: Federal Reserve published FOMC calendars, fetched 2026-07-12:",
        "#   https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm (2021-2025)",
        "#   https://www.federalreserve.gov/monetarypolicy/fomchistorical2020.htm (2020)",
        "# Built by experiments/PROG0-data-backfill/build_fomc_calendar.py.",
        "# Each row is the SECOND DAY of a two-day meeting (statement/press-conf",
        "# day) per the fomc_2026.csv convention. 2020 includes the Mar-2 and",
        "# Mar-15 unscheduled emergency meetings; the cancelled Mar 17-18 meeting",
        "# is excluded; notation votes (2020: Mar 19/23/31, Aug 27; 2025: Aug 22)",
        "# are excluded — note the 2020-03-23 facilities announcement moved",
        "# markets but was not a statement-day meeting.",
        "# Cross-check: the same page's 2026 panel reproduces the committed",
        "# fomc_2026.csv exactly (8/8).",
        "#",
        "date,notes",
    ]
    lines += [f"{d},{note}" for d, note in rows]
    OUT.write_text("\n".join(lines) + "\n")
    print(f"[done] wrote {len(rows)} rows -> {OUT}")
    for d, note in rows:
        print(" ", d, note)


if __name__ == "__main__":
    main()
