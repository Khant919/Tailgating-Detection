import unittest

from config import API_KEY
from src.access_system import AccessController
from src.counter import TripwireCounter


class _Det:
    """Minimal stand-in for a Detection: the counter only reads bbox and track_id."""

    def __init__(self, track_id, cy, cx=300):
        self.track_id = track_id
        self.bbox = (cx - 20, cy - 40, cx + 20, cy + 40)


class CrossingEventTests(unittest.TestCase):
    """process_crossing must report which track crossed, not just how many."""

    def setUp(self):
        self.counter = TripwireCounter(tripwire_start=(50, 300), tripwire_end=(600, 300))

    def test_entry_event_carries_track_id(self):
        self.counter.process_crossing([_Det(7, cy=200)])
        events = self.counter.process_crossing([_Det(7, cy=400)])

        self.assertEqual(events, [{"track_id": 7, "direction": "entry"}])
        self.assertEqual(self.counter.entry_count, 1)

    def test_exit_event_carries_track_id(self):
        self.counter.process_crossing([_Det(3, cy=400)])
        events = self.counter.process_crossing([_Det(3, cy=200)])

        self.assertEqual(events, [{"track_id": 3, "direction": "exit"}])
        self.assertEqual(self.counter.exit_count, 1)

    def test_no_event_without_crossing(self):
        self.counter.process_crossing([_Det(1, cy=200)])
        self.assertEqual(self.counter.process_crossing([_Det(1, cy=250)]), [])

    def test_two_tracks_produce_two_events(self):
        self.counter.process_crossing([_Det(1, cy=200), _Det(2, cy=200, cx=400)])
        events = self.counter.process_crossing([_Det(1, cy=400), _Det(2, cy=400, cx=400)])

        self.assertEqual(len(events), 2)
        self.assertEqual({e["track_id"] for e in events}, {1, 2})


class IdentityBindingTests(unittest.TestCase):
    """A swipe must only authorise the employee it belongs to."""

    def setUp(self):
        self.controller = AccessController(port=5021, swipe_timeout=30)
        self.client = self.controller._app.test_client()

    def _swipe(self, employee_id, name):
        return self.client.post(
            "/swipe",
            json={"employee_id": employee_id, "name": name},
            headers={"x-api-key": API_KEY},
        )

    def test_matching_identity_is_authorized(self):
        self._swipe("EMP001", "Alice Smith")

        result = self.controller.check_for_tailgate(authenticated_name="Alice Smith")

        self.assertEqual(result["status"], "authorized")
        self.assertEqual(result["employee"]["name"], "Alice Smith")

    def test_different_person_crossing_is_a_tailgate(self):
        """Alice swipes, Bob walks through: Bob must not be authorised."""
        self._swipe("EMP001", "Alice Smith")

        result = self.controller.check_for_tailgate(authenticated_name="Bob Jones")

        self.assertEqual(result["status"], "tailgate")

    def test_mismatched_crossing_leaves_swipe_for_its_owner(self):
        """Bob's crossing must not burn Alice's swipe — she still gets in."""
        self._swipe("EMP001", "Alice Smith")

        self.controller.check_for_tailgate(authenticated_name="Bob Jones")
        result = self.controller.check_for_tailgate(authenticated_name="Alice Smith")

        self.assertEqual(result["status"], "authorized")
        self.assertEqual(result["employee"]["name"], "Alice Smith")

    def test_unauthenticated_crossing_with_no_swipe_is_a_tailgate(self):
        result = self.controller.check_for_tailgate(authenticated_name="Ghost")
        self.assertEqual(result["status"], "tailgate")

    def test_selects_correct_swipe_from_several(self):
        self._swipe("EMP001", "Alice Smith")
        self._swipe("EMP002", "Bob Jones")
        self._swipe("EMP003", "Carol White")

        result = self.controller.check_for_tailgate(authenticated_name="Bob Jones")

        self.assertEqual(result["employee"]["employee_id"], "EMP002")
        self.assertEqual(len(self.controller._valid_swipes), 2)

    def test_card_only_mode_still_authorizes(self):
        """Without a face match the swipe still works, preserving old behaviour."""
        self._swipe("EMP001", "Alice Smith")

        result = self.controller.check_for_tailgate()

        self.assertEqual(result["status"], "authorized")


if __name__ == "__main__":
    unittest.main()
