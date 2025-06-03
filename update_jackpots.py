#!/usr/bin/env python3
"""
update_jackpots.py

Fetches all Powerball and Mega Millions draws since January 1, 2025
from the New York Lottery “Past Winning Numbers” pages (which list both
winning numbers and jackpot amounts for each draw), then writes out
a single JSON file (history.json) that looks like:

{
  "timestamp": "2025-06-03T14:00:00Z",
  "powerball": [
    {
      "date": "2025-01-03",
      "numbers": [1, 7, 22, 34, 56, 18],
      "jackpot": 71000000
    },
    ...
  ],
  "megaMillions": [
    {
      "date": "2025-01-07",
      "numbers": [4, 14, 35, 49, 62, 6],
      "jackpot": 20000000
    },
    ...
  ]
}
"""

import re
import json
import requests
from bs4 import BeautifulSoup
from datetime import datetime, date, timezone
from typing import Optional, List, Dict

# ── CONFIGURATION ───────────────────────────────────────────────────────────────

POWERBALL_URL = "https://www.nylottery.org/powerball/past-winning-numbers"      # :contentReference[oaicite:2]{index=2}
MEGAMILLIONS_URL = "https://www.nylottery.org/mega-millions/past-winning-numbers"  # :contentReference[oaicite:3]{index=3}

# Only include draws on or after this cutoff:
CUTOFF_DATE = date(2025, 1, 1)


def fetch_html(url: str) -> Optional[str]:
    """
    Download the raw HTML from the given URL.
    Returns the HTML as a string, or None on failure.
    """
    try:
        resp = requests.get(url, timeout=15)
        resp.raise_for_status()
        return resp.text
    except Exception as e:
        print(f"⛔ Error fetching {url}: {e}")
        return None


def parse_draw_rows(html: str) -> List[Dict]:
    """
    Given the HTML of a “Past Winning Numbers” page (Powerball or Mega Millions),
    parse out each <tr> containing:
      1) a <td class="centred">…<a>“Weekday Month Day<ordinal> Year”</a></td>
      2) a <td class="centred">…<span class="resultBall ball">white1</span> … <span class="resultBall [mega-ball | power-ball]">special</span> …</td>
      3) a <td class="centred nowrap"><strong>$Jackpot</strong> …</td>

    Returns a list of dicts:
      [
        {
          "date": "YYYY-MM-DD",
          "numbers": [int, int, …, int],   # white balls in order, then special ball
          "jackpot": int
        },
        ...
      ]
    Only includes draws whose date >= CUTOFF_DATE.
    """
    soup = BeautifulSoup(html, "html.parser")
    results: List[Dict] = []

    # Find the table of past draws (usually there’s only one big table of results)
    # We can simply look for all <tr> under the page and filter rows that have the expected structure.
    for tr in soup.find_all("tr"):
        # 1) Does this row have at least three <td>?
        tds = tr.find_all("td")
        if len(tds) < 3:
            continue

        # First <td>: should contain an <a> with a date string like “Friday May 30th 2025”
        date_td = tds[0]
        a_tag = date_td.find("a")
        if not a_tag or not a_tag.get_text(strip=True):
            continue
        raw_date = a_tag.get_text(" ", strip=True)  # e.g. "Friday May 30th 2025"

        # Remove the weekday and strip out ordinal suffix from the day (“30th” → “30”)
        parts = raw_date.split()
        if len(parts) < 3:
            continue
        # Drop the first part (weekday), rejoin the rest: "May 30th 2025"
        date_part = " ".join(parts[1:])
        # Remove ordinal suffixes (st, nd, rd, th)
        date_part = re.sub(r"(\d+)(st|nd|rd|th)", r"\1", date_part)

        try:
            draw_date = datetime.strptime(date_part, "%B %d %Y").date()
        except ValueError:
            # If parsing fails, skip this row
            continue

        # Skip anything before our cutoff
        if draw_date < CUTOFF_DATE:
            continue

        # 2) Second <td>: collect all <span class="resultBall ..."> text as numbers
        numbers_td = tds[1]
        number_spans = numbers_td.find_all("span", class_=re.compile(r"\bresultBall\b"))
        numbers: List[int] = []
        for span in number_spans:
            txt = span.get_text(strip=True)
            if txt.isdigit():
                numbers.append(int(txt))
        if not numbers:
            continue

        # 3) Third <td>: should contain a <strong> with the jackpot (e.g. "$189,000,000")
        jackpot_td = tds[2]
        strong = jackpot_td.find("strong")
        if not strong:
            continue

        jackpot_text = strong.get_text(strip=True)  # e.g. "$189,000,000"
        # Strip out $ and commas
        jackpot_digits = jackpot_text.replace("$", "").replace(",", "")
        if not jackpot_digits.isdigit():
            continue
        jackpot_amount = int(jackpot_digits)

        # We have: date, numbers list, jackpot
        results.append({
            "date": draw_date.isoformat(),
            "numbers": numbers,
            "jackpot": jackpot_amount
        })

    # Results appear in reverse‐chronological order on the page; if you want ascending order:
    # results.sort(key=lambda x: x["date"])
    return results


def fetch_lottery_history(url: str) -> List[Dict]:
    """
    Fetch the HTML at `url`, then parse all draw rows (date, numbers, jackpot)
    since CUTOFF_DATE. Returns a list of draw‐dicts.
    """
    html = fetch_html(url)
    if html is None:
        return []
    return parse_draw_rows(html)


def main():
    # 1) Fetch all Powerball draws since Jan 1 2025
    powerball_history = fetch_lottery_history(POWERBALL_URL)

    # 2) Fetch all Mega Millions draws since Jan 1 2025
    megamillions_history = fetch_lottery_history(MEGAMILLIONS_URL)

    # 3) Build output JSON
    now_iso = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    output = {
        "timestamp": now_iso,
        "powerball": powerball_history,
        "megaMillions": megamillions_history
    }

    # 4) Write to history.json
    with open("history.json", "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2)

    print(f"✅ Wrote history.json with {len(powerball_history)} Powerball draws and "
          f"{len(megamillions_history)} Mega Millions draws since {CUTOFF_DATE.isoformat()}.")


if __name__ == "__main__":
    main()
