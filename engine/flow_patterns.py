"""Image-only supervised flow-regime inference. Metadata labels never enter features."""

import csv
import hashlib
import json
from pathlib import Path
import numpy as np
import cv2

FEATURE_VERSION = "visual-clip-v1"
CANONICAL_ROI = [
    0.29,
    0.06,
    0.98,
    0.90,
]  # Supplied fixed-camera view: exclude ruler and black borders.
CLASSES = [
    dict(id="ST", name="Stratified flow (ST)", code="ST"),
    dict(id="ST_MI", name="Stratified flow with mixing at the interface (ST&MI)", code="ST&MI"),
    dict(id="DW_O_O", name="Dispersion of water in oil and oil (D W/O&O)", code="D W/O&O"),
    dict(id="DO_W_W", name="Dispersion of oil in water and water (D O/W&W)", code="D O/W&W"),
    dict(id="DW_O", name="Dispersion of water in oil (D W/O)", code="D W/O"),
    dict(id="DUAL", name="Dual dispersion (D O/W&W/O)", code="D O/W&W/O"),
    dict(id="DO_W", name="Dispersion of oil in water (D O/W)", code="D O/W"),
    dict(id="FULL", name="Fully mixed flow", code="Fully mixed"),
]


def label_index(vm, wc):
    if abs(vm - 0.2) < 1e-6 and wc in (20, 40, 60, 80):
        return 0
    if abs(vm - 0.5) < 1e-6:
        return {20: 2, 40: 1, 60: 1, 80: 3}.get(wc)
    if abs(vm - 0.8) < 1e-6:
        return {20: 4, 40: 5, 60: 5, 80: 6}.get(wc)
    if abs(vm - 1.2) < 1e-6 and wc in (20, 40, 60, 80):
        return 7
    return None


def known_label(meta):
    condition = meta.get("experimental_conditions")
    if not condition:
        return None
    idx = label_index(condition["mixture_velocity_m_per_s"], condition["water_cut_percent"])
    return (
        dict(CLASSES[idx], class_index=idx, source="User-supplied Vm/WC recording label")
        if idx is not None
        else None
    )


def fingerprint(path):
    p = Path(path)
    with p.open("rb") as f:
        head = f.read(1048576)
    return hashlib.sha256(str(p.stat().st_size).encode() + head).hexdigest()


def crop_frame(frame):
    height, width = frame.shape[:2]
    x0, y0, x1, y1 = CANONICAL_ROI
    crop = frame[round(height * y0) : round(height * y1), round(width * x0) : round(width * x1)]
    if crop.size == 0:
        raise ValueError("The image is too small for flow-pattern classification.")
    a = crop if crop.ndim == 2 else crop[..., 1]
    return cv2.resize(a, (256, 192), interpolation=cv2.INTER_AREA)


def visual_features(frames, gap=3):
    """All inputs are pixels and frame gap. No path, Vm, WC, class or frame index."""
    if len(frames) < 2 or gap < 1:
        raise ValueError("Classification needs at least two frames and a positive frame gap.")
    raw = np.stack([crop_frame(f).astype(np.float32) / 255 for f in frames])
    low, high = np.percentile(raw, [1, 99])
    contrast = float(high - low)
    norm = np.clip((raw - low) / max(contrast, 0.03), 0, 1).astype(np.float32)
    a = np.mean(norm, axis=0)
    bands = a.reshape(16, 12, 256)
    patch = a.reshape(6, 32, 8, 32).transpose(0, 2, 1, 3).reshape(48, 1024)
    dx = cv2.Sobel(a, cv2.CV_32F, 1, 0, ksize=3)
    dy = cv2.Sobel(a, cv2.CV_32F, 0, 1, ksize=3)
    mag = np.hypot(dx, dy)
    edges = mag > 0.22
    lap = cv2.Laplacian(a, cv2.CV_32F)
    diff = np.mean(np.abs(np.diff(norm, axis=0)), axis=0) / gap
    hist = np.histogram(a, bins=16, range=(0, 1))[0] / a.size
    gradient_hist = np.histogram(np.clip(mag, 0, 4), bins=12, range=(0, 4))[0] / a.size
    # LBP distribution describes local texture without a learned neural network.
    center = a[1:-1, 1:-1]
    lbp = np.zeros_like(center, dtype=np.uint8)
    for bit, (yy, xx) in enumerate(
        [(0, 0), (0, 1), (0, 2), (1, 2), (2, 2), (2, 1), (2, 0), (1, 0)]
    ):
        lbp |= (a[yy : yy + 190, xx : xx + 254] >= center).astype(np.uint8) << bit
    lbp_hist = np.histogram(lbp, bins=32, range=(0, 256))[0] / lbp.size
    vector = np.concatenate(
        [
            patch.mean(axis=1),
            patch.std(axis=1),
            bands.mean(axis=(1, 2)),
            bands.std(axis=(1, 2)),
            np.abs(dx).reshape(16, 12, 256).mean(axis=(1, 2)),
            np.abs(dy).reshape(16, 12, 256).mean(axis=(1, 2)),
            edges.reshape(16, 12, 256).mean(axis=(1, 2)),
            np.abs(lap).reshape(16, 12, 256).mean(axis=(1, 2)),
            diff.reshape(16, 12, 256).mean(axis=(1, 2)),
            hist,
            gradient_hist,
            lbp_hist,
            [
                contrast,
                float(raw.mean()),
                float(raw.std()),
                float(diff.mean()),
                float(diff.std()),
                float(edges.mean()),
            ],
        ]
    ).astype(np.float32)
    if not np.isfinite(vector).all():
        raise ValueError("Image feature extraction produced invalid values.")
    return vector, dict(contrast=contrast, edge_fraction=float(edges.mean()))


