import os
import unittest

import cv2
import numpy as np

from src.live_capture import WebcamCapture


class TestFaceBlur(unittest.TestCase):
    """Module 8: GDPR face blurring applied to breach evidence screenshots."""

    def setUp(self):
        # Build the instance without __init__ so the test never touches a webcam,
        # database, or the 2FA authenticator.
        self.capture = WebcamCapture.__new__(WebcamCapture)
        self.capture._face_cascade = None

        # A real frame containing a face gives the Haar cascade something to find.
        sample = os.path.join("screenshots", "1786111848.jpg")
        self.frame = cv2.imread(sample)
        if self.frame is None:
            self.skipTest(f"Sample evidence frame not available: {sample}")

    def test_cascade_loads(self):
        """The Haar cascade should load rather than returning None."""
        cascade = self.capture._get_face_cascade()
        self.assertIsNotNone(cascade)
        self.assertFalse(cascade.empty())

    def test_blur_modifies_frame(self):
        """Blurring must actually change pixels when a face is present."""
        blurred = self.capture._blur_faces(self.frame)

        self.assertEqual(blurred.shape, self.frame.shape)
        self.assertFalse(np.array_equal(blurred, self.frame))

    def test_original_frame_not_mutated(self):
        """The live display frame must keep unblurred faces for the guard view."""
        original = self.frame.copy()
        self.capture._blur_faces(self.frame)
        np.testing.assert_array_equal(self.frame, original)

    def test_blurred_region_loses_detail(self):
        """The blurred output should have lower local variance than the source."""
        blurred = self.capture._blur_faces(self.frame)

        diff = np.abs(self.frame.astype(np.int16) - blurred.astype(np.int16))
        changed = diff.sum(axis=2) > 0
        self.assertTrue(changed.any(), "no pixels were blurred")

        # Compare detail only inside the region that was actually altered.
        gray_before = cv2.cvtColor(self.frame, cv2.COLOR_BGR2GRAY)
        gray_after = cv2.cvtColor(blurred, cv2.COLOR_BGR2GRAY)
        self.assertLess(gray_after[changed].var(), gray_before[changed].var())

    def test_fails_closed_without_cascade(self):
        """If the cascade cannot load, the whole frame is blurred, not passed through."""
        self.capture._face_cascade = None
        self.capture._get_face_cascade = lambda: None

        blurred = self.capture._blur_faces(self.frame)

        self.assertEqual(blurred.shape, self.frame.shape)
        self.assertFalse(np.array_equal(blurred, self.frame))


if __name__ == "__main__":
    unittest.main()
