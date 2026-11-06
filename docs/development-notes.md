# Development notes

## From notebook to desktop

The original workflow required editing Python notebook cells and selecting video files. FlowLens introduced recording selection by experimental Vm/WC, explicit frame bounds, original-coordinate ROIs, calibrated image-motion profiles, synchronized visual review and traceable exports. Numerical fields are tied to recorded acquisition timing and scale rather than display playback speed.

## Workflow correction

Switching analyses previously caused unnecessary recomputation. Classification, interface and motion now own independent cached results. Shared settings invalidate all stages; ROI/calibration changes invalidate interface and motion; optical-flow window changes invalidate only motion. Continue callbacks await calculations rather than only opening tabs. Workflow tests verify failure/cancellation stops and duplicate-click handling.

## GPU interface extension

The initial boundary detector used local image features and a random forest. The subsequent small U-Net learned from the saved manual polylines. Its CUDA path was tested on RTX 4090 and its inference fallback preserves the same weights on CPU. Whole-video holdout was used to reduce the leakage risk from adjacent video frames. Evaluation limitations remain visible in model cards and UI text.

## Source portfolio extension

This repository adds a zero-dependency JavaScript viewer and generated sample exports. No trained research model is represented as a bundled asset. Synthetic desktop motion is a distinct path, so a reviewer can exercise the real worker without a misleading AI class. Optional model installation is explicit and ignored by Git.

These notes describe the actual development sequence, not reconstructed Git commits. A new local repository begins at the current source snapshot. Subsequent changes can be committed normally with their actual dates and authors.

## Next engineering improvements

- Simplify remaining compact C# prototype modules after adding behavioral regression checks; Python source is Black-formatted.
- Define a versioned, typed export schema including a source fingerprint shared by every stage.
- Add cancellation tokens and richer process-protocol diagnostics to the C# client.
- Add controlled UI automation to CI; current C# CI checks build and workflow logic, not the complete live desktop.
- Expand dataset coverage, absence labels and video-level cross-validation.
- Measure clean-machine packaging, transitive runtime locks and complete processing latency.
