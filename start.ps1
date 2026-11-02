param([int]$Port = 8001)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$pythonPath = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonPath)) {
    Write-Error 'Pirmiausia sukurkite .venv ir įdiekite backend/requirements.txt pagal README.md.'
    exit 1
}
Write-Host "Atidarykite http://127.0.0.1:$Port"
Write-Host 'Pirmo prisijungimo duomenys: backend/data/initial-credentials.txt'
& $pythonPath -m uvicorn backend.main:app --host 0.0.0.0 --port $Port
