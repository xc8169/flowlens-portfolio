param([string]$DotnetPath='dotnet', [switch]$PackageWorker)
$ErrorActionPreference='Stop'
$taskRoot=$PSScriptRoot
& $DotnetPath publish (Join-Path $taskRoot 'desktop\FlowLens.csproj') -c Release -r win-x64 --self-contained true -o (Join-Path $taskRoot 'app') -p:PublishSingleFile=true -p:IncludeNativeLibrariesForSelfExtract=true
if ($LASTEXITCODE -ne 0) { throw 'Desktop publish failed.' }
if ($PackageWorker) {
    $taskPython=Join-Path $taskRoot '.venv\Scripts\python.exe'
    & $taskPython -m PyInstaller --noconfirm --onedir --console --exclude-module sklearn --exclude-module scipy --exclude-module joblib --name FlowLensWorker --distpath (Join-Path $taskRoot '.build\dist') --workpath (Join-Path $taskRoot '.build\worker') --specpath (Join-Path $taskRoot '.build') (Join-Path $taskRoot 'engine\worker.py')
    if ($LASTEXITCODE -ne 0) { throw 'Install PyInstaller and the chosen torch runtime before packaging the worker.' }
    New-Item -ItemType Directory -Force -Path (Join-Path $taskRoot 'engine-bin') | Out-Null
    Copy-Item -Path (Join-Path $taskRoot '.build\dist\FlowLensWorker\*') -Destination (Join-Path $taskRoot 'engine-bin') -Recurse -Force
}
Write-Host 'Desktop build complete. Model assets are managed separately; see docs/models.md.'
