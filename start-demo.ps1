param([ValidateRange(1,65535)][int]$Port = 8001)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$serverUrl = "http://127.0.0.1:$Port"
$serverJob = $null
try {
    $health = $null
    try { $health = Invoke-RestMethod -Uri "$serverUrl/api/health" -TimeoutSec 2 } catch {}
    if ($health -and $health.service -ne 'sviesa-lighting') { throw "Portą $Port naudoja kita programa." }
    if (-not $health) {
        $serverJob = Start-Job -ArgumentList $PSScriptRoot,$Port -ScriptBlock {
            param($projectDirectory,$listenPort)
            Set-Location -LiteralPath $projectDirectory
            & (Join-Path $projectDirectory '.venv\Scripts\python.exe') -m uvicorn backend.main:app --host 0.0.0.0 --port $listenPort
        }
        for ($attempt = 0; $attempt -lt 50; $attempt++) {
            try { $health = Invoke-RestMethod -Uri "$serverUrl/api/health" -TimeoutSec 1; break } catch {}
            if ($serverJob.State -eq 'Failed' -or $serverJob.State -eq 'Completed') { break }
            Start-Sleep -Milliseconds 200
        }
        if (-not $health -or $health.service -ne 'sviesa-lighting') {
            Receive-Job -Job $serverJob -ErrorAction Continue
            throw 'Serveris nepasileido. Patikrinkite .venv, priklausomybes ir laisvą portą pagal README.'
        }
    }
    Write-Host "Sistema: $serverUrl"
    Write-Host 'Prisijungimo duomenys: backend/data/initial-credentials.txt'
    Write-Host 'Terminale rašykite card, motion on, motion off, disconnect, connect arba quit.'
    & '.\.venv\Scripts\python.exe' tools\device_simulator.py --url $serverUrl --demo
} finally {
    if ($null -ne $serverJob) {
        Stop-Job -Job $serverJob
        Remove-Job -Job $serverJob
    }
}
