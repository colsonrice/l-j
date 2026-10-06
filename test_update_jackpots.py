#!/usr/bin/env python3
"""Checks for update_jackpots.py. No network: the page and the published feed
are supplied by the tests.

    python3 -m unittest test_update_jackpots
"""
import json
import os
import tempfile
import unittest
from unittest import mock

import update_jackpots as feed


def row(date_text, balls, special_class, special, extra="", jackpot="$463,300,000"):
    spans = "".join(f'<span class="resultBall ball">{n}</span>' for n in balls)
    spans += f'<span class="resultBall {special_class}">{special}</span>'
    return (f'<tr><td class="centred"><a href="#">{date_text}</a></td>'
            f'<td class="centred">{spans}{extra}</td>'
            f'<td class="centred nowrap"><strong>{jackpot}</strong> R</td></tr>')


# The add-on draw nylottery.org prints in the same cell since June 2026.
DOUBLE_PLAY = ('<div>Double Play</div>'
               + "".join(f'<span class="resultBall ball">{n}</span>' for n in (7, 22, 29, 35, 51))
               + '<span class="resultBall powerball">20</span>'
               + '<div class="power-play"><strong>×2</strong></div>')


def page(*rows):
    return "<html><body><table>" + "".join(rows) + "</table></body></html>"


class ParseRows(unittest.TestCase):
    def test_powerball_row_ends_at_its_powerball(self):
        html = page(row("Monday October 5th 2026", (16, 23, 32, 36, 54), "powerball", 9, DOUBLE_PLAY))
        self.assertEqual(feed.parse_draw_rows(html),
                         [{"date": "2026-10-05", "numbers": [16, 23, 32, 36, 54, 9], "jackpot": 463300000}])

    def test_mega_millions_row(self):
        html = page(row("Friday October 2nd 2026", (6, 37, 40, 41, 55), "mega-ball", 10, jackpot="$321,000,000"))
        self.assertEqual(feed.parse_draw_rows(html),
                         [{"date": "2026-10-02", "numbers": [6, 37, 40, 41, 55, 10], "jackpot": 321000000}])

    def test_unknown_special_class_falls_back_to_first_six(self):
        twelve = "".join(f'<span class="resultBall ball">{n}</span>' for n in (1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12))
        html = page(f'<tr><td><a>Saturday October 3rd 2026</a></td><td>{twelve}</td><td><strong>$1,000,000</strong></td></tr>')
        self.assertEqual(feed.parse_draw_rows(html)[0]["numbers"], [1, 2, 3, 4, 5, 6])

    def test_short_row_is_not_published(self):
        html = page(row("Monday October 5th 2026", (16, 23, 32, 36), "powerball", 9))
        self.assertEqual(feed.parse_draw_rows(html), [])

    def test_rows_before_the_cutoff_are_skipped(self):
        html = page(row("Saturday December 28th 2024", (1, 2, 3, 4, 5), "powerball", 6))
        self.assertEqual(feed.parse_draw_rows(html), [])


class MergeHistory(unittest.TestCase):
    def test_published_double_play_row_is_trimmed_to_the_main_draw(self):
        previous = [{"date": "2026-06-03", "numbers": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12], "jackpot": 5}]
        self.assertEqual(feed.merge_history(previous, []),
                         [{"date": "2026-06-03", "numbers": [1, 2, 3, 4, 5, 6], "jackpot": 5}])

    def test_fetched_rows_win_and_older_rows_are_kept_newest_first(self):
        previous = [{"date": "2026-10-03", "numbers": [9, 9, 9, 9, 9, 9], "jackpot": 1},
                    {"date": "2025-12-31", "numbers": [1, 2, 3, 4, 5, 6], "jackpot": 2}]
        fetched = [{"date": "2026-10-05", "numbers": [16, 23, 32, 36, 54, 9], "jackpot": 3},
                   {"date": "2026-10-03", "numbers": [4, 8, 15, 16, 23, 42], "jackpot": 4}]
        self.assertEqual([r["date"] for r in feed.merge_history(previous, fetched)],
                         ["2026-10-05", "2026-10-03", "2025-12-31"])
        self.assertEqual(feed.merge_history(previous, fetched)[1]["numbers"], [4, 8, 15, 16, 23, 42])

    def test_malformed_published_rows_are_dropped(self):
        previous = [{"date": "2026-10-03", "numbers": [1, 2, 3], "jackpot": 1},
                    {"date": "not a date", "numbers": [1, 2, 3, 4, 5, 6], "jackpot": 1},
                    {"date": "2026-10-01", "numbers": ["x"] * 6, "jackpot": 1},
                    {"numbers": [1, 2, 3, 4, 5, 6]},
                    {"date": "2024-12-28", "numbers": [1, 2, 3, 4, 5, 6], "jackpot": 1}]
        self.assertEqual(feed.merge_history(previous, []), [])


