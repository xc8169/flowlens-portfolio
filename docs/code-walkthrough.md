# A short code review route

## 1. Reproducible scientific processing — Python

Start with scripts/demo.py. It generates known input, calls the actual analysis engine, verifies measured displacement, and publishes only portable synthetic results. Then inspect worker.py: Source.read validates frame bounds and seeks explicitly; validate checks the last requested frame, ROI and calibration; analyze divides displacement by frame gap before exporting source-frame motion.

Explain the difference between pair gap (A to B) and pair spacing (one A to the next A). For example, a two-frame gap produces approximately four pixels displacement in the generated sample, which is normalized to two pixels per source frame. Velocity is source-frame displacement × acquisition FPS × mm/pixel ÷ 1000.

## 2. Model runtime reliability — Python

In torch_interface.py, follow select_device, TorchInterfaceModel.probability and _fallback. Explain why device discovery is followed by a real kernel probe, why the model is initially loaded on CPU, and why a CUDA failure reloads weights into a fresh CPU model. Tests use temporary untrained weights to exercise these contracts independently of research accuracy.

In train_torch_interface.py, inspect grouping by source video. The evaluation fit excludes complete video groups, then the final model is refit on all annotations. Splitting nearby frames randomly would allow very similar images from one recording on both sides of evaluation. This grouping reduces that leakage but a two-video holdout is still a limited experiment.

## 3. UI/process integration — C#

Read WorkerClient.cs and WorkflowNavigator.cs. Follow a Continue click into the awaited stage sequence. Show the failure and cancellation short-circuits and the duplicate-click guard. In AnalysisSessionState.cs, explain independent caches and why JsonElement.Clone is necessary. In PortfolioDemo.cs, show how a synthetic numerical check is kept distinct from an AI classification.

## 4. Interactive scientific review — JavaScript

Read web/model.js first: unit checks, bounded input sizes, plain local image filenames, nullable measurements, and exact frame-ID matching. In web/app.js, follow file loading, validation, selection changes and SVG rendering. A line is split around missing values; null is never turned into a zero velocity. A browser GPU is not substituted for the device recorded during inference.

## 5. A concrete bug story

Earlier navigation mixed classification and motion display state, so returning to an analysis required unnecessary recalculation. Independent caches and scoped invalidation fixed that workflow. A related Continue button originally opened a view without starting processing; the awaited navigator now starts the required stage and proceeds only on successful completion. The C# tests exercise the actual navigator.

Useful follow-up improvements include a versioned typed export schema, simplifying remaining prototype modules, more independent recordings, negative interface examples, and measured end-to-end performance on fresh systems. Python files are formatted with Black; some C# modules retain the compact research-prototype structure. The walkthrough points to bounded pieces that are easiest to review first.
