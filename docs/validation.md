# Validation and limits

## Reproducible public example

The generated sample uses seed 731, +2 pixels/source frame and 100 fps. The example selects 12 pairs, two-frame A→B gap, three-frame pair spacing and a fixed ROI. At an illustrative 0.1 mm/px, expected velocity is 0.020 m/s. The committed web/demo/summary.json records observed values and software versions. Regenerate it with scripts/demo.py. This verifies indexing, sign, gap normalization, calibration arithmetic and exports; it does not validate real fluid velocity.

Python tests also cover reverse/stationary motion, frame bounds, cancellation, missing texture and changing per-pair profiles. Optional torch tests use untrained fixture weights and a one-epoch synthetic training smoke check. JavaScript tests verify the real demo export, missing-data gaps, calibration consistency, input bounds, filename safety and exact frame matching. C# checks exercise cache lifetime, scoped invalidation, result bundles and the awaited workflow controller.

## Historical research evaluation

These figures were recorded during development of the separate FlowLens research release on 5 November 2026. The private research dataset/model is not included, so these accuracy figures cannot be independently reproduced from the generated example alone.

| Measurement | Recorded value |
|---|---:|
| Manual boundary labels | 73 positive frames / 9 source videos |
| Boundary holdout | 17 annotated frames / 2 whole videos |
| Neural conditional row MAE | 19.4694 px |
| Accepted annotated columns | 96.2288% |
| Neural unconditional path MAE | 20.1094 px |
| Earlier forest conditional MAE | 25.4590 px at 99.4273% coverage |
| Warm neural processing | CPU 11.71 ms / RTX 4090 1.83 ms per frame |

The neural model reduced conditional error on this small holdout while accepting fewer columns. Detectors use different sampling grids; this is not an exhaustive benchmark. Human polylines are the reference, rather than independent physical ground truth. The held-out fit used a fixed schedule before the final model was trained on all annotations. Final-model predictions on those nine source videos are training-source predictions.

Warm timings were measured over 20 iterations of one research frame after warmup. They include preprocessing and device transfer but exclude process startup, video decoding, curve decoding, plotting and export. They do not imply a 6.4× speedup for a complete application run. The recorded environment was Python 3.12.10 / PyTorch 2.11.0+cu128 on RTX 4090.

The flow-pattern model's separate historical held-out-recording clip accuracy was 35.9%, on 12 eligible recordings from four evaluable classes. Four other classes had only one source recording each. All classifications and automatic interface-skip decisions require review.

## Remaining scientific limits

Interface labels contain visible boundaries only; absence detection for eligible flow patterns is unvalidated. D O/W&W has no annotated boundary examples. A single y(x) curve cannot represent all possible interfaces. The approximate pipe calibration adds spatial uncertainty. Dense optical flow follows image texture, which is not necessarily equal to phase velocity. Additional independent recordings, negative examples and a consistent interface definition are needed before broader deployment claims.
