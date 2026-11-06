"""Image-feature and scientific-label checks without private fitted models."""

from pathlib import Path
import sys
import tempfile
import unittest

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "engine"))
from flow_patterns import CLASSES, known_label, label_index, visual_features
from interfaces import features, track


class Features(unittest.TestCase):
    def test_experimental_labels_follow_confirmed_table(self):
        expected = {0.2: [0, 0, 0, 0], 0.5: [2, 1, 1, 3], 0.8: [4, 5, 5, 6], 1.2: [7, 7, 7, 7]}
        for vm, indices in expected.items():
            for wc, expected_index in zip([20, 40, 60, 80], indices):
                self.assertEqual(label_index(vm, wc), expected_index)
        self.assertEqual(CLASSES[2]["code"], "D W/O&O")
        self.assertEqual(CLASSES[3]["code"], "D O/W&W")
        self.assertIsNone(known_label({}))

    def test_features_are_finite_deterministic_pixels_only(self):
        image = np.random.default_rng(19).integers(0, 256, (700, 1024, 3), dtype=np.uint8)
        a, _ = visual_features([image, image, image], 3)
        b, _ = visual_features([image.copy(), image.copy(), image.copy()], 3)
        self.assertEqual(a.shape, (274,))
        np.testing.assert_array_equal(a, b)
        self.assertTrue(np.isfinite(a).all())
        interface = features(image)
        self.assertEqual(interface.shape[-1], 21)
        self.assertTrue(np.isfinite(interface).all())

    def test_ineligible_patterns_fail_before_loading_models(self):
        with tempfile.TemporaryDirectory() as tmp:
            for pattern in ("DW_O", "DO_W", "FULL"):
                with self.assertRaisesRegex(ValueError, "not applicable"):
                    track({"pattern": pattern}, Path(tmp), None, lambda *a, **k: None)


if __name__ == "__main__":
    unittest.main()
