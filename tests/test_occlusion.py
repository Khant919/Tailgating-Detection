import unittest

import numpy as np

from config import API_KEY, MAX_OCCUPANCY_PER_BOX, MIN_OCCLUSION_FRAMES
from src.access_system import AccessController
from src.counter import TripwireCounter


class _Det:
    """Detection stand-in with an explicitly controllable box shape."""

    def __init__(self, track_id, cy, cx=300, width=60, height=160):
        self.track_id = track_id
        half_w, half_h = width // 2, height // 2
        self.bbox = (cx - half_w, cy - half_h, cx + half_w, cy + half_h)


SINGLE = dict(width=60, height=160)   # aspect 0.375 — one person
MERGED = dict(width=140, height=160)  # aspect 0.875 — two abreast


class OccupancyEstimationTests(unittest.TestCase):
    def setUp(self):
        self.counter = TripwireCounter(tripwire_start=(50, 300), tripwire_end=(600, 300))
        self.counter.configure_for_frame(640, 480)

    def test_single_person_box_is_one(self):
        self.assertEqual(self.counter.estimate_box_occupancy((0, 0, 60, 160)), 1)

    def test_wide_box_is_two(self):
        self.assertEqual(self.counter.estimate_box_occupancy((0, 0, 140, 160)), 2)

    def test_distance_does_not_change_estimate(self):
        """Aspect ratio is scale invariant: a closer person is not two people."""
        near = self.counter.estimate_box_occupancy((0, 0, 120, 320))
        far = self.counter.estimate_box_occupancy((0, 0, 30, 80))
        self.assertEqual(near, 1)
        self.assertEqual(far, 1)

    def test_flow_split_forces_at_least_two(self):
        self.assertEqual(self.counter.estimate_box_occupancy((0, 0, 60, 160), flow_split=True), 2)

    def test_estimate_is_capped(self):
        self.assertLessEqual(
            self.counter.estimate_box_occupancy((0, 0, 900, 100)), MAX_OCCUPANCY_PER_BOX
        )

    def test_degenerate_box_is_one(self):
        self.assertEqual(self.counter.estimate_box_occupancy((10, 10, 10, 10)), 1)


class OccludedCountingTests(unittest.TestCase):
    def setUp(self):
        self.counter = TripwireCounter(tripwire_start=(50, 300), tripwire_end=(600, 300))
        self.counter.configure_for_frame(640, 480)

    def _approach_then_cross(self, shape, approach_frames=4):
        for _ in range(approach_frames):
            self.counter.process_crossing([_Det(1, 200, **shape)])
        return self.counter.process_crossing([_Det(1, 400, **shape)])

    def test_single_person_crossing_counts_one(self):
        events = self._approach_then_cross(SINGLE)

        self.assertEqual(len(events), 1)
        self.assertFalse(events[0]["occluded"])
        self.assertEqual(self.counter.entry_count, 1)

    def test_merged_box_counts_two(self):
        """The whole point: two people in one box must not enter as one."""
        events = self._approach_then_cross(MERGED)

        self.assertEqual(len(events), 2)
        self.assertEqual(self.counter.entry_count, 2)
        self.assertEqual(self.counter.occluded_entries, 1)

    def test_merged_box_emits_one_occluded_event(self):
        events = self._approach_then_cross(MERGED)

        self.assertEqual([e["occluded"] for e in events], [False, True])
        self.assertTrue(all(e["direction"] == "entry" for e in events))

    def test_occluded_event_keeps_host_track_id(self):
        """The hidden person is reported against the box they were hiding in."""
        events = self._approach_then_cross(MERGED)
        self.assertTrue(all(e["track_id"] == 1 for e in events))

    def test_single_noisy_frame_does_not_inflate_count(self):
        """One merged-looking frame is noise, not a person."""
        self.counter.process_crossing([_Det(1, 180, **SINGLE)])
        self.counter.process_crossing([_Det(1, 200, **MERGED)])
        self.counter.process_crossing([_Det(1, 220, **SINGLE)])
        self.counter.process_crossing([_Det(1, 240, **SINGLE)])
        events = self.counter.process_crossing([_Det(1, 400, **SINGLE)])

        self.assertEqual(len(events), 1)
        self.assertEqual(self.counter.entry_count, 1)

    def test_sustained_merge_is_counted(self):
        self.counter.process_crossing([_Det(1, 180, **SINGLE)])
        for _ in range(MIN_OCCLUSION_FRAMES):
            self.counter.process_crossing([_Det(1, 200, **MERGED)])
        events = self.counter.process_crossing([_Det(1, 400, **MERGED)])

        self.assertEqual(len(events), 2)

    def test_exit_is_never_split(self):
        """Occupancy inflation applies to entries only; exits are not a breach."""
        for _ in range(4):
            self.counter.process_crossing([_Det(1, 400, **MERGED)])
        events = self.counter.process_crossing([_Det(1, 200, **MERGED)])

        self.assertEqual(len(events), 1)
        self.assertEqual(self.counter.exit_count, 1)


class OccludedAuthorizationTests(unittest.TestCase):
    """A hidden person must never be authorised by the host's swipe."""

    def setUp(self):
        self.controller = AccessController(port=5031, swipe_timeout=30)
        self.client = self.controller._app.test_client()
        self.client.post(
            "/swipe",
            json={"employee_id": "EMP001", "name": "Alice Smith"},
            headers={"x-api-key": API_KEY},
        )

    def test_occluded_entry_cannot_consume_a_swipe(self):
        result = self.controller.check_for_tailgate(
            authenticated_name=None, allow_card_only=False
        )

        self.assertEqual(result["status"], "tailgate")
        self.assertEqual(len(self.controller._valid_swipes), 1)

    def test_host_still_authorised_after_occluded_breach(self):
        self.controller.check_for_tailgate(authenticated_name=None, allow_card_only=False)
        result = self.controller.check_for_tailgate(authenticated_name="Alice Smith")

        self.assertEqual(result["status"], "authorized")


class VelocitySplitTests(unittest.TestCase):
    """Flow clustering must separate real divergence from measurement noise."""

    def test_noise_around_zero_is_not_a_split(self):
        noise = np.array([-0.4, -0.2, -0.1, 0.1, 0.2, 0.3, 0.15, -0.25])
        self.assertFalse(TripwireCounter._has_velocity_split(noise))

    def test_two_diverging_clusters_are_a_split(self):
        """Separation must exceed OPTICAL_FLOW_SPLIT_THRESHOLD (20 px/frame)."""
        diverging = np.array([-13.0, -12.5, -12.8, 12.4, 13.1, 12.9])
        self.assertTrue(TripwireCounter._has_velocity_split(diverging))

    def test_separation_below_threshold_is_not_a_split(self):
        near = np.array([-3.0, -2.8, -3.1, 3.0, 2.9, 3.2])
        self.assertFalse(TripwireCounter._has_velocity_split(near))

    def test_uniform_motion_is_not_a_split(self):
        """Everyone drifting together is camera shake, not two people."""
        uniform = np.array([4.0, 4.2, 3.9, 4.1, 4.05, 3.95])
        self.assertFalse(TripwireCounter._has_velocity_split(uniform))

    def test_too_few_points_is_not_a_split(self):
        self.assertFalse(TripwireCounter._has_velocity_split(np.array([-8.0, 8.0])))


if __name__ == "__main__":
    unittest.main()
