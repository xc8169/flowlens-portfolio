"""Prediction-only interface inference; bundled trained numerical model."""

from pathlib import Path
import csv
import hashlib
import json
import shutil
import cv2
import numpy as np
import matplotlib.pyplot as plt
from timeline import preview_frame
from flow_patterns import fingerprint

FEATURE_VERSION = "interface-texture-v1"

SUPPORTED = {"ST", "ST_MI", "DW_O_O", "DO_W_W", "DUAL"}

EXCLUDED = {"DW_O", "DO_W", "FULL"}

MAX_W, MAX_H = 240, 160


def write_json(path, value):
    Path(path).write_text(json.dumps(value, indent=2, allow_nan=False), encoding="utf-8")


def stopped(out, emit):
    if (out / "cancel.flag").exists():
        emit("cancelled", message="Interface operation cancelled; previous model/results kept.")
        return True
    return False


def validate_roi(roi, width, height):
    if len(roi) != 4 or any(not isinstance(v, (int, np.integer)) for v in roi):
        raise ValueError("ROI must contain four integers.")
    x, y, w, h = roi
    if x < 0 or y < 0 or w < 24 or h < 24 or x + w > width or y + h > height:
        raise ValueError("Select a search region inside the image, at least 24 × 24 pixels.")
    return x, y, w, h


def source_identity(source):
    origin = source.origin
    original = Path(origin.get("path", source.path))
    group = fingerprint(original) if original.is_file() else fingerprint(source.path)
    return group, int(origin.get("original_start_frame", 0))


def features(crop):
    h, w = crop.shape[:2]
    rw = min(MAX_W, w)
    rh = min(MAX_H, max(24, round(h * rw / w)))
    im = cv2.resize(crop, (rw, rh), interpolation=cv2.INTER_AREA).astype(np.float32) / 255
    g = im[..., 1]
    lo, hi = np.percentile(g, [2, 98])
    z = np.clip((g - lo) / max(float(hi - lo), 0.05), 0, 1).astype(np.float32)
    gx = cv2.Sobel(z, cv2.CV_32F, 1, 0, ksize=3) / 4
    gy = cv2.Sobel(z, cv2.CV_32F, 0, 1, ksize=3) / 4
    fs = [
        g,
        z,
        im[..., 0] - g,
        im[..., 2] - g,
        gx,
        gy,
        np.abs(gx),
        np.abs(gy),
        cv2.Laplacian(z, cv2.CV_32F),
    ]
    for size in (3, 9, 21):
        mu = cv2.blur(z, (size, size))
        sd = np.sqrt(np.maximum(0, cv2.blur(z * z, (size, size)) - mu * mu))
        offset = max(1, size // 2)
        above = np.pad(mu, ((offset, 0), (0, 0)), mode="edge")[:-offset]
        below = np.pad(mu, ((0, offset), (0, 0)), mode="edge")[offset:]
        fs.extend([mu, sd, below - above, np.abs(below - above)])
    return np.stack(fs, axis=-1).astype(np.float32)


class InterfaceModel:
    def __init__(self, folder):
        self.folder = Path(folder)
        self.card = json.loads((self.folder / "model_card.json").read_text())
        if self.card["feature_version"] != FEATURE_VERSION:
            raise ValueError("Incompatible interface model.")
        with np.load(self.folder / "forest.npz", allow_pickle=False) as d:
            self.data = {k: d[k] for k in d.files}

    def scores(self, x):
        x = np.asarray(x, dtype=np.float32)
        d = self.data
        answer = np.zeros(len(x))
        rows = np.arange(len(x))
        for tree in range(len(d["left"])):
            nodes = np.zeros(len(x), np.int32)
            while True:
                active = d["left"][tree, nodes] >= 0
                if not active.any():
                    break
                r = rows[active]
                node = nodes[active]
                nodes[active] = np.where(
                    x[r, d["feature"][tree, node]] <= d["threshold"][tree, node],
                    d["left"][tree, node],
                    d["right"][tree, node],
                )
            answer += d["value"][tree, nodes]
        return answer / len(d["left"])


def trace_path(scores):
    """A smooth path through image evidence; no prior frame or manual-y input."""
    h, w = scores.shape
    cost = -np.log(np.clip(scores, 0.001, 0.999))
    acc = cost[:, 0].copy()
    parents = np.zeros((w, h), np.int16)
    rows = np.arange(h)
    for col in range(1, w):
        options = []
        for shift in range(-3, 4):
            previous = rows + shift
            valid = (previous >= 0) & (previous < h)
            options.append(
                np.where(valid, acc[np.clip(previous, 0, h - 1)] + 0.16 * abs(shift), np.inf)
            )
        matrix = np.stack(options)
        choice = matrix.argmin(axis=0)
        parents[col] = np.clip(rows + choice - 3, 0, h - 1)
        acc = matrix[choice, rows] + cost[:, col]
    path = np.zeros(w, np.int32)
    path[-1] = acc.argmin()
    for col in range(w - 1, 0, -1):
        path[col - 1] = parents[col, path[col]]
    return path


def detect(crop, roi, model):
    if hasattr(model, "probability"):
        from torch_interface import decode

        return decode(model.probability(crop), crop, roi)
    f = features(crop)
    h, w = f.shape[:2]
    scores = model.scores(f.reshape(-1, f.shape[-1])).reshape(h, w)
    path = trace_path(scores)
    votes = scores[path, np.arange(w)]
    good = votes >= 0.55
    contrast = float(np.std(cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)))
    accepted = contrast >= 2 and good.mean() >= 0.5 and np.median(votes) >= 0.60
    if not accepted:
        good[:] = False
    x, y, rw, rh = roi
    xs = x + np.arange(w) * (rw - 1) / max(1, w - 1)
    ys = y + path * (rh - 1) / max(1, h - 1)
    valid = ys[good]
    return dict(
        x=xs.tolist(),
        y=[float(v) if ok else None for v, ok in zip(ys, good)],
        scores=votes.tolist(),
        median_row_px=float(np.median(valid)) if len(valid) else None,
        coverage=float(good.mean()),
        model_score=float(np.median(votes)),
        status="Review required" if accepted else "No reliable boundary detected",
        accepted=bool(accepted),
    )


