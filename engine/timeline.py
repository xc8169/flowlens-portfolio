"""Per-pair profiles and exports. Missing texture stays missing, never zero-filled."""

import csv
import json
from pathlib import Path
import numpy as np
import cv2
from matplotlib import pyplot as plt


def row_statistics(horizontal, valid):
    height = horizontal.shape[0]
    med = np.full(height, np.nan)
    top = np.full(height, np.nan)
    coverage = np.mean(valid, axis=1)
    for row in range(height):
        values = horizontal[row, valid[row]]
        if len(values):
            med[row] = np.median(values)
            top[row] = np.mean(np.sort(values)[-max(1, int(len(values) * 0.1)) :])
    return med, top, coverage


def preview_frame(path, frame):
    ratio = min(1, 960 / frame.shape[1])
    if ratio < 1:
        frame = cv2.resize(
            frame,
            (round(frame.shape[1] * ratio), round(frame.shape[0] * ratio)),
            interpolation=cv2.INTER_AREA,
        )
    ok, data = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 90])
    if not ok:
        raise ValueError("Could not encode the pair preview.")
    data.tofile(str(path))


def clean(values):
    a = np.asarray(values)
    return np.where(np.isfinite(a), a, None).tolist()


def export_timeline(out, pair_info, profiles, average, roi, fps, scale, physical, request):
    rows = np.arange(roi[1], roi[1] + roi[3])
    factor = fps * scale / 1000 if physical else 1.0
    units = "m/s" if physical else "px / source frame"
    med = np.stack([p[0] for p in profiles])
    top = np.stack([p[1] for p in profiles])
    coverage = np.stack([p[2] for p in profiles])
    displayed = med * factor
    displayed_top = top * factor
    finite = np.concatenate(
        [displayed[np.isfinite(displayed)], displayed_top[np.isfinite(displayed_top)]]
    )
    lo = min(0, float(finite.min())) if len(finite) else -1.0
    hi = max(0, float(finite.max())) if len(finite) else 1.0
    pad = max((hi - lo) * 0.05, 0.001 if physical else 0.1)
    manifest = dict(
        units=units,
        physical_units=physical,
        calibration_approximate=(
            bool(request.get("calibration_is_approximate", False)) if physical else False
        ),
        fps=fps,
        pair_step=int(request.get("pair_step", request.get("gap", 1))),
        frame_gap=int(request.get("gap", 1)),
        rows=rows.tolist(),
        x_min=lo - pad,
        x_max=hi + pad,
        pairs=pair_info,
        profiles=[
            dict(median=clean(p[0] * factor), top10=clean(p[1] * factor), coverage=clean(p[2]))
            for p in profiles
        ],
        average=dict(
            median=clean(np.array([np.nan if p[1] is None else p[1] for p in average]) * factor),
            top10=clean(np.array([np.nan if p[2] is None else p[2] for p in average]) * factor),
        ),
        note="Eulerian horizontal image-motion profiles at fixed image rows. Each profile comes from one frame pair; no temporal averaging between pairs. The reference curve is the median of the temporally averaged field, not the average of per-pair medians. Times are pair midpoints relative to selected start. Missing texture is null. Display limits are fixed across pairs.",
    )
    (out / "timeline.json").write_text(json.dumps(manifest, allow_nan=False), encoding="utf-8")
    with (out / "profile_evolution.csv").open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(
            [
                "pair_index",
                "frame_a",
                "frame_b",
                "original_frame_a",
                "original_frame_b",
                "midpoint_seconds_from_start",
                "image_row",
                "median_dx_px_per_source_frame",
                "top10_mean_dx_px_per_source_frame",
                "median_vx_m_per_s",
                "top10_mean_vx_m_per_s",
                "texture_coverage",
            ]
        )
        for i, pair in enumerate(pair_info):
            for j, row in enumerate(rows):
                m = float(med[i, j]) if np.isfinite(med[i, j]) else None
                t = float(top[i, j]) if np.isfinite(top[i, j]) else None
                w.writerow(
                    [
                        i + 1,
                        pair["frame_a"],
                        pair["frame_b"],
                        pair["original_frame_a"],
                        pair["original_frame_b"],
                        pair["midpoint_seconds_from_start"],
                        int(row),
                        m,
                        t,
                        m * factor if physical and m is not None else None,
                        t * factor if physical and t is not None else None,
                        float(coverage[i, j]),
                    ]
                )
    # Each heatmap column is one sampled pair, without interpolation across rows or time.
    times = np.array(
        [p["midpoint_seconds_from_start"] if fps > 0 else i + 1 for i, p in enumerate(pair_info)]
    )
    spacing = manifest["pair_step"] / fps if fps > 0 else 1.0
    extent = [times[0] - spacing / 2, times[-1] + spacing / 2, rows[-1] + 0.5, rows[0] - 0.5]
    vmax = max(float(np.max(np.abs(finite))) if len(finite) else 1.0, 0.001 if physical else 0.1)
    cmap = plt.get_cmap("RdBu_r").copy()
    cmap.set_bad("#dfe5e6")
    fig, ax = plt.subplots(figsize=(9, 4.6), layout="constrained")
    im = ax.imshow(
        np.ma.masked_invalid(displayed.T),
        aspect="auto",
        origin="upper",
        extent=extent,
        cmap=cmap,
        vmin=-vmax,
        vmax=vmax,
        interpolation="nearest",
    )
    ax.set(
        xlabel="Pair midpoint time from selection start (s)" if fps > 0 else "Pair index",
        ylabel="Image row (px)",
        title=(
            "Horizontal velocity profile over time"
            if physical
            else "Horizontal motion profile over time"
        ),
    )
    fig.colorbar(
        im, ax=ax, label=("Approximate " if manifest["calibration_approximate"] else "") + units
    )
    fig.savefig(out / "profile_timeline.png", dpi=135)
    plt.close(fig)
    fig, ax = plt.subplots(figsize=(9, 4.6), layout="constrained")
    values = [
        (
            np.nan
            if p["median_dx_px_per_source_frame"] is None
            else p["median_dx_px_per_source_frame"] * factor
        )
        for p in pair_info
    ]
    ax.plot(times, values, color="#176d76", marker=".", linewidth=1.2)
    ax.set(
        xlabel="Pair midpoint time from selection start (s)" if fps > 0 else "Pair index",
        ylabel=units,
        title=(
            "Median horizontal image velocity vs time"
            if physical
            else "Median horizontal image motion vs time"
        ),
    )
    ax.grid(alpha=0.18)
    fig.savefig(out / "velocity_vs_time.png", dpi=135)
    plt.close(fig)
    return dict(
        data="timeline.json",
        heatmap="profile_timeline.png",
        trace="velocity_vs_time.png",
        pairs=len(pair_info),
        units=units,
    )
