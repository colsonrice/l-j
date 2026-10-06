#!/usr/bin/env python3
"""
update_jackpots.py

Fetches Powerball and Mega Millions draws from the New York Lottery
"Past Winning Numbers" pages (which list winning numbers and jackpot
amounts for each draw) and writes a single JSON file (history.json):

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

Two rules the apps that read this file depend on:

1. Every row is the MAIN draw: five white balls, then the special ball.
   The page prints add-on draws (Double Play) in the same cell, and a row
   that carries them is rejected by every reader.
2. A run never publishes less than was published before. If the source
   is down the previous feed stands; a game that could not be fetched
   keeps its previous rows.
"""

import re
import json
import sys
import requests
from bs4 import BeautifulSoup
from datetime import datetime, date, timezone
from typing import Optional, List, Dict

# ── CONFIGURATION ───────────────────────────────────────────────────────────────

POWERBALL_URL = "https://www.nylottery.org/powerball/past-winning-numbers"
MEGAMILLIONS_URL = "https://www.nylottery.org/mega-millions/past-winning-numbers"

# The feed as last published (GitHub Pages serves the gh-pages branch).
PUBLISHED_URL = "https://raw.githubusercontent.com/colsonrice/l-j/gh-pages/history.json"

OUTPUT_FILE = "history.json"
GAMES = ("powerball", "megaMillions")

# Only include draws on or after this cutoff:
CUTOFF_DATE = date(2025, 1, 1)

# Five white balls and the special ball.
MAIN_DRAW_BALLS = 6
# The span class that marks the special ball, which ends the main draw.
SPECIAL_BALL_CLASSES = {"powerball", "power-ball", "mega-ball", "megaball"}


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


def main_draw_numbers(numbers_td) -> List[int]:
    """
    The main draw's balls, in page order: everything up to and including the
    first special ball. If no span carries a known special-ball class, the
    first six balls are the main draw.
    """
    numbers: List[int] = []
    for span in numbers_td.find_all("span", class_=re.compile(r"\bresultBall\b")):
        txt = span.get_text(strip=True)
        if not txt.isdigit():
            continue
        numbers.append(int(txt))
        if SPECIAL_BALL_CLASSES & set(span.get("class") or []):
            break
    return numbers[:MAIN_DRAW_BALLS]


def parse_draw_rows(html: str) -> List[Dict]:
    """
    Given the HTML of a "Past Winning Numbers" page (Powerball or Mega Millions),
    parse out each <tr> containing:
      1) a <td> with an <a> holding "Weekday Month Day<ordinal> Year"
      2) a <td> of <span class="resultBall ..."> balls: the main draw first,
         then any add-on draw
      3) a <td> with a <strong>$Jackpot</strong>

    Returns a list of dicts, newest first as on the page:
      [{"date": "YYYY-MM-DD", "numbers": [w1, w2, w3, w4, w5, special], "jackpot": int}, ...]
    Only includes draws whose date >= CUTOFF_DATE, and only rows with exactly
    six numbers.
    """
    soup = BeautifulSoup(html, "html.parser")
    results: List[Dict] = []

    for tr in soup.find_all("tr"):
        tds = tr.find_all("td")
        if len(tds) < 3:
            continue

        # First <td>: an <a> with a date string like "Friday May 30th 2025"
        a_tag = tds[0].find("a")
        if not a_tag or not a_tag.get_text(strip=True):
            continue
        raw_date = a_tag.get_text(" ", strip=True)

        # Drop the weekday and the ordinal suffix ("30th" → "30")
        parts = raw_date.split()
        if len(parts) < 3:
            continue
        date_part = re.sub(r"(\d+)(st|nd|rd|th)", r"\1", " ".join(parts[1:]))

        try:
            draw_date = datetime.strptime(date_part, "%B %d %Y").date()
        except ValueError:
            continue

        if draw_date < CUTOFF_DATE:
            continue

        # Second <td>: the main draw only. A short row is a page we do not
        # understand; publishing it would feed readers a row they reject.
        numbers = main_draw_numbers(tds[1])
        if len(numbers) != MAIN_DRAW_BALLS:
            print(f"⚠️ Skipping {draw_date.isoformat()}: expected {MAIN_DRAW_BALLS} numbers, found {len(numbers)}.")
            continue

        # Third <td>: a <strong> with the jackpot (e.g. "$189,000,000")
        strong = tds[2].find("strong")
        if not strong:
            continue
        jackpot_digits = strong.get_text(strip=True).replace("$", "").replace(",", "")
        if not jackpot_digits.isdigit():
            continue

        results.append({
            "date": draw_date.isoformat(),
            "numbers": numbers,
            "jackpot": int(jackpot_digits)
        })

    return results


def fetch_lottery_history(url: str) -> List[Dict]:
    """
    Fetch the HTML at `url`, then parse all draw rows (date, numbers, jackpot)
    since CUTOFF_DATE. Returns a list of draw-dicts, empty on failure.
    """
    html = fetch_html(url)
    if html is None:
        return []
    return parse_draw_rows(html)


def fetch_published() -> Optional[Dict]:
    """The feed as last published, or None if it cannot be read."""
    try:
        resp = requests.get(PUBLISHED_URL, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        return data if isinstance(data, dict) else None
    except Exception as e:
        print(f"⚠️ Could not read the published feed: {e}")
        return None


def clean_row(row) -> Optional[Dict]:
    """
    A previously published row, kept only if it is well formed. A row that
    carries an add-on draw after the main draw is trimmed to the main draw.
    """
    try:
        draw_date = date.fromisoformat(row["date"])
        numbers = [int(n) for n in row["numbers"]]
        jackpot = int(row["jackpot"])
    except (KeyError, TypeError, ValueError):
        return None
    if draw_date < CUTOFF_DATE or len(numbers) < MAIN_DRAW_BALLS:
        return None
    return {"date": draw_date.isoformat(), "numbers": numbers[:MAIN_DRAW_BALLS], "jackpot": jackpot}


def merge_history(previous: List[Dict], fetched: List[Dict]) -> List[Dict]:
    """
    Fetched rows win; published rows the page no longer lists are kept, so the
    feed only ever grows. Newest first.
    """
    by_date: Dict[str, Dict] = {}
    for row in previous or []:
        cleaned = clean_row(row)
        if cleaned:
            by_date[cleaned["date"]] = cleaned
    for row in fetched:
        by_date[row["date"]] = row
    return [by_date[d] for d in sorted(by_date, reverse=True)]


def main() -> int:
    fetched = {
        "powerball": fetch_lottery_history(POWERBALL_URL),
        "megaMillions": fetch_lottery_history(MEGAMILLIONS_URL),
    }
    if not any(fetched.values()):
        # The source is down or changed. The published feed stands as it is.
        print("⛔ No draws fetched for either game; not writing history.json.")
        return 1

    published = fetch_published() or {}
    output = {"timestamp": datetime.now(timezone.utc).replace(microsecond=0).isoformat()}
    for game in GAMES:
        previous = published.get(game)
        previous = previous if isinstance(previous, list) else []
        if not fetched[game]:
            print(f"⚠️ No {game} draws fetched; keeping the {len(previous)} published rows.")
        output[game] = merge_history(previous, fetched[game])

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2)

    print(f"✅ Wrote history.json with {len(output['powerball'])} Powerball draws and "
          f"{len(output['megaMillions'])} Mega Millions draws since {CUTOFF_DATE.isoformat()}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