def current_model(models_dir, device="auto"):
    root = Path(models_dir)
    pointer = root / "current.json"
    if not pointer.exists():
        raise ValueError(
            "Bundled interface model missing. Keep the complete release folder together."
        )
    version = json.loads(pointer.read_text())["directory"]
    if Path(version).name != version:
        raise ValueError("Invalid interface model directory.")
    folder = root / version
    card = json.loads((folder / "model_card.json").read_text())
    if "architecture" in card:
        from torch_interface import TorchInterfaceModel

        return TorchInterfaceModel(folder, device)
    return InterfaceModel(folder)


def track(req, out, Source, emit):
    if req["pattern"] not in SUPPORTED:
        raise ValueError(
            "Interface tracking is not applicable to fully dispersed or fully mixed flow. Choose a supported layered pattern."
        )
    model = current_model(req["models_dir"], req.get("device", "auto"))
    artifact = "weights.pt" if hasattr(model, "probability") else "forest.npz"
    shutil.copy2(model.folder / artifact, out / artifact)
    shutil.copy2(model.folder / "model_card.json", out / "model_card.json")
    with Source(req["source"]) as source:
        roi = list(validate_roi(req["roi"], source.width, source.height))
        x, y, w, h = roi
        start, count, step = int(req["start"]), int(req["pairs"]), int(req["pair_step"])
        fps = float(req.get("fps", source.fps))
        if (
            start < 0
            or not 1 <= count <= 200
            or step < 1
            or start + (count - 1) * step >= source.count
            or not np.isfinite(fps)
            or fps < 0
        ):
            raise ValueError("Invalid interface tracking range or FPS.")
        scale = float(req.get("mm_per_pixel", 0))
        physical = bool(req.get("calibration_confirmed", False)) and scale > 0
        if not np.isfinite(scale):
            raise ValueError("Invalid spatial scale.")
        group, offset = source_identity(source)
        frames = []
        reference = None
        with (out / "interface_points.csv").open("w", newline="", encoding="utf-8-sig") as f:
            writer = csv.writer(f)
            writer.writerow(
                [
                    "frame",
                    "original_frame",
                    "seconds_from_start",
                    "x_px",
                    "y_px",
                    "model_score_uncalibrated",
                ]
            )
            for i in range(count):
                if stopped(out, emit):
                    return
                index = start + i * step
                im = source.read(index)
                d = detect(im[y : y + h, x : x + w], roi, model)
                row = d["median_row_px"]
                seconds = (index - start) / fps if fps > 0 else None
                if reference is None and row is not None:
                    reference = row
                d.update(
                    frame=index,
                    original_frame=index + offset,
                    seconds_from_start=seconds,
                    displacement_from_first_detected_px=(
                        row - reference if row is not None else None
                    ),
                    displacement_mm=(
                        (row - reference) * scale if physical and row is not None else None
                    ),
                )
                overlay = im.copy()
                previous = None
                for xx, yy, score in zip(d["x"], d["y"], d["scores"]):
                    writer.writerow([index, index + offset, seconds, xx, yy, score])
                    if yy is None:
                        previous = None
                        continue
                    point = (round(xx), round(yy))
                    if previous is not None:
                        cv2.line(overlay, previous, point, (255, 220, 0), 2, cv2.LINE_AA)
                    previous = point
                cv2.rectangle(overlay, (x, y), (x + w - 1, y + h - 1), (120, 180, 150), 1)
                file = f"interface-{i:04d}.jpg"
                preview_frame(out / file, overlay)
                d["preview"] = file
                frames.append(d)
                emit(
                    "progress",
                    progress=int(90 * (i + 1) / count),
                    message=f"Tracking interface frame {i+1}/{count}",
                )
        with (out / "interface_positions.csv").open("w", newline="", encoding="utf-8-sig") as f:
            writer = csv.writer(f)
            writer.writerow(
                [
                    "frame",
                    "original_frame",
                    "seconds_from_start",
                    "median_row_px",
                    "displacement_px",
                    "displacement_mm",
                    "accepted_column_fraction",
                    "model_score_uncalibrated",
                    "status",
                ]
            )
            for d in frames:
                writer.writerow(
                    [
                        d["frame"],
                        d["original_frame"],
                        d["seconds_from_start"],
                        d["median_row_px"],
                        d["displacement_from_first_detected_px"],
                        d["displacement_mm"],
                        d["coverage"],
                        d["model_score"],
                        d["status"],
                    ]
                )
        times = [d["seconds_from_start"] if fps > 0 else i + 1 for i, d in enumerate(frames)]
        positions = [np.nan if d["median_row_px"] is None else d["median_row_px"] for d in frames]
        fig, ax = plt.subplots(figsize=(8, 3.1), layout="constrained")
        ax.plot(times, positions, color="#177e8a", marker=".", linewidth=1.2)
        ax.invert_yaxis()
        ax.grid(alpha=0.2)
        ax.set(
            xlabel="Time from selection start (s)" if fps > 0 else "Sample index",
            ylabel="Median interface image row (px; down)",
            title="Interface position over time · review required",
        )
        fig.savefig(out / "interface_timeline.png", dpi=130)
        plt.close(fig)
        runtime = (
            model.runtime()
            if hasattr(model, "runtime")
            else dict(
                backend="NumPy random forest", device="cpu", device_name="CPU", fallback_reason=None
            )
        )
        result = dict(
            version="0.8.0",
            source=source.meta(),
            request=req,
            roi=roi,
            pattern=req["pattern"],
            model_version=model.card["model_version"],
            runtime=runtime,
            training_source=group in model.card["training_groups"],
            unseen_pattern=req["pattern"] not in model.card["patterns"],
            validation=model.card["validation"],
            physical_displacement=physical,
            calibration_approximate=bool(req.get("calibration_is_approximate", False)),
            frames=frames,
            notes="Cyan line is a model suggestion; review every result. Missing detections remain null. Positive displacement is downward in image coordinates. Millimetres describe relative image displacement, not water-layer height. Samples are frame A of the shared pair range; no temporal interpolation or propagation is imposed.",
        )
        if stopped(out, emit):
            return
        write_json(out / "interface.json", result)
        emit("interface_result", result=result)
