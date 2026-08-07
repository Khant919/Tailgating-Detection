import os
import unittest
from src.database import DatabaseManager

class TestDatabaseManager(unittest.TestCase):
    def setUp(self):
        # Use a temporary database for testing
        self.test_db_path = "test_tailgate_events.db"
        # Ensure any leftover database from a crashed test is removed
        if os.path.exists(self.test_db_path):
            os.remove(self.test_db_path)
        self.db = DatabaseManager(db_path=self.test_db_path)

    def tearDown(self):
        # Clean up the test database file
        if os.path.exists(self.test_db_path):
            os.remove(self.test_db_path)

    def test_database_initialization(self):
        """Verify database file and events table are initialized."""
        self.assertTrue(os.path.exists(self.test_db_path))
        
        # Query sqlite_master to verify the table exists
        conn = self.db._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='events';")
            table = cursor.fetchone()
        finally:
            conn.close()
        
        self.assertIsNotNone(table)
        self.assertEqual(table[0], "events")

    def test_log_event_and_retrieve(self):
        """Verify that events can be logged and correctly retrieved."""
        # Log a few events
        self.db.log_event("Tailgate Detected", "screenshots/test_tailgate1.jpg")
        self.db.log_event("Authorized Swipe", "screenshots/test_swipe1.jpg")
        
        events = self.db.get_recent_events()
        self.assertEqual(len(events), 2)
        
        # The latest event (Authorized Swipe) should be first
        self.assertEqual(events[0]["status"], "Authorized Swipe")
        self.assertEqual(events[0]["image_path"], "screenshots/test_swipe1.jpg")
        self.assertIsNotNone(events[0]["timestamp"])
        
        # The first event (Tailgate Detected) should be second
        self.assertEqual(events[1]["status"], "Tailgate Detected")
        self.assertEqual(events[1]["image_path"], "screenshots/test_tailgate1.jpg")
        self.assertIsNotNone(events[1]["timestamp"])

    def test_recent_events_limit(self):
        """Verify the limit parameter is respected."""
        for i in range(10):
            self.db.log_event(f"Event {i}", f"screenshots/img_{i}.jpg")
            
        events = self.db.get_recent_events(limit=5)
        self.assertEqual(len(events), 5)
        
        # The latest event (Event 9) should be first
        self.assertEqual(events[0]["status"], "Event 9")

if __name__ == "__main__":
    unittest.main()
