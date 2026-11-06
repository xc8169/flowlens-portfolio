"""Reproducible offline training from saved polylines. Never modifies source labels."""

from pathlib import Path
import argparse
import hashlib
import json
import os
import random
import time
import uuid

os.environ.setdefault("CUBLAS_WORKSPACE_CONFIG", ":4096:8")
import cv2
import numpy as np
import torch
from torch.nn import functional as F
from torch_interface import ARCH, HEIGHT, WIDTH, BoundaryNet, preprocess, select_device, decode


def write(path, value):
    Path(path).write_text(json.dumps(value, indent=2, allow_nan=False), encoding="utf-8")


def dataset(folder):
    records = []
    images = []
    targets = []
    masks = []
    for path in sorted(Path(folder).glob("*.json")):
        r = json.loads(path.read_text())
        r["label_file"] = path.name
        if not r["applicable"] or r["absent"]:
            continue
        image = Path(folder) / r["image"]
        if hashlib.sha256(image.read_bytes()).hexdigest() != r["image_sha256"]:
            raise ValueError("Label crop checksum failed: " + str(image))
        im = cv2.imdecode(np.fromfile(image, np.uint8), cv2.IMREAD_COLOR)
        p = np.array(r["points"])
        x, y, w, h = r["roi"]
        xs = x + np.arange(WIDTH) * (w - 1) / (WIDTH - 1)
        target = (np.interp(xs, p[:, 0], p[:, 1]) - y) * (HEIGHT - 1) / (h - 1)
        mask = (xs >= p[0, 0]) & (xs <= p[-1, 0])
        records.append(r)
        images.append(preprocess(im))
        targets.append(target)
        masks.append(mask)
    if len(records) < 3:
        raise ValueError("Need at least 3 positive annotated frames.")
    return (
        records,
        torch.tensor(np.array(images)),
        torch.tensor(np.array(targets), dtype=torch.float32),
        torch.tensor(np.array(masks)),
    )


def seed_all(seed):
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)
    torch.backends.cudnn.benchmark = False
    torch.backends.cudnn.deterministic = True
    torch.use_deterministic_algorithms(True)


def fit(images, targets, masks, ids, epochs, device, seed, log):
    seed_all(seed)
    net = BoundaryNet().to(device)
    optimizer = torch.optim.AdamW(net.parameters(), lr=0.001, weight_decay=0.0001)
    data = images.to(device)
    ys = targets.to(device)
    valid = masks.to(device)
    rows = torch.arange(HEIGHT, device=device)[None, :, None]
    start = time.perf_counter()
    for epoch in range(epochs):
        if (log.parent / "cancel.flag").exists():
            raise RuntimeError("Training cancelled; no active model replaced.")
        net.train()
        losses = []
        for batch in torch.tensor(ids)[torch.randperm(len(ids))].split(8):
            x = data[batch].clone()
            y = ys[batch].clone()
            mask = valid[batch].clone()
            # Move image and annotation together; reduces fixed-row memorization.
            shifts = torch.randint(-28, 29, (len(batch),)).tolist()
            for j, shift in enumerate(shifts):
                x[j] = torch.roll(x[j], shift, dims=1)
                if shift > 0:
                    x[j, :, :shift] = x[j, :, shift : shift + 1].clone()
                elif shift < 0:
                    x[j, :, shift:] = x[j, :, shift - 1 : shift].clone()
                y[j] += shift
                if random.random() < 0.5:
                    x[j] = x[j].flip(-1)
                    y[j] = y[j].flip(-1)
                    mask[j] = mask[j].flip(-1)
            mask &= (y >= 5) & (y < HEIGHT - 5)
            x[:, 0] = (x[:, 0] * (0.8 + 0.4 * random.random()) + random.uniform(-0.08, 0.08)).clamp(
                0, 1
            )
            x += torch.randn_like(x) * 0.01
            target = torch.exp(-0.5 * ((rows - y[:, None, :]) / 2.0) ** 2)
            target /= target.sum(1, keepdim=True).clamp_min(1e-8)
            logits = net(x)
            percol = -(target * F.log_softmax(logits, dim=1)).sum(1)
            loss = percol[mask].mean()
            optimizer.zero_grad()
            loss.backward()
            torch.nn.utils.clip_grad_norm_(net.parameters(), 5.0)
            optimizer.step()
            losses.append(loss.item())
        if epoch % 10 == 0 or epoch == epochs - 1:
            event = dict(
                epoch=epoch + 1,
                epochs=epochs,
                loss=float(np.mean(losses)),
                elapsed_s=time.perf_counter() - start,
                device=device,
            )
            with log.open("a") as f:
                f.write(json.dumps(event) + "\n")
            print(json.dumps(event), flush=True)
    return net.eval(), time.perf_counter() - start