class VisualForest:
    """Portable inference for exported sklearn trees; loads no executable pickle."""

    def __init__(self, model_dir):
        root = Path(model_dir)
        self.card = json.loads((root / "model_card.json").read_text(encoding="utf-8"))
        if self.card["feature_version"] != FEATURE_VERSION:
            raise ValueError("The model feature version is incompatible.")
        with np.load(root / "visual_forest.npz", allow_pickle=False) as data:
            self.data = {k: data[k] for k in data.files}
        self.classes = self.card["classes"]

    def predict_scores(self, features):
        x = np.atleast_2d(features).astype(np.float32)
        if x.shape[1] != self.card["feature_count"]:
            raise ValueError("Wrong feature dimension for the trained model.")
        d = self.data
        result = np.zeros((len(x), len(self.classes)), np.float64)
        for tree in range(len(d["node_counts"])):
            nodes = np.zeros(len(x), dtype=np.int32)
            while True:
                active = d["left"][tree, nodes] >= 0
                if not active.any():
                    break
                row = np.flatnonzero(active)
                node = nodes[row]
                choice = x[row, d["feature"][tree, node]] <= d["threshold"][tree, node]
                nodes[row] = np.where(choice, d["left"][tree, node], d["right"][tree, node])
            result += d["value"][tree, nodes]
        return result / len(d["node_counts"])

    def nearest_distance(self, features):
        z = (np.atleast_2d(features) - self.data["mean"]) / self.data["std"]
        refs = self.data["reference_z"]
        return np.sqrt(
            np.maximum(
                0,
                (z * z).mean(axis=1)[:, None]
                + (refs * refs).mean(axis=1)[None, :]
                - 2 * z @ refs.T / z.shape[1],
            )
        ).min(axis=1)


