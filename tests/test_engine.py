"""Measurement and boundary tests; run with Python's standard unittest runner."""

import sys
import tempfile
import unittest
from pathlib import Path
import json
import numpy as np
import cv2

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "engine"))
from worker import (
    Source,
    estimate,
    validate,
    make_demo,
    analyze,
    parse_conditions,
    clip_indices,
    prepare_clip,
)


class Measurements(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.base = Path(cls.tmp.name)
        cls.video = cls.base / "translation.npz"
        make_demo(cls.video)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_known_translation_sign_and_scale(self):
        with Source(self.video) as s:
            flow = estimate(s.read(0), s.read(1))[20:-20, 20:-20]
            self.assertAlmostEqual(float(np.median(flow[..., 0])), 2.0, delta=0.1)
            self.assertAlmostEqual(float(np.median(flow[..., 1])), 0.0, delta=0.1)

    def test_nonzero_frame_selection(self):
        with Source(self.video) as s:
            a = s.read(17)
            b = s.read(19)
            flow = estimate(a, b)[20:-20, 20:-20]
            self.assertAlmostEqual(float(np.median(flow[..., 0])), 4.0, delta=0.15)
            self.assertFalse(np.array_equal(s.read(17), s.read(0)))

    def test_reverse_motion(self):
        with Source(self.video) as s:
            flow = estimate(s.read(1), s.read(0))[20:-20, 20:-20]
            self.assertAlmostEqual(float(np.median(flow[..., 0])), -2.0, delta=0.1)

    def test_stationary(self):
        with Source(self.video) as s:
            a = s.read(3)
            flow = estimate(a, a)[20:-20, 20:-20]
            self.assertLess(float(np.max(np.abs(flow))), 0.01)

    def test_boundaries_and_calibration(self):
        with Source(self.video) as s:
            for req in [
                dict(start=60, pairs=1),
                dict(start=-1),
                dict(roi=[0, 0, 500, 100]),
                dict(pairs=0),
                dict(gap=0),
                dict(calibration_confirmed=True, fps=0, mm_per_pixel=1),
            ]:
                with self.subTest(req=req), self.assertRaises(ValueError):
                    validate(req, s)
            with self.assertRaises(ValueError):
                s.read(61)

    def test_gap_normalization_physical_units_and_exports(self):
        out = self.base / "result"
        out.mkdir(exist_ok=True)
        req = dict(
            source=str(self.video),
            output=str(out),
            start=11,
            pairs=3,
            gap=2,
            roi=[24, 24, 240, 130],
            fps=100,
            mm_per_pixel=0.1,
            calibration_confirmed=True,
        )
        (out / "request.json").write_text(json.dumps(req))
        analyze(req, out)
        r = json.loads((out / "result.json").read_text())
        self.assertAlmostEqual(r["median_dx_px_per_source_frame"], 2, delta=0.15)
        self.assertAlmostEqual(r["velocity_m_per_s"], 0.02, delta=0.0015)
        for file in r["files"]:
            self.assertTrue((out / file).exists(), file)

    def test_cancel_does_not_publish_result(self):
        out = self.base / "cancel"
        out.mkdir()
        (out / "cancel.flag").touch()
        analyze(dict(source=str(self.video), pairs=2), out)
        self.assertFalse((out / "result.json").exists())

    def test_unconfirmed_calibration_never_exports_physical_velocity(self):
        out = self.base / "uncalibrated"
        out.mkdir()
        analyze(dict(source=str(self.video), pairs=1, fps=100, mm_per_pixel=0.1), out)
        self.assertIsNone(json.loads((out / "result.json").read_text())["velocity_m_per_s"])

    def test_user_pipe_scale_gives_correct_velocity(self):
        out = self.base / "pipe-calibration"
        out.mkdir()
        analyze(
            dict(
                source=str(self.video),
                pairs=2,
                fps=300,
                mm_per_pixel=50 / 600,
                calibration_confirmed=True,
                calibration_is_approximate=True,
            ),
            out,
        )
        r = json.loads((out / "result.json").read_text())
        # 2 pixels/source frame * 300 frames/s * (50/600) mm/pixel / 1000 = 0.05 m/s.
        self.assertAlmostEqual(r["velocity_m_per_s"], 0.05, delta=0.001)
        self.assertTrue(any("Approximate spatial calibration" in w for w in r["warnings"]))

    def test_filename_conditions_are_experimental_labels(self):
        for code, vm in [("02", 0.2), ("05", 0.5), ("08", 0.8), ("12", 1.2)]:
            for wc in (20, 40, 60, 80):
                conditions = parse_conditions(f"vm{code}wc{wc}.cine")
                self.assertEqual(conditions["mixture_velocity_m_per_s"], vm)
                self.assertEqual(conditions["water_cut_percent"], wc)
        self.assertIsNone(parse_conditions("vm05wc140.cine"))
        self.assertIsNone(parse_conditions("synthetic.npz"))

    def test_playback_includes_intermediate_frames_and_original_indices(self):
        out = self.base / "clip"
        out.mkdir()
        prepare_clip(dict(source=str(self.video), start=7, pairs=3, gap=2, fps=100), out)
        clip = json.loads((out / "clip.json").read_text())
        self.assertEqual([f["frame"] for f in clip["frames"]], list(range(7, 14)))
        self.assertEqual(clip["frames"][-1]["seconds_from_start"], 0.06)
        self.assertEqual(clip["frames"][0]["original_frame"], 7)
        self.assertEqual(clip["preview_stride"], 1)
        with Source(self.video) as s:
            np.testing.assert_array_equal(
                cv2.imdecode(
                    np.fromfile(clip["original_preview"], dtype=np.uint8), cv2.IMREAD_UNCHANGED
                ),
                s.read(7),
            )
        for f in clip["frames"]:
            self.assertIsNotNone(
                cv2.imdecode(np.fromfile(out / f["file"], dtype=np.uint8), cv2.IMREAD_COLOR)
            )

    def test_long_playback_is_bounded_and_retains_endpoints(self):
        indices, stride = clip_indices(100, 20100)
        self.assertLessEqual(len(indices), 401)
        self.assertEqual(indices[0], 100)
        self.assertEqual(indices[-1], 20100)
        self.assertGreater(stride, 1)
        with self.assertRaises(ValueError):
            clip_indices(5, 5)

    def test_cancel_playback_does_not_publish_clip(self):
        out = self.base / "clip-cancel"
        out.mkdir()
        (out / "cancel.flag").touch()
        prepare_clip(dict(source=str(self.video), pairs=2), out)
        self.assertFalse((out / "clip.json").exists())

    def test_excerpt_conditions_and_original_frame_mapping(self):
        excerpt = self.base / "excerpt.npz"
        with Source(self.video) as s:
            np.savez_compressed(
                excerpt,
                frames=np.stack([s.read(i) for i in range(3)]),
                fps=100,
                provenance=json.dumps(dict(name="vm05wc40.cine", original_start_frame=15000)),
            )
        out = self.base / "excerpt-clip"
        out.mkdir()
        prepare_clip(dict(source=str(excerpt), pairs=2, fps=100), out)
        clip = json.loads((out / "clip.json").read_text())
        self.assertEqual(clip["frames"][0]["original_frame"], 15000)
        self.assertEqual(clip["frames"][-1]["original_frame"], 15002)
        self.assertEqual(clip["source"]["experimental_conditions"]["mixture_velocity_m_per_s"], 0.5)

    def test_pair_spacing_samples_adjacent_frames_over_longer_time(self):
        out = self.base / "spaced"
        out.mkdir()
        req = dict(
            source=str(self.video),
            start=5,
            pairs=3,
            gap=1,
            pair_step=10,
            fps=100,
            roi=[24, 24, 240, 130],
        )
        analyze(req, out)
        t = json.loads((out / "timeline.json").read_text())
        self.assertEqual(
            [(p["frame_a"], p["frame_b"]) for p in t["pairs"]], [(5, 6), (15, 16), (25, 26)]
        )
        np.testing.assert_allclose(
            [p["midpoint_seconds_from_start"] for p in t["pairs"]], [0.005, 0.105, 0.205]
        )
        for p in t["pairs"]:
            self.assertAlmostEqual(p["median_dx_px_per_source_frame"], 2, delta=0.15)
        with Source(self.video) as s:
            with self.assertRaises(ValueError):
                validate(dict(start=50, pairs=3, gap=1, pair_step=10), s)

    def test_profile_evolution_retains_changing_velocity(self):
        varying = self.base / "accelerating.npz"
        with Source(self.video) as s:
            base = s.read(0)
        frames = np.stack(
            [
                cv2.warpAffine(
                    base, np.float32([[1, 0, x], [0, 1, 0]]), (320, 192), borderMode=cv2.BORDER_WRAP
                )
                for x in [0, 1, 3, 6, 10]
            ]
        )
        np.savez_compressed(varying, frames=frames, fps=300)
        out = self.base / "evolution"
        out.mkdir()
        analyze(
            dict(
                source=str(varying),
                pairs=4,
                gap=1,
                pair_step=1,
                fps=300,
                mm_per_pixel=50 / 600,
                calibration_confirmed=True,
                roi=[24, 24, 240, 130],
            ),
            out,
        )
        t = json.loads((out / "timeline.json").read_text())
        self.assertEqual(t["units"], "m/s")
        self.assertEqual(len(t["profiles"]), 4)
        for i, p in enumerate(t["profiles"]):
            med = [v for v in p["median"] if v is not None]
            self.assertAlmostEqual(float(np.median(med)), 0.025 * (i + 1), delta=0.004)
        np.testing.assert_allclose(
            [p["midpoint_seconds_from_start"] for p in t["pairs"]], np.arange(0.5, 4) / 300
        )
        self.assertTrue((out / "profile_timeline.png").is_file())
        self.assertTrue((out / "velocity_vs_time.png").is_file())
        self.assertEqual(
            len((out / "profile_evolution.csv").read_text(encoding="utf-8-sig").splitlines()),
            1 + 4 * 130,
        )
        for i, pair in enumerate(t["pairs"]):
            self.assertEqual(pair["frame_a"], i)
            self.assertEqual(pair["frame_b"], i + 1)
            for key in ("frame_preview", "frame_b_preview", "vector_preview"):
                self.assertTrue((out / pair[key]).is_file())
            b = cv2.imdecode(
                np.fromfile(out / pair["frame_b_preview"], dtype=np.uint8), cv2.IMREAD_GRAYSCALE
            )
            self.assertLess(
                float(np.mean(np.abs(b.astype(float) - frames[i + 1].astype(float)))), 3
            )

    def test_profile_missing_texture_stays_missing(self):
        from timeline import row_statistics

        field = np.ones((20, 30), np.float32) * 4
        valid = np.ones_like(field, dtype=bool)
        valid[:5] = False
        med, top, coverage = row_statistics(field, valid)
        self.assertTrue(np.isnan(med[:5]).all())
        self.assertTrue(np.isnan(top[:5]).all())
        self.assertTrue((coverage[:5] == 0).all())
        np.testing.assert_allclose(med[5:], 4)


if __name__ == "__main__":
    unittest.main(verbosity=2)
