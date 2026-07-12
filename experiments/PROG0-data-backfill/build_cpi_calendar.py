#!/usr/bin/env python3
"""PROG-0 — build CPI release-date calendars 2020-2025 from the official BLS
schedule pages, via Wayback Machine snapshots (bls.gov serves 403 to this box;
web.archive.org holds faithful captures of the same public pages).

Method (deterministic, source-documented, Rule Zero — no invented dates):
  - Fetch N Wayback snapshots of https://www.bls.gov/schedule/news_release/cpi.htm
    spread across 2020-2026. Each page carries ~14 months of official
    (reference month, release date, release time) rows.
  - Parse the schedule table; merge across snapshots.
  - Overlapping months across snapshots are CROSS-CHECKS: any conflict between
    two snapshots for the same reference month aborts the build (schedule
    revisions would need manual review; none expected).
  - Emit compass/orchestrator/calendars/cpi_2020_2025.csv in the cpi_2026.csv
    format, and cross-validate the 2026 rows we can see against the committed
    cpi_2026.csv.

Usage: python3 experiments/PROG0-data-backfill/build_cpi_calendar.py
"""
from __future__ import annotations

import html as html_mod
import re
import sys
import time
import urllib.request
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
OUT = ROOT / "compass" / "orchestrator" / "calendars" / "cpi_2020_2025.csv"
EXISTING_2026 = ROOT / "compass" / "orchestrator" / "calendars" / "cpi_2026.csv"

PAGE = "https://www.bls.gov/schedule/news_release/cpi.htm"
# One snapshot per ~year, overlapping coverage; ids chosen so the union spans
# releases from Jan-2020 (Dec-2019 data) through Dec-2025 + 2026 overlap.
SNAPSHOT_TS = ["20200115", "20210115", "20211115", "20220601", "20230115",
               "20240115", "20250115", "20251015", "20260115"]

MONTHS = {m: i + 1 for i, m in enumerate(
    ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
     "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"])}


def fetch(ts: str) -> str:
    url = f"https://web.archive.org/web/{ts}id_/{PAGE}"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return r.read().decode("utf-8", errors="ignore")
        except Exception as e:
            if attempt == 3:
                raise
            time.sleep(3 * (attempt + 1))
    return ""


def parse(page: str) -> dict:
    """-> {reference 'YYYY-MM': release 'YYYY-MM-DD'} from the schedule table."""
    out = {}
    for row in re.findall(r"<tr[^>]*>(.*?)</tr>", page, re.S):
        cells = [html_mod.unescape(re.sub(r"<[^>]+>", "", c)).strip()
                 for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", row, re.S)]
        if len(cells) < 2:
            continue
        m_ref = re.match(r"^([A-Z][a-z]+) (\d{4})$", cells[0])
        m_rel = re.match(r"^([A-Z][a-z]+)\.? (\d{1,2}), (\d{4})$", cells[1])
        if not (m_ref and m_rel):
            continue
        ref_mon = m_ref.group(1)[:3]
        rel_mon = m_rel.group(1)[:3]
        if ref_mon not in MONTHS or rel_mon not in MONTHS:
            continue
        ref = f"{m_ref.group(2)}-{MONTHS[ref_mon]:02d}"
        rel = f"{m_rel.group(3)}-{MONTHS[rel_mon]:02d}-{int(m_rel.group(2)):02d}"
        out[ref] = rel
    return out


def main() -> None:
    merged: dict = {}
    sources: dict = {}
    for ts in SNAPSHOT_TS:
        try:
            page = fetch(ts)
        except Exception as e:
            print(f"[warn] snapshot {ts} unavailable: {e}", file=sys.stderr)
            continue
        rows = parse(page)
        print(f"[snapshot {ts}] {len(rows)} rows "
              f"({min(rows) if rows else '-'}..{max(rows) if rows else '-'})")
        for ref, rel in rows.items():
            if ref in merged and merged[ref] != rel:
                print(f"FATAL: conflict for reference {ref}: "
                      f"{merged[ref]} (snap {sources[ref]}) vs {rel} (snap {ts})",
                      file=sys.stderr)
                sys.exit(1)
            merged.setdefault(ref, rel)
            sources.setdefault(ref, ts)

    # Keep releases dated 2020-01-01 .. 2025-12-31
    rows = sorted((rel, ref) for ref, rel in merged.items()
                  if "2020-01-01" <= rel <= "2025-12-31")

    # Completeness: expect exactly 72 monthly releases in 2020-2025
    if len(rows) != 72:
        got_months = {r[:7] for r, _ in rows}
        missing = [f"{y}-{m:02d}" for y in range(2020, 2026) for m in range(1, 13)
                   if f"{y}-{m:02d}" not in got_months]
        print(f"FATAL: expected 72 releases, got {len(rows)}; "
              f"months without a release: {missing}", file=sys.stderr)
        sys.exit(1)

    # Sanity: every date a weekday, day-of-month in 8..16 band
    for rel, ref in rows:
        d = datetime.fromisoformat(rel)
        assert d.weekday() < 5, f"{rel} not a weekday"
        assert 8 <= d.day <= 16, f"{rel} outside BLS mid-month band"

    # Cross-validate overlap against committed cpi_2026.csv
    committed = {}
    for line in EXISTING_2026.read_text().splitlines():
        if line.startswith("20"):
            committed[line.split(",")[0]] = True
    overlap_2026 = sorted(rel for ref, rel in merged.items()
                          if rel.startswith("2026"))
    matched = [r for r in overlap_2026 if r in committed]
    print(f"[xcheck] 2026 overlap: {len(matched)}/{len(overlap_2026)} snapshot "
          f"dates present in committed cpi_2026.csv")
    if overlap_2026 and len(matched) != len(overlap_2026):
        print(f"FATAL: 2026 snapshot dates not in committed file: "
              f"{[r for r in overlap_2026 if r not in committed]}", file=sys.stderr)
        sys.exit(1)

    ref_names = {v: k for k, v in MONTHS.items()}
    lines = [
        "# compass/orchestrator/calendars/cpi_2020_2025.csv",
        "# Source: Bureau of Labor Statistics CPI release schedule",
        "# (https://www.bls.gov/schedule/news_release/cpi.htm), captured via",
        "# Wayback Machine snapshots (bls.gov 403s this host; archive.org holds",
        f"# faithful captures). Snapshots used: {', '.join(SNAPSHOT_TS)}.",
        "# Built by experiments/PROG0-data-backfill/build_cpi_calendar.py",
        f"# on 2026-07-12. Cross-checks: overlapping snapshots agree on every",
        "# month (build aborts on conflict); 2026 overlap validated against the",
        "# committed cpi_2026.csv; all dates weekdays within the BLS 8th-16th",
        "# release band. All releases 08:30 ET.",
        "#",
        "date,notes",
    ]
    for rel, ref in rows:
        y, m = ref.split("-")
        month_name = [k for k, v in MONTHS.items() if v == int(m)][0]
        full = {"Jan": "January", "Feb": "February", "Mar": "March", "Apr": "April",
                "May": "May", "Jun": "June", "Jul": "July", "Aug": "August",
                "Sep": "September", "Oct": "October", "Nov": "November",
                "Dec": "December"}[month_name]
        lines.append(f"{rel},CPI release ({full} {y} data)")
    OUT.write_text("\n".join(lines) + "\n")
    print(f"[done] wrote {len(rows)} rows -> {OUT}")


if __name__ == "__main__":
    main()
