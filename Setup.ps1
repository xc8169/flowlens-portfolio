param([string]$PythonPath='python', [switch]$WithTorch, [switch]$Cuda)
$ErrorActionPreference='Stop'
$taskRoot=$PSScriptRoot
$env:PYTHONUTF8='1'
$taskPython=Join-Path $taskRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $taskPython)) {
    & $PythonPath -m venv (Join-Path $taskRoot '.venv')
    if ($LASTEXITCODE -ne 0) { throw 'Python 3.12 x64 is required.' }
}
& $taskPython -m pip install -r (Join-Path $taskRoot 'requirements-lock-windows.txt')
if ($LASTEXITCODE -ne 0) { throw 'Core dependency installation failed.' }
if ($WithTorch -or $Cuda) {
    $taskRequirements=if ($Cuda) { 'requirements-torch-cuda.txt' } else { 'requirements-torch-cpu.txt' }
    & $taskPython -m pip install -r (Join-Path $taskRoot $taskRequirements)
    if ($LASTEXITCODE -ne 0) { throw 'PyTorch installation failed.' }
}
& $taskPython (Join-Path $taskRoot 'scripts\demo.py')
if ($LASTEXITCODE -ne 0) { throw 'Synthetic validation failed.' }
Write-Host 'Ready. Run .venv\Scripts\python.exe -m http.server 8000 --bind 127.0.0.1 --directory web'
Write-Host 'Windows desktop: dotnet run --project desktop\FlowLens.csproj'
