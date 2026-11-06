# Builds S.C.A.F.F.O.L.D. into a fast-startup onedir bundle using PyInstaller.
# Output: dist\scaffold\scaffold.exe  (launch this; the folder beside it holds the runtime).

$python = ".\.venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    Write-Error "Virtual environment not found. Run .\setup.ps1 first."
    exit 1
}

& $python -m PyInstaller app.spec --distpath dist --workpath build --noconfirm --clean
if ($LASTEXITCODE -ne 0) {
    Write-Error "PyInstaller build failed."
    exit $LASTEXITCODE
}

Write-Host "Build complete. Run dist\scaffold\scaffold.exe"
