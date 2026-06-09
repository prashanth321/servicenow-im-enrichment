if (-not (Test-Path ".venv/Scripts/python.exe")) {
  Write-Error "Missing .venv. Run ./setup_venv.ps1 first."
  exit 1
}

& ".venv/Scripts/python.exe" app.py
