"""Small fully convolutional boundary network; identical weights on CUDA and CPU."""

from pathlib import Path
import hashlib
import json
import time
import cv2
import numpy as np
import torch
from torch import nn
from torch.nn import functional as F

ARCH = "flowlens-boundary-unet-v1"
HEIGHT, WIDTH = 192, 288


class Block(nn.Sequential):
    def __init__(self, a, b):
        super().__init__(
            nn.Conv2d(a, b, 3, padding=1),
            nn.GroupNorm(4, b),
            nn.SiLU(),
            nn.Conv2d(b, b, 3, padding=1),
            nn.GroupNorm(4, b),
            nn.SiLU(),
        )


class BoundaryNet(nn.Module):
    def __init__(self):
        super().__init__()
        self.a = Block(3, 12)
        self.b = Block(12, 24)
        self.c = Block(24, 48)
        self.d = Block(48, 96)
        self.u = Block(144, 48)
        self.v = Block(72, 24)
        self.w = Block(36, 12)
        self.head = nn.Conv2d(12, 1, 1)

    def forward(self, x):
        a = self.a(x)
        b = self.b(F.max_pool2d(a, 2))
        c = self.c(F.max_pool2d(b, 2))
        d = self.d(F.max_pool2d(c, 2))
        u = self.u(torch.cat([F.interpolate(d, size=c.shape[-2:], mode="nearest"), c], 1))
        v = self.v(torch.cat([F.interpolate(u, size=b.shape[-2:], mode="nearest"), b], 1))
        return self.head(
            self.w(torch.cat([F.interpolate(v, size=a.shape[-2:], mode="nearest"), a], 1))
        )[:, 0]


def preprocess(crop):
    im = cv2.resize(crop, (WIDTH, HEIGHT), interpolation=cv2.INTER_AREA).astype(np.float32) / 255.0
    g = im[..., 1]
    lo, hi = np.percentile(g, [2, 98])
    z = np.clip((g - lo) / max(float(hi - lo), 0.05), 0, 1)
    return np.stack([z, im[..., 0] - g, im[..., 2] - g], 0).astype(np.float32)


def select_device(preference="auto"):
    if preference not in ("auto", "cpu", "cuda"):
        raise ValueError("Device must be auto, cpu or cuda.")
    if preference == "cpu":
        return "cpu", None
    try:
        if torch.cuda.is_available():
            # Probe an actual kernel: driver discovery alone does not prove compatibility.
            torch.ones(1, device="cuda").add_(1)
            torch.cuda.synchronize()
            return "cuda", None
    except (RuntimeError, AssertionError, OSError) as ex:
        return "cpu", "CUDA initialization failed: " + str(ex)
    return "cpu", "CUDA unavailable; using the same PyTorch model on CPU."


class TorchInterfaceModel:
    def __init__(self, folder, device="auto"):
        self.folder = Path(folder)
        self.card = json.loads((self.folder / "model_card.json").read_text())
        if self.card["architecture"] != ARCH:
            raise ValueError("Unsupported boundary network architecture.")
        weights = self.folder / "weights.pt"
        if hashlib.sha256(weights.read_bytes()).hexdigest() != self.card["weights_sha256"]:
            raise ValueError("Interface model checksum failed.")
        torch.set_num_threads(min(4, torch.get_num_threads()))
        self.device, self.fallback_reason = select_device(device)
        self.net = BoundaryNet()
        self.net.load_state_dict(torch.load(weights, map_location="cpu", weights_only=True))
        self.net.eval()
        self.started = time.perf_counter()
        self.inference_ms = []
        try:
            self.net.to(self.device)
        except (RuntimeError, AssertionError, OSError) as ex:
            self._fallback(ex)

    def _fallback(self, ex):
        self.device = "cpu"
        self.fallback_reason = "CUDA execution failed; resumed on CPU: " + str(ex)
        # Reload CPU weights rather than copying from a potentially failed CUDA context.
        self.net = BoundaryNet()
        self.net.load_state_dict(
            torch.load(self.folder / "weights.pt", map_location="cpu", weights_only=True)
        )
        self.net.eval()

    @torch.inference_mode()
    def probability(self, crop):
        data = torch.from_numpy(preprocess(crop)[None])
        start = time.perf_counter()
        try:
            p = self.net(data.to(self.device)).softmax(dim=1).cpu().numpy()[0]
        except (RuntimeError, AssertionError, OSError) as ex:
            if self.device != "cuda":
                raise
            self._fallback(ex)
            p = self.net(data).softmax(dim=1).numpy()[0]
        self.inference_ms.append((time.perf_counter() - start) * 1000)
        return p

    def runtime(self):
        return dict(
            backend="PyTorch",
            device=self.device,
            device_name=torch.cuda.get_device_name(0) if self.device == "cuda" else "CPU",
            torch_version=str(torch.__version__),
            cuda_runtime=torch.version.cuda,
            fallback_reason=self.fallback_reason,
            mean_network_ms=float(np.mean(self.inference_ms)) if self.inference_ms else None,
        )


def decode(probability, crop, roi):
    from interfaces import trace_path

    h, w = probability.shape
    path = trace_path(probability)
    rows = np.arange(h)[:, None]
    # Probability mass near the curve is evidence concentration, not calibrated accuracy.
    scores = (probability * (np.abs(rows - path[None, :]) <= 4)).sum(0)
    good = scores >= 0.25
    accepted = (
        float(np.std(cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY))) >= 2
        and good.mean() >= 0.5
        and np.median(scores) >= 0.35
    )
    if not accepted:
        good[:] = False
    x, y, rw, rh = roi
    xs = x + np.arange(w) * (rw - 1) / (w - 1)
    ys = y + path * (rh - 1) / (h - 1)
    return dict(
        x=xs.tolist(),
        y=[float(v) if ok else None for v, ok in zip(ys, good)],
        scores=scores.tolist(),
        median_row_px=float(np.median(ys[good])) if good.any() else None,
        coverage=float(good.mean()),
        model_score=float(np.median(scores)),
        status="Review required" if accepted else "No reliable boundary detected",
        accepted=bool(accepted),
    )
