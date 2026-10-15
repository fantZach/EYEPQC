[CmdletBinding()]
param(
    [ValidateSet('Status', 'Run')]
    [string]$Mode = 'Status',
    [string]$BindAddress = '127.0.0.1',
    [ValidateRange(1, 65535)]
    [int]$Port = 8765,
    [string]$TokenFile = 'tmp/mobile_pairing/relay.token',
    [string]$AccountsFile,
    [string]$PairingFile,
    [string]$TlsCert,
    [string]$TlsKey,
    [string]$SerialPort
)

$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
$connections = @(Get-NetTCPConnection | Where-Object { $_.LocalPort -in $Port, 8766 })
if ($Mode -eq 'Status') {
    if ($connections.Count -eq 0) {
        Write-Host 'No relay/download TCP endpoints found.'
    } else {
        $connections | Select-Object State, LocalAddress, LocalPort, RemoteAddress, RemotePort, OwningProcess |
            Format-Table -AutoSize
        $connections.OwningProcess | Sort-Object -Unique | ForEach-Object {
            Get-Process -Id $_ -ErrorAction SilentlyContinue |
                Select-Object Id, ProcessName, Path
        } | Format-Table -AutoSize
    }
    Write-Host 'TCP peers alone do not prove an authenticated phone/video session. Check relay session logs.'
    return
}

$listeners = @($connections | Where-Object { $_.LocalPort -eq $Port -and $_.State -eq 'Listen' })
if ($listeners.Count -gt 0) {
    throw "Port $Port already has a listener (PID $($listeners.OwningProcess -join ',')). Inspect Status; keep the existing service."
}

Push-Location $repoRoot
try {
    $python = Join-Path $repoRoot '.venv/Scripts/python.exe'
    if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
        throw 'Create the repository .venv and install requirements.txt and pc/requirements.txt first.'
    }
    $relayArgs = @('-u', (Join-Path $repoRoot 'pc/src/host/relay.py'), '--host', $BindAddress, '--port', $Port)
    if ($AccountsFile) {
        if (-not $TlsCert -or -not $TlsKey -or $PSBoundParameters.ContainsKey('TokenFile')) {
            throw 'AccountsFile requires TlsCert/TlsKey and excludes TokenFile.'
        }
        $relayArgs += @('--accounts-file', (Resolve-Path -LiteralPath $AccountsFile).Path)
    } else {
        if ($PairingFile) { throw 'PairingFile requires AccountsFile and TLS.' }
        $relayArgs += @('--token-file', (Resolve-Path -LiteralPath $TokenFile).Path)
    }
    if ($PairingFile) { $relayArgs += @('--pairing-file', (Resolve-Path -LiteralPath $PairingFile).Path) }
    if ($TlsCert -or $TlsKey) {
        if (-not $TlsCert -or -not $TlsKey) { throw 'Supply both TlsCert and TlsKey.' }
        $relayArgs += @('--tls-cert', (Resolve-Path -LiteralPath $TlsCert).Path, '--tls-key', (Resolve-Path -LiteralPath $TlsKey).Path)
    }
    if ($SerialPort) { $relayArgs += @('--serial-port', $SerialPort) }
    Write-Host 'Foreground relay: stop the phone first, then press Ctrl+C here. Credentials are unchanged.'
    & $python @relayArgs
    if ($LASTEXITCODE -ne 0) { throw "Relay exited with code $LASTEXITCODE." }
} finally {
    Pop-Location
}
