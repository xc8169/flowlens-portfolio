"""FlowLens worker. One JSON request per invocation, JSON-lines events on stdout."""

from __future__ import annotations
import argparse
import csv
import hashlib
import json
import os
import math
import re
from pathlib import Path
import struct
import sys
import time
import traceback

os.environ.setdefault("MPLCONFIGDIR", str(Path(__file__).resolve().parents[1] / ".cache"))
import cv2
import numpy as np
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from timeline import row_statistics, preview_frame, export_timeline
from flow_patterns import classify_range
from vector_display import overlay as render_vectors
import interfaces

VERSION = "0.8.0"
VECTOR_STYLE = dict(
    scale=8.0,
    max_length_px=40,
    shaft_thickness_px=2,
    outline_thickness_px=0,
    tip_fraction=0.25,
    minimum_motion_px_per_frame=0.1,
)
PARAMS = dict(pyr_scale=0.5, levels=3, winsize=15, iterations=3, poly_n=5, poly_sigma=1.2, flags=0)


def emit(kind, **data):
    print(json.dumps(dict(type=kind, **data), allow_nan=False), flush=True)


def save_json(path, value):
    Path(path).write_text(json.dumps(value, indent=2, allow_nan=False), encoding="utf-8")


def image_write(path, frame):
    ok, data = cv2.imencode(".png", frame)
    if not ok:
        raise ValueError("Could not encode preview image.")
    data.tofile(str(path))


