param(
    [Parameter(Mandatory=$true)][System.Net.IPAddress]$ServerIP,
    [Parameter(Mandatory=$true)][System.Net.IPAddress]$DeviceIP,
    [Parameter(Mandatory=$true)][System.Net.IPAddress]$Gateway,
    [System.Net.IPAddress]$Subnet = '255.255.255.0',
    [ValidateRange(1,65535)][int]$Port = 8001
)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$dataDirectory = if ($env:LIGHTING_DATA_DIR) { $env:LIGHTING_DATA_DIR } else { Join-Path $projectRoot 'backend\data' }
$deviceSecret = if ($env:LIGHTING_DEVICE_KEY) { $env:LIGHTING_DEVICE_KEY } else { (Get-Content -LiteralPath (Join-Path $dataDirectory 'device-secret.txt') -Raw).Trim() }
if ($deviceSecret -notmatch '^[a-zA-Z0-9_-]{32,128}$') { throw 'Konfigūracijos generatoriui naudokite 32–128 raidžių, skaitmenų, _ arba - raktą.' }
foreach ($address in @($ServerIP,$DeviceIP,$Gateway,$Subnet)) {
    if ($address.AddressFamily -ne [System.Net.Sockets.AddressFamily]::InterNetwork) { throw 'Naudokite IPv4 adresus.' }
}
if ($ServerIP.Equals($DeviceIP) -or $DeviceIP.Equals($Gateway)) { throw 'Arduino turi turėti atskirą IP adresą.' }
$templatePath = Join-Path $projectRoot 'arduino\LightingController\config.example.h'
$configText = Get-Content -LiteralPath $templatePath -Raw
foreach ($entry in @(@('SERVER_IP',$ServerIP),@('DEVICE_IP',$DeviceIP),@('GATEWAY_IP',$Gateway),@('SUBNET_MASK',$Subnet))) {
    $octets = $entry[1].GetAddressBytes() -join ', '
    $configText = [regex]::Replace($configText, "const byte $($entry[0])\[\] = \{[^}]+\};", "const byte $($entry[0])[] = {$octets};")
}
$configText = $configText.Replace('const uint16_t SERVER_PORT = 8001;', "const uint16_t SERVER_PORT = $Port;")
$configText = $configText.Replace('PASTE_THE_GENERATED_DEVICE_KEY_HERE', $deviceSecret)
$outputPath = Join-Path $projectRoot 'arduino\LightingController\config.h'
[System.IO.File]::WriteAllText($outputPath, $configText, [System.Text.UTF8Encoding]::new($false))
Write-Host 'Sukurtas privatus arduino/LightingController/config.h. Prieš įkėlimą patikrinkite IP ir relės aktyvų lygį.'
