$ErrorActionPreference = "Stop"
if (-not $IsWindows -and $env:OS -ne "Windows_NT") { throw "Build this executable on Windows." }
Set-Location $PSScriptRoot
python -m pip install -r requirements-capture-build.txt
if ($LASTEXITCODE -ne 0) { throw "Dependency installation failed" }
$captureManifest = Join-Path $PSScriptRoot "packaging/capture.manifest"
python -m PyInstaller --noconfirm --clean --onefile --windowed --collect-submodules mss --name RocoCapture --manifest $captureManifest --distpath dist/capture --workpath build/capture --specpath build windows_capture.py
if ($LASTEXITCODE -ne 0) { throw "PyInstaller build failed" }
Write-Host "Built: dist/capture/RocoCapture.exe"