@torch.inference_mode()
def evaluate(net, ids, records, folder, device):
    errors = []
    all_errors = []
    detected = 0
    total = 0
    frames = []
    for i in ids:
        r = records[i]
        im = cv2.imdecode(np.fromfile(Path(folder) / r["image"], np.uint8), 1)
        prob = (
            net(torch.from_numpy(preprocess(im)[None]).to(device)).softmax(dim=1).cpu().numpy()[0]
        )
        d = decode(prob, im, r["roi"])
        xs = np.array(d["x"])
        ys = np.array([np.nan if y is None else y for y in d["y"]])
        p = np.array(r["points"])
        mask = (xs >= p[0, 0]) & (xs <= p[-1, 0])
        total += int(mask.sum())
        good = mask & np.isfinite(ys)
        detected += int(good.sum())
        e = np.abs(ys[good] - np.interp(xs[good], p[:, 0], p[:, 1]))
        errors.extend(e.tolist())
        from interfaces import trace_path

        row = trace_path(prob) * (r["roi"][3] - 1) / (HEIGHT - 1) + r["roi"][1]
        all_errors.extend(np.abs(row[mask] - np.interp(xs[mask], p[:, 0], p[:, 1])).tolist())
        frames.append(
            dict(
                label=r["label_file"],
                group=r["group"],
                mae_px=float(e.mean()) if len(e) else None,
                coverage=float(good.sum() / mask.sum()),
            )
        )
    return dict(
        kind="Whole-video held-out evaluation; final model subsequently refit on all labels",
        held_out_groups=sorted({records[i]["group"] for i in ids}),
        held_out_frames=len(ids),
        mean_absolute_error_px=float(np.mean(errors)) if errors else None,
        detected_fraction=detected / total,
        unconditional_path_mae_px=float(np.mean(all_errors)),
        frames=frames,
        note="Fixed training schedule; these videos were excluded from fitting and epoch selection. Error is against manual polylines, conditional on accepted columns. Coverage is not accuracy.",
    )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--labels", required=True)
    ap.add_argument("--models", required=True)
    ap.add_argument("--report", required=True)
    ap.add_argument("--epochs", type=int, default=120)
    ap.add_argument("--seed", type=int, default=20261105)
    ap.add_argument("--device", choices=["auto", "cpu", "cuda"], default="auto")
    a = ap.parse_args()
    if not 1 <= a.epochs <= 1000:
        raise ValueError("Epochs must be 1–1000.")
    out = Path(a.report)
    out.mkdir(parents=True, exist_ok=True)
    torch.set_num_threads(4)
    records, images, targets, masks = dataset(a.labels)
    groups = sorted({r["group"] for r in records})
    if len(groups) < 2:
        raise ValueError("Need at least two source videos for independent video evaluation.")
    held = set(groups[-max(1, len(groups) // 4) :])
    train = [i for i, r in enumerate(records) if r["group"] not in held]
    test = [i for i, r in enumerate(records) if r["group"] in held]
    device, reason = select_device(a.device)
    print(
        json.dumps(
            dict(
                device=device,
                gpu=torch.cuda.get_device_name(0) if device == "cuda" else None,
                fallback_reason=reason,
                train=len(train),
                test=len(test),
            )
        ),
        flush=True,
    )
    net, seconds = fit(
        images, targets, masks, train, a.epochs, device, a.seed, out / "holdout-training.jsonl"
    )
    validation = evaluate(net, test, records, a.labels, device)
    write(out / "validation.json", validation)
    torch.save({k: v.cpu() for k, v in net.state_dict().items()}, out / "holdout-weights.pt")
    del net
    net, final_seconds = fit(
        images,
        targets,
        masks,
        list(range(len(records))),
        a.epochs,
        device,
        a.seed,
        out / "final-training.jsonl",
    )
    root = Path(a.models)
    revision = hashlib.sha256(json.dumps(records, sort_keys=True).encode()).hexdigest()
    version = "torch-interface-" + revision[:8] + "-" + uuid.uuid4().hex[:8]
    dest = root / version
    dest.mkdir(parents=True)
    torch.save({k: v.cpu() for k, v in net.state_dict().items()}, dest / "weights.pt")
    card = dict(
        model_version=version,
        architecture=ARCH,
        estimator="PyTorch BoundaryNet (small U-Net)",
        input_size=[HEIGHT, WIDTH],
        positive_frames=len(records),
        labelled_frames=len(records),
        videos=len(groups),
        patterns=sorted({r["pattern"] for r in records}),
        training_groups=groups,
        training_labels=[r["label_file"] for r in records],
        dataset_revision=revision,
        validation=validation,
        weights_sha256=hashlib.sha256((dest / "weights.pt").read_bytes()).hexdigest(),
        training=dict(
            epochs=a.epochs,
            seed=a.seed,
            device=device,
            device_name=torch.cuda.get_device_name(0) if device == "cuda" else "CPU",
            torch_version=str(torch.__version__),
            cuda_runtime=torch.version.cuda,
            deterministic_algorithms=True,
            holdout_seconds=seconds,
            final_seconds=final_seconds,
            optimizer="AdamW",
            learning_rate=0.001,
            batch_size=8,
            loss="Gaussian row-target cross entropy over annotated columns only",
        ),
        inputs="Image pixels only; no Vm, WC, filename, pattern, recording ID or prior-frame boundary.",
        limitations="Experimental single-valued boundary; all-positive small dataset, absence detection unvalidated. Uncalibrated concentration scores; review every prediction. GPU/CPU floating-point differences are possible.",
    )
    write(dest / "model_card.json", card)
    write(out / "training_report.json", card)
    # Atomic activation after all training/validation artifacts have been written.
    root.mkdir(parents=True, exist_ok=True)
    write(root / "current.tmp", dict(directory=version))
    os.replace(root / "current.tmp", root / "current.json")
    print(
        json.dumps(dict(model=version, validation=validation, training=card["training"])),
        flush=True,
    )


if __name__ == "__main__":
    main()
