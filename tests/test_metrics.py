#!/usr/bin/env python3
"""Tests du chronomètre de latence (core/metrics.py)."""

import sys
import unittest
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from core.metrics import TurnTimer, format_timings, percentile, summarize


class FakeClock:
    def __init__(self):
        self.now = 100.0

    def __call__(self):
        return self.now


class TestTurnTimer(unittest.TestCase):
    def test_first_mark_wins_and_order_follows_pipeline(self):
        clock = FakeClock()
        timer = TurnTimer(clock)
        clock.now = 100.9
        timer.mark("first_sentence")
        clock.now = 100.3
        timer.mark("stt")
        clock.now = 102.0
        timer.mark("first_sentence")   # ignorée : déjà notée
        timer.mark("total")
        self.assertEqual(timer.as_ms(), {"stt": 300, "first_sentence": 900, "total": 2000})

    def test_format(self):
        self.assertEqual(format_timings({"stt": 320, "first_token": 400, "total": 2400}),
                         "transcription 320 ms · total 2,4 s")


class TestSummary(unittest.TestCase):
    def test_percentile(self):
        self.assertIsNone(percentile([], 0.5))
        self.assertEqual(percentile([1, 2, 3, 4], 0.5), 2.5)
        self.assertEqual(percentile([10], 0.9), 10)

    def test_summarize_by_model(self):
        rows = [{"model": "m", "timings": {"total": t, "stt": 100}} for t in (1000, 2000, 3000)]
        rows.append({"model": "", "timings": {"total": 50}})
        out = summarize(rows)
        self.assertEqual(list(out["m"]), ["stt", "total"])
        self.assertEqual(out["m"]["total"], {"n": 3, "p50": 2000, "p90": 2800})
        self.assertEqual(out["?"]["total"]["n"], 1)


if __name__ == "__main__":
    unittest.main()
