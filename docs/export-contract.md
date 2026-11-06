# Viewer input contract

The viewer reads the current FlowLens research export format, not a network API. Select files directly from an exported motion/interface result folder. It requires timeline.json and optionally accepts interface.json and local JPEG/PNG previews. The source selector supports files from the same combined selection; no ZIP parser is included.

## timeline.json

- `rows`: increasing original image-row coordinates.
- `pairs`: one object per frame pair, including `frame_a`, `frame_b`, `original_frame_a`, `original_frame_b`, nullable `midpoint_seconds_from_start`, nullable motion/velocity, texture coverage, and three local preview filenames.
- `profiles`: matching median, top10 and coverage arrays for every row and pair. A missing measurement is JSON null.
- `units`, `physical_units`, `calibration_approximate`: explicit unit/calibration metadata.
- `x_min`, `x_max`: fixed plot limits across all pairs.

The viewer accepts up to 200 pairs and 10000 rows, and JSON files up to 20 MiB. It rejects mismatched lengths, nonfinite numbers, contradictory units and external/traversal image paths. Imported data is displayed using DOM text nodes and numeric SVG coordinates.

## interface.json

`frames` contains original frame IDs, relative sample times, x/y curve arrays, nullable median rows and accepted-column coverage. `runtime` may include backend, device, device_name and fallback_reason. Model metadata describes the originating inference run.

Interface samples are matched to frame A by original frame ID without temporal interpolation. The legacy timeline format does not carry a source fingerprint. Therefore frame-ID matching alone cannot verify that separately selected files came from the same recording. The UI states this limitation; select files from the same exported session. Interface position is shown as its own time trace and is not silently overlaid onto a potentially unrelated recording.

Relative displacement is image displacement from the first accepted boundary, not water-layer height or phase fraction. Model scores, texture coverage and accepted boundary coverage must not be interpreted as calibrated accuracy.
