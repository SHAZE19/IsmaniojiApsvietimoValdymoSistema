param([int]$Port = 8001)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
& '.\.venv\Scripts\python.exe' tools\device_simulator.py --url "http://127.0.0.1:$Port" --demo
