"""Inference/runtime contracts tested with temporary UNTRAINED weights.

These tests do not measure research accuracy and require no research recordings.
"""

from pathlib import Path
import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "engine"))
try:
    import torch
except ImportError:
    torch = None

if torch is not None:
    import torch_interface as ti
    import interfaces


@unittest.skipIf(
    torch is None, "Install optional PyTorch requirements to run inference/training checks"
)
class TorchPortfolio(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.folder = Path(cls.temp.name)
        torch.manual_seed(12)
        torch.save(ti.BoundaryNet().state_dict(), cls.folder / "weights.pt")
        cls.card = {
            "architecture": ti.ARCH,
            "weights_sha256": hashlib.sha256((cls.folder / "weights.pt").read_bytes()).hexdigest(),
        }
        (cls.folder / "model_card.json").write_text(json.dumps(cls.card))
        cls.image = np.random.default_rng(13).integers(0, 256, (96, 160, 3), dtype=np.uint8)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_cpu_probability_and_blank_rejection(self):
        model = ti.TorchInterfaceModel(self.folder, "cpu")
        probability = model.probability(self.image)
        self.assertEqual(model.device, "cpu")
        self.assertEqual(probability.shape, (192, 288))
        np.testing.assert_allclose(probability.sum(axis=0), 1, atol=1e-5)
        blank = interfaces.detect(np.full((96, 160, 3), 100, np.uint8), [12, 20, 160, 96], model)
        self.assertFalse(blank["accepted"])
        self.assertTrue(all(y is None for y in blank["y"]))
        self.assertEqual(blank["x"][0], 12)
        self.assertEqual(blank["x"][-1], 171)

    def test_unavailable_cuda_and_failed_initialization_fall_back(self):
        with patch.object(torch.cuda, "is_available", return_value=False):
            device, reason = ti.select_device("auto")
            self.assertEqual(device, "cpu")
            self.assertIn("unavailable", reason)
        with (
            patch.object(torch.cuda, "is_available", return_value=True),
            patch.object(torch, "ones", side_effect=RuntimeError("driver failed")),
        ):
            device, reason = ti.select_device("auto")
            self.assertEqual(device, "cpu")
            self.assertIn("driver failed", reason)

    def test_failed_cuda_execution_retries_same_weights_on_cpu(self):
        model = ti.TorchInterfaceModel(self.folder, "cpu")
        expected = model.probability(self.image)
        model.device = "cuda"
        with (
            patch.object(torch.Tensor, "to", lambda tensor, *a, **k: tensor),
            patch.object(model.net, "forward", side_effect=RuntimeError("simulated CUDA error")),
        ):
            actual = model.probability(self.image)
        self.assertEqual(model.device, "cpu")
        self.assertIn("simulated", model.fallback_reason)
        np.testing.assert_allclose(actual, expected, atol=1e-6)

    def test_actual_gpu_cpu_parity_when_cuda_is_available(self):
        if not torch.cuda.is_available():
            self.skipTest("No CUDA device; CPU/failure paths still tested")
        cpu = ti.TorchInterfaceModel(self.folder, "cpu")
        gpu = ti.TorchInterfaceModel(self.folder, "auto")
        self.assertEqual(gpu.device, "cuda")
        np.testing.assert_allclose(
            cpu.probability(self.image), gpu.probability(self.image), atol=3e-5, rtol=3e-4
        )

    def test_corrupt_checkpoint_is_rejected_before_loading(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            (folder / "model_card.json").write_text(json.dumps(self.card))
            (folder / "weights.pt").write_bytes(b"corrupted")
            with self.assertRaisesRegex(ValueError, "checksum"):
                ti.TorchInterfaceModel(folder, "cpu")

    def test_offline_trainer_on_generated_labels_preserves_inputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            labels = folder / "labels"
            labels.mkdir()
            before = {}
            for i in range(3):
                image = self.image.copy()
                path = labels / f"frame-{i}.png"
                ok, encoded = cv2.imencode(".png", image)
                self.assertTrue(ok)
                encoded.tofile(str(path))
                label = {
                    "applicable": True,
                    "absent": False,
                    "group": f"generated-video-{i}",
                    "image": path.name,
                    "image_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                    "points": [[0, 45 + i], [159, 45 + i]],
                    "roi": [0, 0, 160, 96],
                    "pattern": "ST",
                    "frame": i,
                }
                (labels / f"label-{i}.json").write_text(json.dumps(label))
            for path in labels.iterdir():
                before[path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
            completed = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "engine/train_torch_interface.py"),
                    "--labels",
                    str(labels),
                    "--models",
                    str(folder / "models"),
                    "--report",
                    str(folder / "report"),
                    "--device",
                    "cpu",
                    "--epochs",
                    "1",
                ],
                capture_output=True,
                text=True,
                timeout=120,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            card = json.loads((folder / "report/training_report.json").read_text())
            self.assertEqual(card["training"]["device"], "cpu")
            self.assertEqual(card["positive_frames"], 3)
            self.assertEqual(card["validation"]["held_out_frames"], 1)
            self.assertEqual(set(card["validation"]["held_out_groups"]), {"generated-video-2"})
            for path in labels.iterdir():
                self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), before[path.name])


if __name__ == "__main__":
    unittest.main()
