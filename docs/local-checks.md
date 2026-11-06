# Local preparation checks

Checked on Windows x64 on 7 November 2026 (Japan time).

| Check | Result |
|---|---|
| Fresh Python 3.12 virtual environment | Core dependencies installed from requirements.txt |
| Generated motion example in fresh environment | 1.9998227 px/source frame; 0.01999823 m/s, against expected 2.0 px/frame and 0.020 m/s |
| Core environment unit suite | 20 passed; 6 optional PyTorch tests skipped because torch was not installed |
| PyTorch-capable development environment | All 26 Python tests passed, including actual RTX 4090 / CPU probability agreement |
| Python formatting | Black 26.10.1 check passed |
| JavaScript | All 8 tests passed; application-controller integration runs against a small DOM adapter |
| C# desktop | .NET 10 Release build passed with zero warnings and errors |
| C# workflow and catalog | Cache/export/Continue/failure/skip checks and all 16 Vm/WC combinations passed |
| Generated README figure | Rendered from actual synthetic exports and visually inspected |
| Local web assets | Served successfully over local HTTP |

The browser-control surfaces could not provide a successful live browser rendering in this session. Browser behavior is checked through the JavaScript controller/DOM-adapter tests, not a full browser end-to-end test. The source-only WPF changes were compiled; this session did not complete a live desktop UI check of that edition. The separate installed research application had been exercised during its earlier releases.

GitHub Actions jobs are configured but have not run remotely before publication. The historical research-model accuracy in validation.md is separate from these public code checks. No research recordings, annotation crops, fitted weights, installed runtimes or compiled executables are tracked in this source repository.