class Main(unittest.TestCase):
    PUBLISHED = {"timestamp": "2026-10-06T16:40:23+00:00",
                 "powerball": [{"date": "2026-10-05", "numbers": [16, 23, 32, 36, 54, 9, 7, 22, 29, 35, 51, 20], "jackpot": 463300000}],
                 "megaMillions": [{"date": "2026-10-02", "numbers": [6, 37, 40, 41, 55, 10], "jackpot": 321000000}]}

    def run_main(self, fetched, published):
        with tempfile.TemporaryDirectory() as directory:
            before = os.getcwd()
            os.chdir(directory)
            try:
                with mock.patch.object(feed, "fetch_lottery_history", side_effect=lambda url: fetched[url]), \
                     mock.patch.object(feed, "fetch_published", return_value=published):
                    code = feed.main()
                written = json.load(open("history.json")) if os.path.exists("history.json") else None
            finally:
                os.chdir(before)
        return code, written

    def test_source_down_publishes_nothing(self):
        code, written = self.run_main({feed.POWERBALL_URL: [], feed.MEGAMILLIONS_URL: []}, self.PUBLISHED)
        self.assertNotEqual(code, 0)
        self.assertIsNone(written)

    def test_one_game_down_keeps_its_published_rows(self):
        fetched = {feed.POWERBALL_URL: [{"date": "2026-10-07", "numbers": [1, 2, 3, 4, 5, 6], "jackpot": 485000000}],
                   feed.MEGAMILLIONS_URL: []}
        code, written = self.run_main(fetched, self.PUBLISHED)
        self.assertEqual(code, 0)
        self.assertEqual([r["date"] for r in written["powerball"]], ["2026-10-07", "2026-10-05"])
        self.assertEqual(written["powerball"][1]["numbers"], [16, 23, 32, 36, 54, 9])
        self.assertEqual(written["megaMillions"], self.PUBLISHED["megaMillions"])

    def test_no_published_feed_still_publishes_what_was_fetched(self):
        fetched = {feed.POWERBALL_URL: [{"date": "2026-10-07", "numbers": [1, 2, 3, 4, 5, 6], "jackpot": 1}],
                   feed.MEGAMILLIONS_URL: [{"date": "2026-10-06", "numbers": [1, 2, 3, 4, 5, 6], "jackpot": 2}]}
        code, written = self.run_main(fetched, None)
        self.assertEqual(code, 0)
        self.assertEqual(len(written["powerball"]), 1)
        self.assertEqual(len(written["megaMillions"]), 1)

    def test_every_published_row_has_six_numbers(self):
        fetched = {feed.POWERBALL_URL: [{"date": "2026-10-07", "numbers": [1, 2, 3, 4, 5, 6], "jackpot": 1}],
                   feed.MEGAMILLIONS_URL: [{"date": "2026-10-06", "numbers": [1, 2, 3, 4, 5, 6], "jackpot": 2}]}
        _, written = self.run_main(fetched, self.PUBLISHED)
        for game in ("powerball", "megaMillions"):
            self.assertTrue(all(len(r["numbers"]) == 6 for r in written[game]))


if __name__ == "__main__":
    unittest.main()