def classify_range(req, out, source_factory, emit):
    model = VisualForest(req["model_dir"])
    with source_factory(req["source"]) as source:
        meta = source.meta()
        start = int(req.get("start", 0))
        pairs = int(req.get("pairs", 20))
        gap = int(req.get("gap", 1))
        step = int(req.get("pair_step", gap))
        if pairs < 1 or pairs > 200 or gap < 1 or gap > 100 or step < 1 or step > 100000:
            raise ValueError("Invalid selected range for classification.")
        end = start + (pairs - 1) * step + gap
        if start < 0 or end >= source.count:
            raise ValueError("The classification range exceeds the video.")
        if source.width < 400 or source.height < 400 or not 0.9 < source.width / source.height < 2:
            raise ValueError(
                "This model was trained on the supplied fixed-camera pipe recordings. Use that view; small or differently framed videos are unsupported."
            )
        context_gap = min(3, max(1, (end - start) // 2))
        clip_length = 2 * context_gap
        if end - start < clip_length:
            starts = [start]
            offsets = [0, end - start]
        else:
            count = min(12, max(1, (end - start + 1) // (clip_length + 1)))
            starts = np.unique(np.linspace(start, end - clip_length, count).astype(int)).tolist()
            offsets = [0, context_gap, clip_length]
        features = []
        quality = []
        clips = []
        fps = float(req.get("fps", source.fps))
        if not np.isfinite(fps) or fps < 0:
            raise ValueError("Acquisition FPS must be a finite nonnegative number.")
        for i, a in enumerate(starts):
            if (out / "cancel.flag").exists():
                emit("cancelled", message="Classification cancelled.")
                return
            frames = [source.read(a + offset) for offset in offsets]
            v, q = visual_features(frames, context_gap)
            features.append(v)
            quality.append(q)
            clips.append(
                dict(
                    frame_a=a,
                    frame_b=a + offsets[-1],
                    midpoint_seconds_from_start=(
                        (a + offsets[-1] / 2 - start) / fps if fps > 0 else None
                    ),
                )
            )
            emit(
                "progress",
                progress=int(80 * (i + 1) / len(starts)),
                message=f"Classifying image clip {i+1} / {len(starts)}",
            )
        x = np.stack(features)
        scores = model.predict_scores(x)
        distances = model.nearest_distance(x)
        average = scores.mean(axis=0)
        order = np.argsort(average)[::-1]
        best = int(order[0])
        margin = float(average[order[0]] - average[order[1]])
        reasons = []
        if model.card["evaluation_summary"]["held_out_recording_clip_accuracy"] < 0.7:
            reasons.append(
                "Experimental model: limited held-out-recording performance; every prediction requires review."
            )
        if float(average[best]) < 0.55 or margin < 0.10:
            reasons.append("Low separation between model classes (heuristic review threshold).")
        if (
            np.mean([q["contrast"] for q in quality]) < 0.04
            or np.mean([q["edge_fraction"] for q in quality]) < 0.003
        ):
            reasons.append("Very low image contrast or detail.")
        if float(np.median(distances)) > model.card["feature_distance_review_threshold"]:
            reasons.append("Image features differ substantially from the training views.")
        expected = known_label(meta)
        if source.path.suffix.lower() == ".cine":
            source_fingerprint = fingerprint(source.path)
            seen = any(r["fingerprint"] == source_fingerprint for r in model.card["recordings"])
        else:
            origin = meta.get("provenance", {})
            seen = any(
                r["name"] == origin.get("name") and r["size_bytes"] == origin.get("size_bytes")
                for r in model.card["recordings"]
            )
        for i, clip in enumerate(clips):
            index = int(np.argmax(scores[i]))
            clip.update(
                predicted_class=model.classes[index]["name"],
                model_score=float(scores[i, index]),
                feature_distance=float(distances[i]),
            )
        output = dict(
            model_version=model.card["model_version"],
            method="Random forest on image texture, vertical structure and short-clip difference features",
            prediction=model.classes[best],
            model_score=float(average[best]),
            score_note="Uncalibrated forest score; not a probability of correctness.",
            margin=margin,
            decision="Review required" if reasons else "Provisional prediction",
            review_reasons=reasons,
            known_experimental_label=expected,
            agrees_with_known_label=(
                (model.classes[best]["id"] == expected["id"]) if expected else None
            ),
            source_was_in_training=seen,
            training_source_note=(
                "This recording or its excerpt contributed training images. Agreement is not held-out validation."
                if seen
                else "This source was not matched to the training recordings; no guarantee of generalization."
            ),
            rankings=[dict(model.classes[int(j)], score=float(average[j])) for j in order],
            clips=clips,
            source=meta,
            request=req,
            view_crop_fractions=CANONICAL_ROI,
            model_limitations=model.card["limitations"],
            evaluation=model.card["evaluation_summary"],
            note="Filename/Vm/WC are used only to display the separate known experimental label; they are not classifier inputs. The fixed interior crop excludes the ruler and borders and is independent of the velocity ROI.",
        )
        crop = crop_frame(source.read(start))
        ok, preview = cv2.imencode(".png", crop)
        if not ok:
            raise ValueError("Could not encode the classifier view.")
        preview.tofile(str(out / "classification_view.png"))
        output["preview"] = "classification_view.png"
        if (out / "cancel.flag").exists():
            emit("cancelled", message="Classification cancelled.")
            return
        (out / "classification.json").write_text(
            json.dumps(output, indent=2, allow_nan=False), encoding="utf-8"
        )
        with (out / "classification_clips.csv").open("w", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fieldnames=list(clips[0]))
            w.writeheader()
            w.writerows(clips)
        emit("classification", result=output, path=str(out / "classification.json"))
