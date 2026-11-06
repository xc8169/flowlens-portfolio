"""Display-only arrows for an explicitly supplied pair or averaged field."""

import cv2
import numpy as np


def overlay(frame, field, valid, roi, style):
    x, y, w, h = roi
    base = cv2.cvtColor(frame, cv2.COLOR_GRAY2BGR) if frame.ndim == 2 else frame.copy()
    cv2.rectangle(base, (x, y), (x + w - 1, y + h - 1), (130, 225, 60), 2)
    step = max(40, min(w, h) // 10)
    cap = min(style["max_length_px"], step * 0.8)
    for yy in range(step // 2, h, step):
        for xx in range(step // 2, w, step):
            if not valid[yy, xx]:
                continue
            vector = field[yy, xx]
            if float(np.linalg.norm(vector)) < style["minimum_motion_px_per_frame"]:
                continue
            arrow = vector * style["scale"]
            length = float(np.linalg.norm(arrow))
            if length > cap:
                arrow *= cap / length
            a = (x + xx, y + yy)
            b = (round(a[0] + float(arrow[0])), round(a[1] + float(arrow[1])))
            cv2.arrowedLine(
                base,
                a,
                b,
                (35, 220, 255),
                style["shaft_thickness_px"],
                cv2.LINE_AA,
                tipLength=style["tip_fraction"],
            )
    return base, dict(style, grid_spacing_px=step, effective_max_length_px=cap)
