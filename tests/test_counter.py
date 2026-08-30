import unittest

import numpy as np

from config import TRIPWIRE_Y_RATIO
from src.counter import TripwireCounter


class _Det:
    """Minimal Detection stand-in: the counter only reads bbox and track_id."""

    def __init__(self, track_id, cy, cx=300, half_w=20, half_h=40):
        self.track_id = track_id
        self.bbox = (cx - half_w, cy - half_h, cx + half_w, cy + half_h)


def _frame(width=640, height=480):
    return np.zeros((height, width, 3), dtype=np.uint8)


class DirectionalCountingTests(unittest.TestCase):
    def setUp(self):
        self.counter = TripwireCounter(tripwire_start=(50, 300), tripwire_end=(600, 300))

    def _move(self, track_id, *positions):
        events = []
        for cy in positions:
            events.extend(self.counter.process_crossing([_Det(track_id, cy)]))
        return events

    def test_downward_crossing_counts_as_entry(self):
        self._move(1, 200, 400)
        self.assertEqual((self.counter.entry_count, self.counter.exit_count), (1, 0))

    def test_upward_crossing_counts_as_exit(self):
        self._move(1, 400, 200)
        self.assertEqual((self.counter.entry_count, self.counter.exit_count), (0, 1))

    def test_first_sighting_never_counts(self):
        """A track appearing already past the line must not register a crossing."""
        self._move(1, 400)
        self.assertEqual((self.counter.entry_count, self.counter.exit_count), (0, 0))

    def test_loitering_on_the_line_counts_once(self):
        """Jitter around the line must not inflate the count."""
        self._move(1, 200, 400, 400, 400)
        self.assertEqual(self.counter.entry_count, 1)

    def test_round_trip_counts_one_each_way(self):
        self._move(1, 200, 400, 200)
        self.assertEqual((self.counter.entry_count, self.counter.exit_count), (1, 1))

    def test_tracks_are_counted_independently(self):
        self.counter.process_crossing([_Det(1, 200), _Det(2, 400, cx=450)])
        self.counter.process_crossing([_Det(1, 400), _Det(2, 200, cx=450)])

        self.assertEqual((self.counter.entry_count, self.counter.exit_count), (1, 1))

    def test_negative_track_ids_are_ignored(self):
        """Untracked detections (-1) carry no identity and must be skipped."""
        self._move(-1, 200, 400)
        self.assertEqual(self.counter.entry_count, 0)

    def test_reset_clears_counts(self):
        self._move(1, 200, 400)
        self.counter.reset()
        self.assertEqual((self.counter.entry_count, self.counter.exit_count), (0, 0))


class ResolutionScalingTests(unittest.TestCase):
    """The tripwire must land in the same relative place on any camera."""

    def test_scales_to_1080p(self):
        counter = TripwireCounter()
        counter.process_crossing([], _frame(1920, 1080))

        self.assertEqual(counter.tripwire_y, int(1080 * TRIPWIRE_Y_RATIO))
        self.assertLess(counter.tripwire_end[0], 1920)

    def test_scales_to_720p(self):
        counter = TripwireCounter()
        counter.process_crossing([], _frame(1280, 720))

        self.assertEqual(counter.tripwire_y, int(720 * TRIPWIRE_Y_RATIO))

    def test_counts_correctly_at_1080p(self):
        """A person crossing the rescaled line is still counted."""
        counter = TripwireCounter()
        frame = _frame(1920, 1080)
        line_y = int(1080 * TRIPWIRE_Y_RATIO)

        counter.process_crossing([_Det(1, line_y - 200, cx=960)], frame)
        counter.process_crossing([_Det(1, line_y + 200, cx=960)], frame)

        self.assertEqual(counter.entry_count, 1)

    def test_explicit_coordinates_are_not_rescaled(self):
        counter = TripwireCounter(tripwire_start=(0, 100), tripwire_end=(640, 100))
        counter.process_crossing([], _frame(1920, 1080))

        self.assertEqual(counter.tripwire_y, 100)

    def test_occlusion_threshold_is_reachable(self):
        """The old absolute threshold exceeded a whole 640x480 frame, so it never fired."""
        counter = TripwireCounter()
        counter.process_crossing([], _frame(640, 480))

        self.assertLess(counter.max_person_area, 640 * 480)

    def test_occlusion_threshold_scales_with_frame(self):
        small = TripwireCounter()
        small.process_crossing([], _frame(640, 480))

        large = TripwireCounter()
        large.process_crossing([], _frame(1920, 1080))

        self.assertGreater(large.max_person_area, small.max_person_area)


if __name__ == "__main__":
    unittest.main()