class Source:
    """Read one frame at a time. The NPZ format is reserved for small demo excerpts."""

    def __init__(self, path):
        self.path = Path(path).resolve()
        if not self.path.is_file():
            raise ValueError("Video file does not exist: " + str(self.path))
        self.cap = None
        self.pack = None
        self.origin = {}
        self.next_index = -1
        if self.path.suffix.lower() == ".npz":
            self.pack = np.load(self.path, allow_pickle=False)
            self.frames = self.pack["frames"]
            self.count = len(self.frames)
            self.fps = float(self.pack["fps"])
            self.height, self.width = self.frames.shape[1:3]
            self.origin = (
                json.loads(str(self.pack["provenance"])) if "provenance" in self.pack else {}
            )
        else:
            self.cap = cv2.VideoCapture(str(self.path), cv2.CAP_FFMPEG)
            if not self.cap.isOpened():
                self.close()
                raise ValueError(
                    "Cannot decode this recording. Try an uncompressed CINE, MP4 or AVI, or export a short lossless excerpt from the camera software."
                )
            self.count = int(self.cap.get(cv2.CAP_PROP_FRAME_COUNT))
            self.width = int(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            self.height = int(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            self.fps = float(self.cap.get(cv2.CAP_PROP_FPS))
            if not np.isfinite(self.fps):
                self.fps = 0.0
            if self.path.suffix.lower() == ".cine":
                with self.path.open("rb") as f:
                    header = f.read(44)
                    if len(header) == 44 and header[:2] == b"CI":
                        h = struct.unpack("<2sHHHiIiIIIIQ", header)
                        f.seek(h[9] + 768)
                        raw = f.read(4)
                        if len(raw) == 4:
                            camera_fps = struct.unpack("<I", raw)[0]
                            if 0 < camera_fps < 10000000:
                                self.fps = float(camera_fps)
                                self.origin["fps_source"] = "Phantom CINE SETUP FrameRate field"
        if self.count < 2 or self.width < 8 or self.height < 8:
            self.close()
            raise ValueError("The recording needs at least two frames and valid image dimensions.")

    def read(self, index):
        if index < 0 or index >= self.count:
            raise ValueError(f"Frame {index} is outside 0–{self.count - 1}.")
        if self.pack is not None:
            im = self.frames[index].copy()
        else:
            if self.next_index != index:
                if not self.cap.set(cv2.CAP_PROP_POS_FRAMES, index):
                    raise ValueError("The decoder cannot seek to the requested frame.")
                reported = self.cap.get(cv2.CAP_PROP_POS_FRAMES)
                if abs(reported - index) > 0.5:
                    raise ValueError(
                        f"Decoder seek mismatch: requested {index}, reported {reported}."
                    )
            ok, im = self.cap.read()
            if not ok:
                raise ValueError(f"Could not decode frame {index}.")
            self.next_index = index + 1
        if im.dtype != np.uint8:
            raise ValueError(
                "This version needs 8-bit decoded images; export a consistently scaled excerpt first."
            )
        return im

    def meta(self):
        st = self.path.stat()
        condition_name = self.origin.get("name", self.path.name)
        conditions = parse_conditions(condition_name)
        return dict(
            path=str(self.path),
            name=self.path.name,
            frame_count=self.count,
            width=self.width,
            height=self.height,
            fps=self.fps,
            size_bytes=st.st_size,
            modified_ns=st.st_mtime_ns,
            provenance=self.origin,
            experimental_conditions=conditions,
            timing_note="Verify acquisition timing; ordinary video metadata can describe playback timing.",
        )

    def close(self):
        if self.cap is not None:
            self.cap.release()
        if self.pack is not None:
            self.pack.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


def parse_conditions(name):
    m = re.match(r"^vm(\d{2,}|\d+\.\d+)wc(\d{1,3})(?:\.|$)", name, re.I)
    if not m:
        return None
    code, wc = m.groups()
    vm = float(code) if "." in code else int(code) / 10
    if vm <= 0 or not 0 <= int(wc) <= 100:
        return None
    return dict(
        mixture_velocity_m_per_s=vm,
        water_cut_percent=int(wc),
        source="filename experimental label; not an optical-flow measurement",
    )


def clip_indices(start, end, max_frames=401):
    if start < 0 or end <= start:
        raise ValueError("Playback range must contain at least two frames.")
    if not 2 <= max_frames <= 401:
        raise ValueError("Playback cache supports 2–401 preview frames.")
    stride = max(1, math.ceil((end - start) / (max_frames - 1)))
    indices = list(range(start, end + 1, stride))
    if indices[-1] != end:
        indices.append(end)
    return indices, stride


def prepare_clip(req, out):
    """Generate bounded, display-only JPEG frames with original frame/time mapping."""
    with Source(req["source"]) as source:
        start, pairs, gap, _, fps, _, _, _, pair_step = validate(req, source)
        end = start + (pairs - 1) * pair_step + gap
        indices, stride = clip_indices(start, end, int(req.get("max_preview_frames", 401)))
        original_start = int(source.origin.get("original_start_frame", 0))
        frames = []
        for i, idx in enumerate(indices):
            if cancelled(out):
                return
            im = source.read(idx)
            if i == 0:
                image_write(out / "preview.png", im)
            ratio = min(1, 960 / source.width)
            if ratio < 1:
                im = cv2.resize(
                    im,
                    (round(source.width * ratio), round(source.height * ratio)),
                    interpolation=cv2.INTER_AREA,
                )
            file = f"clip-{i:04d}.jpg"
            ok, data = cv2.imencode(".jpg", im, [cv2.IMWRITE_JPEG_QUALITY, 90])
            if not ok:
                raise ValueError("Could not encode a playback frame.")
            data.tofile(str(out / file))
            frames.append(
                dict(
                    file=file,
                    frame=idx,
                    original_frame=original_start + idx,
                    seconds_from_start=(idx - start) / fps if fps > 0 else None,
                )
            )
            if i % 10 == 0 or i == len(indices) - 1:
                emit(
                    "progress",
                    progress=int((i + 1) * 100 / len(indices)),
                    message=f"Preparing video frame {i+1} / {len(indices)}",
                )
        manifest = dict(
            source=source.meta(),
            start=start,
            end=end,
            fps=fps,
            preview_stride=stride,
            frames=frames,
            original_preview=str(out / "preview.png"),
            note="JPEG previews are for viewing only; analysis always uses full-resolution source frames. Intervening frames are included when frame gap > 1, unless a long range needs preview subsampling.",
        )
        if cancelled(out):
            return
        save_json(out / "clip.json", manifest)
        emit("clip", path=str(out / "clip.json"), clip=manifest)


def gray(frame):
    # Preserve the green-channel approach used in the original notebook.
    return frame if frame.ndim == 2 else frame[..., 1]


def estimate(a, b, winsize=15):
    params = dict(PARAMS, winsize=winsize)
    return cv2.calcOpticalFlowFarneback(gray(a), gray(b), None, **params)


def texture_mask(frame):
    a = gray(frame).astype(np.float32)
    dx = cv2.Sobel(a, cv2.CV_32F, 1, 0, ksize=3)
    dy = cv2.Sobel(a, cv2.CV_32F, 0, 1, ksize=3)
    return np.hypot(dx, dy) >= 12.0


def validate(req, source):
    start, pairs, gap = (int(req.get(k, v)) for k, v in [("start", 0), ("pairs", 20), ("gap", 1)])
    pair_step = int(req.get("pair_step", gap))
    if not 1 <= pairs <= 200 or not 1 <= gap <= 100:
        raise ValueError("Use 1–200 frame pairs and a gap of 1–100 frames.")
    if pair_step < 1 or pair_step > 100000:
        raise ValueError("Pair spacing must be 1–100000 frames.")
    last = start + (pairs - 1) * pair_step + gap
    if start < 0 or last >= source.count:
        raise ValueError(
            f"Frame range exceeds the recording. Last requested frame: {last}; last available: {source.count - 1}."
        )
    roi = [int(v) for v in req.get("roi", [0, 0, source.width, source.height])]
    if len(roi) != 4:
        raise ValueError("ROI must contain x, y, width, height.")
    x, y, w, h = roi
    if x < 0 or y < 0 or w < 16 or h < 16 or x + w > source.width or y + h > source.height:
        raise ValueError(
            "The analysis region must fit inside the image and be at least 16 × 16 pixels."
        )
    fps, scale = float(req.get("fps", 0)), float(req.get("mm_per_pixel", 0))
    if not np.isfinite(fps) or not np.isfinite(scale) or fps < 0 or scale < 0:
        raise ValueError("Frame rate and spatial calibration must be finite, nonnegative numbers.")
    physical = bool(req.get("calibration_confirmed", False))
    if physical and (fps <= 0 or scale <= 0):
        raise ValueError(
            "Physical velocity needs a positive acquisition FPS and mm/pixel calibration."
        )
    winsize = int(req.get("winsize", 15))
    if winsize not in (15, 25, 35):
        raise ValueError("Window size must be 15, 25 or 35.")
    return start, pairs, gap, roi, fps, scale, physical, winsize, pair_step


def cancelled(out):
    if (out / "cancel.flag").exists():
        emit("cancelled", message="Analysis cancelled. No completed result was published.")
        return True
    return False


def csv_write(path, columns, rows):
    with Path(path).open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(columns)
        w.writerows(rows)


def analyze(req, out):
    t0 = time.perf_counter()
    with Source(req["source"]) as source:
        start, pairs, gap, roi, fps, scale, physical, winsize, pair_step = validate(req, source)
        x, y, w, h = roi
        first = source.read(start)
        previous_full = first
        previous_index = start
        flow_sum = np.zeros((h, w, 2), np.float64)
        weight = np.zeros((h, w), np.int32)
        series = []
        pair_info = []
        pair_profiles = []
        valid_total = 0
        for i in range(pairs):
            if cancelled(out):
                return
            a_index = start + i * pair_step
            if a_index != previous_index:
                previous_full = source.read(a_index)
            prev = previous_full[y : y + h, x : x + w]
            idx = a_index + gap
            next_full = source.read(idx)
            nxt = next_full[y : y + h, x : x + w]
            field = estimate(prev, nxt, winsize) / gap
            valid = texture_mask(prev) & texture_mask(nxt) & np.isfinite(field).all(axis=2)
            flow_sum += np.where(valid[..., None], field, 0)
            weight += valid
            valid_total += int(valid.sum())
            values = field[..., 0][valid]
            median = float(np.median(values)) if values.size else None
            original_start = int(source.origin.get("original_start_frame", 0))
            pair_profiles.append(row_statistics(field[..., 0], valid))
            frame_file = f"pair-{i:04d}.jpg"
            preview_frame(out / frame_file, previous_full)
            frame_b_file = f"pair-b-{i:04d}.jpg"
            overlay_file = f"pair-vectors-{i:04d}.jpg"
            preview_frame(out / frame_b_file, next_full)
            pair_overlay, _ = render_vectors(previous_full, field, valid, roi, VECTOR_STYLE)
            preview_frame(out / overlay_file, pair_overlay)
            pair_info.append(
                dict(
                    index=i,
                    frame_a=a_index,
                    frame_b=idx,
                    original_frame_a=original_start + a_index,
                    original_frame_b=original_start + idx,
                    midpoint_seconds_from_start=(
                        ((a_index + idx) / 2 - start) / fps if fps > 0 else None
                    ),
                    median_dx_px_per_source_frame=median,
                    velocity_m_per_s=(
                        median * fps * scale / 1000 if physical and median is not None else None
                    ),
                    texture_coverage=float(valid.mean()),
                    frame_preview=frame_file,
                    frame_b_preview=frame_b_file,
                    vector_preview=overlay_file,
                )
            )
            series.append(
                [
                    idx - gap,
                    idx,
                    original_start + idx - gap,
                    original_start + idx,
                    (idx - start) / fps if fps else None,
                    median,
                    median * fps * scale / 1000 if physical and median is not None else None,
                    float(valid.mean()),
                ]
            )
            previous_full = next_full
            previous_index = idx
            emit(
                "progress",
                progress=int((i + 1) * 85 / pairs),
                message=f"Analyzed pair {i+1} / {pairs}",
            )
        if cancelled(out):
            return
        field = (flow_sum / np.maximum(weight, 1)[..., None]).astype(np.float32)
        valid = weight > 0
        ux = field[..., 0]
        values = ux[valid]
        if not values.size:
            raise ValueError(
                "No textured pixels in the selected region. Choose a region with visible image features."
            )
        median = float(np.median(values))
        profile = []
        for row in range(h):
            vals = ux[row, valid[row]]
            profile.append(
                [
                    y + row,
                    float(np.median(vals)) if len(vals) else None,
                    (
                        float(np.mean(np.sort(vals)[-max(1, int(len(vals) * 0.1)) :]))
                        if len(vals)
                        else None
                    ),
                    float(valid[row].mean()),
                ]
            )
        csv_write(
            out / "motion.csv",
            [
                "frame_a",
                "frame_b",
                "original_frame_a",
                "original_frame_b",
                "seconds_from_start",
                "median_dx_px_per_source_frame",
                "median_vx_m_per_s",
                "texture_coverage",
            ],
            series,
        )
        csv_write(
            out / "profile.csv",
            [
                "image_row",
                "median_dx_px_per_source_frame",
                "top10_mean_dx_px_per_source_frame",
                "texture_coverage",
            ],
            profile,
        )
        image_write(out / "frame.png", first)
        base, vector_style = render_vectors(first, field, valid, roi, VECTOR_STYLE)
        image_write(out / "overlay.png", base)
        plt.rcParams.update(
            {
                "font.family": "DejaVu Sans",
                "font.size": 10,
                "axes.spines.top": False,
                "axes.spines.right": False,
            }
        )
        fig, ax = plt.subplots(figsize=(8.2, 3.8), layout="constrained")
        vmax = max(0.2, float(np.percentile(np.abs(values), 98)))
        image = ax.imshow(
            np.ma.array(ux, mask=~valid),
            cmap="RdBu_r",
            vmin=-vmax,
            vmax=vmax,
            extent=[x, x + w, y + h, y],
        )
        ax.set(
            xlabel="Image column (px)",
            ylabel="Image row (px)",
            title="Horizontal image motion · temporal average",
        )
        fig.colorbar(image, ax=ax, label="px / source frame")
        fig.savefig(out / "heatmap.png", dpi=130)
        plt.close(fig)
        fig, ax = plt.subplots(figsize=(8.2, 3.8), layout="constrained")
        rows = np.array([p[0] for p in profile])
        med = np.array([np.nan if p[1] is None else p[1] for p in profile])
        top = np.array([np.nan if p[2] is None else p[2] for p in profile])
        ax.plot(med, rows, color="#166f83", label="Median of textured pixels")
        ax.plot(top, rows, color="#bb7c20", alpha=0.85, label="Top 10% signed horizontal motion")
        ax.invert_yaxis()
        ax.set(
            xlabel="Horizontal motion (px / source frame)",
            ylabel="Image row (px)",
            title="Motion profile across the analysis region",
        )
        ax.grid(alpha=0.15)
        ax.legend(fontsize=8)
        fig.savefig(out / "profile.png", dpi=130)
        plt.close(fig)
        if cancelled(out):
            return
        emit("progress", progress=90, message="Building per-pair profiles and timeline…")
        timeline = export_timeline(
            out, pair_info, pair_profiles, profile, roi, fps, scale, physical, req
        )
        coverage = valid_total / (w * h * pairs)
        warnings = [
            "Optical flow estimates image-feature motion; physical fluid velocity requires independent validation.",
            "Texture coverage measures usable image gradients, not tracking accuracy or confidence.",
            "Top 10% uses the largest signed horizontal values; it is not a mean speed magnitude.",
        ]
        if not physical:
            warnings.append(
                "Physical velocity disabled: acquisition FPS and spatial calibration are not confirmed."
            )
        if physical and req.get("calibration_is_approximate", False):
            warnings.append(
                "Approximate spatial calibration from user-supplied pipe ID 50 mm across about 600 pixels; physical velocity has corresponding scale uncertainty."
            )
        if coverage < 0.25:
            warnings.append("Low texture coverage: interpret this result cautiously.")
        result = dict(
            version=VERSION,
            algorithm="Farneback dense optical flow",
            parameters=dict(PARAMS, winsize=winsize),
            preprocessing="green channel; texture gradient threshold 12; no image resizing",
            source=source.meta(),
            request=req,
            roi=roi,
            frame_indexing="zero-based; last frame inclusive",
            median_dx_px_per_source_frame=median,
            velocity_m_per_s=median * fps * scale / 1000 if physical else None,
            texture_coverage=coverage,
            elapsed_seconds=round(time.perf_counter() - t0, 3),
            pairs=pairs,
            vector_display=vector_style,
            timeline=timeline,
            warnings=warnings,
            python=sys.version,
            opencv=cv2.__version__,
            numpy=np.__version__,
            files=[
                "motion.csv",
                "profile.csv",
                "frame.png",
                "overlay.png",
                "heatmap.png",
                "profile.png",
                "request.json",
                "result.json",
                "profile_evolution.csv",
                "timeline.json",
                "profile_timeline.png",
                "velocity_vs_time.png",
            ]
            + [
                p[key]
                for p in pair_info
                for key in ("frame_preview", "frame_b_preview", "vector_preview")
            ],
        )
        if cancelled(out):
            return
        save_json(out / "result.json", result)
        emit("result", path=str(out / "result.json"), result=result)


def probe(req, out):
    with Source(req["source"]) as source:
        frame = max(0, min(int(req.get("frame", 0)), source.count - 1))
        image_write(out / "preview.png", source.read(frame))
        info = dict(source.meta(), preview=str(out / "preview.png"), preview_frame=frame)
        save_json(out / "metadata.json", info)
        emit("metadata", metadata=info)


def make_demo(path):
    rng = np.random.default_rng(731)
    tex = rng.integers(30, 225, (192, 320), dtype=np.uint8)
    tex = cv2.GaussianBlur(tex, (3, 3), 0)
    frames = np.stack(
        [
            cv2.warpAffine(
                tex, np.float32([[1, 0, 2 * i], [0, 1, 0]]), (320, 192), borderMode=cv2.BORDER_WRAP
            )
            for i in range(61)
        ]
    )
    np.savez_compressed(
        path,
        frames=frames,
        fps=100.0,
        provenance=json.dumps(
            dict(kind="synthetic validation", expected_dx_px_per_frame=2, seed=731)
        ),
    )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "command",
        choices=["probe", "analyze", "classify", "clip", "make-demo", "extract", "interface-track"],
    )
    ap.add_argument("request")
    args = ap.parse_args()
    if args.command == "make-demo":
        make_demo(args.request)
        return
    req = json.loads(Path(args.request).read_text(encoding="utf-8-sig"))
    out = Path(req["output"]).resolve()
    out.mkdir(parents=True, exist_ok=True)
    save_json(out / "request.json", req)
    if args.command == "probe":
        probe(req, out)
    elif args.command == "analyze":
        analyze(req, out)
    elif args.command == "clip":
        prepare_clip(req, out)
    elif args.command == "classify":
        classify_range(req, out, Source, emit)
    elif args.command == "interface-track":
        interfaces.track(req, out, Source, emit)
    else:
        with Source(req["source"]) as source:
            start = int(req.get("start", 15000))
            count = int(req.get("count", 41))
            if not 2 <= count <= 201 or start < 0 or start + count > source.count:
                raise ValueError("Invalid excerpt range.")
            frames = np.stack([source.read(start + i) for i in range(count)])
            meta = source.meta()
            meta.update(
                original_start_frame=start,
                kind="lossless decoded excerpt",
                timing="one excerpt frame per source frame",
            )
            dest = out / req.get("name", "research-excerpt.npz")
            np.savez_compressed(dest, frames=frames, fps=source.fps, provenance=json.dumps(meta))
            emit("extracted", path=str(dest))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        traceback.print_exc(file=sys.stderr)
        emit("error", message=str(exc))
        sys.exit(1)
