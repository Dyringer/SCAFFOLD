# Creates .venv and installs dependencies
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install --upgrade pip
if (Test-Path requirements.txt) { pip install -r requirements.txt }
pip install -r requirements-dev.txt
Write-Host "Setup complete. Run '.\.venv\Scripts\Activate.ps1' to activate the venv."
