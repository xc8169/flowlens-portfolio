# Optional research models and runtimes

The clean source example works without research assets. The repository contains image feature extraction, forest inference, the PyTorch network, boundary decoding and offline training code. It intentionally does not ship research recordings, original annotation crops, fitted forests or neural weights.

## Use existing models locally

After Python setup, from the repository root:

```sh
python scripts/import_local_models.py "PATH_TO_EXISTING_FLOWLENS_INSTALLATION"
```

This copies `model/` and `interface-models/` from the selected installation. Both directories are ignored by Git except their README files. Inspect `git status` before publishing any deliberately changed asset policy. Restart the desktop to load the model card. Set the `FLOWLENS_DATA_DIR` environment variable to your own recording folder, or use Open recording.

## Train a boundary model

Install core requirements and one of the PyTorch runtime files. Saved annotation JSON files must reference the original crop PNG, its SHA-256, a source-video group, original ROI, pattern and ordered manual polyline. The offline trainer checks crop hashes and supervises only annotated columns.

```sh
python engine/train_torch_interface.py --labels PATH_TO_LABELS --models interface-models --report training-reports/my-run --device auto --epochs 120 --seed 20261105
```

The trainer requires at least two video groups for evaluation, writes a separate holdout checkpoint/report, refits on all labels and activates a new model atomically after success. Current source uses a fixed group-sorted holdout; broader cross-validation is a future improvement. Place cancel.flag in the report folder to cancel at an epoch boundary. CPU training is supported with `--device cpu`; Auto selects CUDA when initialization succeeds. Runtime errors during training stop the run rather than automatically restarting a long training job. Inference has automatic CPU retry.

## Runtime setup

Core motion processing uses NumPy, OpenCV and Matplotlib. PyTorch is optional for the generated motion demo. The verified Windows core dependency set is in requirements-lock-windows.txt. Install `requirements-torch-cpu.txt` for a CPU runtime, or `requirements-torch-cuda.txt` for the official CUDA 12.8 build used on the original RTX 4090 system. A compatible NVIDIA driver is needed for CUDA. The prebuilt torch wheel supplies its runtime libraries; a separately installed CUDA Toolkit is not required for this model.

`Setup.ps1 -WithTorch` selects CPU torch; `Setup.ps1 -Cuda` selects CUDA torch. Windows core dependencies are locked; PyTorch's transitive dependencies and non-Windows environments are not fully locked. Repeatable clean-machine GPU packaging remains future work. Hardware/library changes may alter floating-point results even with deterministic training settings.

To build a PyInstaller worker, install PyInstaller 6.22.3 into the chosen environment and run `Build.ps1 -PackageWorker`. Install the intended PyTorch runtime before packaging if interface inference is required. Keep research model folders alongside the packaged app; weights are data assets, not embedded code. The research application's previously verified portable package is a separate artifact and is not committed here.
