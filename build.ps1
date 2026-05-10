# Builds main.py into a standalone exe using PyInstaller
param(
    [string]$Name = "app",
    [switch]$OneFile = $true,
    [switch]$NoConsole
)

$activateScript = ".\.venv\Scripts\Activate.ps1"
if (-not (Test-Path $activateScript)) {
    Write-Error "Virtual environment not found. Run .\setup.ps1 first."
    exit 1
}

. $activateScript

$args_list = @("main.py", "--name", $Name, "--distpath", "dist", "--workpath", "build", "--clean")

if ($OneFile) { $args_list += "--onefile" }
if ($NoConsole) { $args_list += "--noconsole" }

pyinstaller @args_list

Write-Host "Build complete. Executable is at dist\$Name.exe"
