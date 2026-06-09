$python = "C:/Users/SaiPrashanthKorthiwa/AppData/Local/Programs/Python/Python312/python.exe"

if (-not (Test-Path ".venv/Scripts/python.exe")) {
  & $python -m venv .venv
}

& ".venv/Scripts/python.exe" -m pip install --upgrade pip
& ".venv/Scripts/python.exe" -m pip install -r requirements.txt
Write-Host "Virtual environment is ready."
