param([switch]$Plan)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$root = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$workspace = 'build/vitis/g6_secure_cleanup_20261011_candidate014_safe_hello_ack_retry'
$workspaceFull = [IO.Path]::GetFullPath((Join-Path $root $workspace))
$toolRoot = if ($env:EYEPQC_TOOL_ROOT) { $env:EYEPQC_TOOL_ROOT } else { 'E:/fpg/2026.1' }
$python = Join-Path $root '.venv/Scripts/python.exe'
$g6Script = Join-Path $root 'src/host/g6_board.py'
$batchScript = Join-Path $root 'run_g7_batch.ps1'
$collectorScript = Join-Path $PSScriptRoot 'collect_g7_usb_etw.ps1'
$outputRoot = Join-Path $root 'build/g7_usb_etw'

function Test-IsAdministrator {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = [Security.Principal.WindowsPrincipal]::new($identity)
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function ConvertTo-WindowsArgument([string]$Value) {
    if ($null -eq $Value) { return '""' }
    $builder = [System.Text.StringBuilder]::new()
    [void]$builder.Append('"')
    $slashes = 0
    foreach ($char in $Value.ToCharArray()) {
        if ($char -eq [char]92) { $slashes++; continue }
        if ($char -eq [char]34) {
            [void]$builder.Append(('\' * (2 * $slashes + 1)))
            [void]$builder.Append('"')
            $slashes = 0
            continue
        }
        if ($slashes) { [void]$builder.Append(('\' * $slashes)); $slashes = 0 }
        [void]$builder.Append($char)
    }
    if ($slashes) { [void]$builder.Append(('\' * (2 * $slashes))) }
    [void]$builder.Append('"')
    return $builder.ToString()
}

function Join-WindowsArguments([string[]]$Values) {
    return (($Values | ForEach-Object { ConvertTo-WindowsArgument ([string]$_) }) -join ' ')
}

function Write-RunLog([string]$Message) {
    Add-Content -LiteralPath $script:launcherLog -Value $Message -Encoding utf8
}

if (!(Test-Path -LiteralPath $python)) { throw "Project Python is missing: $python" }
if (!(Test-Path -LiteralPath $workspaceFull)) { throw "Candidate workspace is missing: $workspaceFull" }
if (!(Test-Path -LiteralPath $g6Script) -or !(Test-Path -LiteralPath $batchScript) -or
    !(Test-Path -LiteralPath $collectorScript)) { throw 'A required G6/G7/ETW script is missing.' }

$manifestPath = Join-Path $workspaceFull 'g6_usb_manifest.json'
$elfPath = Join-Path $workspaceFull 'g6_usb/build/g6_usb.elf'
$manifest = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
$identity = [ordered]@{
    manifest_sha256 = (Get-FileHash -LiteralPath $manifestPath -Algorithm SHA256).Hash.ToLowerInvariant()
    elf_sha256 = (Get-FileHash -LiteralPath $elfPath -Algorithm SHA256).Hash.ToLowerInvariant()
    xsa_sha256 = [string]$manifest.xsa_sha256
}
if (!$identity.xsa_sha256 -or !$manifest.xsa -or !(Test-Path -LiteralPath $manifest.xsa)) {
    throw 'Candidate manifest has no valid XSA identity.'
}
if ((Get-FileHash -LiteralPath $manifest.xsa -Algorithm SHA256).Hash.ToLowerInvariant() -ne $identity.xsa_sha256) {
    throw 'Candidate XSA does not match the manifest.'
}

if ($Plan) {
    [pscustomobject]@{
        action = 'PlanOnly'
        candidate = $workspaceFull
        build = $identity
        sequence = @('verify_candidate_hashes', 'JTAG_load_candidate_and_capture_3s_baseline',
                     'start_non_payload_USB_ETW', 'run_one_receiver_exit_trial_without_JTAG_reload',
                     'stop_ETW_even_if_trial_fails')
        administrator_required_to_run = $true
        persistent_storage_written = $false
        raw_logs_directory = [IO.Path]::GetFullPath($outputRoot)
        trial = @{ attempts = 1; fault_seconds = 30; recovery_seconds = 2; wait_cdc_seconds = 20 }
    } | ConvertTo-Json -Depth 6
    exit 0
}

if (!(Test-IsAdministrator)) { throw 'Run this one-shot diagnostic from an elevated PowerShell window.' }
$env:EYEPQC_TOOL_ROOT = $toolRoot

$devices = @(Get-PnpDevice -PresentOnly -ErrorAction Stop | Where-Object {
    ([string]$_.InstanceId).StartsWith('USB\VID_03FD&PID_7020\', [StringComparison]::OrdinalIgnoreCase)
})
if ($devices.Count -ne 1 -or $devices[0].Status -ne 'OK') {
    throw "Expected exactly one healthy EYEPQC CDC device (VID_03FD&PID_7020); found $($devices.Count). No test was started."
}
$jtagDevices = @(Get-PnpDevice -PresentOnly -ErrorAction Stop | Where-Object {
    ([string]$_.InstanceId).StartsWith('USB\VID_0403&PID_6014\', [StringComparison]::OrdinalIgnoreCase)
})
if ($jtagDevices.Count -ne 1 -or $jtagDevices[0].Status -ne 'OK') {
    throw "Expected exactly one healthy FTDI JTAG device (VID_0403&PID_6014); found $($jtagDevices.Count). No test was started."
}
$busyProcesses = @(Get-Process python,pythonw,xsdb,hw_server,vivado,vitis -ErrorAction SilentlyContinue)
if ($busyProcesses.Count) {
    throw "Another Python/Vivado/JTAG process is active ($($busyProcesses.ProcessName -join ', ')); stop before starting this diagnostic."
}

New-Item -ItemType Directory -Path $outputRoot -Force | Out-Null
$stamp = Get-Date -Format 'yyyyMMdd_HHmmss_fff'
$script:launcherLog = Join-Path $outputRoot "single_$stamp.launcher.log"
$baselineStdout = Join-Path $outputRoot "single_$stamp.baseline.stdout.log"
$baselineStderr = Join-Path $outputRoot "single_$stamp.baseline.stderr.log"
$trialStdout = Join-Path $outputRoot "single_$stamp.trial.stdout.log"
$trialStderr = Join-Path $outputRoot "single_$stamp.trial.stderr.log"
$traceStarted = $false
$exitCode = 1
$baselineResultPath = $null
$etlPath = $null

try {
    Write-RunLog "G7_ETW_SINGLE_START utc=$([DateTime]::UtcNow.ToString('o')) candidate=$workspaceFull"
    $verify = @(& $python $g6Script --workspace $workspaceFull --tool-root $toolRoot --verify-only 2>&1 |
        ForEach-Object { [string]$_ })
    $verifyExit = $LASTEXITCODE
    foreach ($line in $verify) { Write-RunLog "VERIFY $line" }
    if ($verifyExit -ne 0) { throw "Candidate verify-only failed with exit code $verifyExit." }

    $baselineArgs = @(
        $g6Script, '--workspace', $workspaceFull, '--tool-root', $toolRoot,
        '--seconds', '3', '--wait-cdc', '30', '--sessions', '1',
        '--report-key-fingerprint', '--debug-stage'
    )
    $baselineProcess = Start-Process -FilePath $python -ArgumentList (Join-WindowsArguments $baselineArgs) `
        -WorkingDirectory $root -PassThru -Wait -WindowStyle Hidden `
        -RedirectStandardOutput $baselineStdout -RedirectStandardError $baselineStderr
    if ($baselineProcess.ExitCode -ne 0) {
        throw "Fresh candidate012 JTAG baseline failed with exit code $($baselineProcess.ExitCode); see $baselineStderr."
    }
    $marker = Get-Content -LiteralPath $baselineStdout | Where-Object { $_ -match '^G6_RUN_RESULT path=' } | Select-Object -Last 1
    $markerMatch = if ($marker) { [regex]::Match([string]$marker, '^G6_RUN_RESULT path=(.+)$') } else { $null }
    if (!$markerMatch -or !$markerMatch.Success) { throw 'Fresh baseline did not emit G6_RUN_RESULT.' }
    $baselineResultPath = [IO.Path]::GetFullPath($markerMatch.Groups[1].Value.Trim().Trim('"'))
    $capturePrefix = [IO.Path]::GetFullPath((Join-Path $root 'data/captures')).TrimEnd([IO.Path]::DirectorySeparatorChar) + [IO.Path]::DirectorySeparatorChar
    if (!$baselineResultPath.StartsWith($capturePrefix, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Fresh baseline result is outside data/captures: $baselineResultPath"
    }
    $baseline = Get-Content -LiteralPath $baselineResultPath -Raw | ConvertFrom-Json
    if ($baseline.status -ne 'passed' -or $baseline.parameters.jtag_load -ne $true -or
        $baseline.jtag_completed -ne $true -or $baseline.build.manifest_sha256 -ne $identity.manifest_sha256 -or
        $baseline.build.elf_sha256 -ne $identity.elf_sha256 -or $baseline.build.xsa_sha256 -ne $identity.xsa_sha256 -or
        !$baseline.sessions -or $baseline.sessions[0].frames -lt 2) {
        throw 'Fresh JTAG baseline did not pass the candidate identity, load, or authenticated-frame checks.'
    }
    Write-RunLog "BASELINE_OK result=$baselineResultPath frames=$($baseline.sessions[0].frames)"

    $startOutput = @(& $collectorScript -Action Start 2>&1 | ForEach-Object { [string]$_ })
    foreach ($line in $startOutput) { Write-RunLog "ETW_START $line" }
    $traceStarted = $true

    $batchArgs = @(
        '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', $batchScript,
        '-Mode', 'ReceiverExit', '-Attempts', '1', '-RecoverySeconds', '2',
        '-FaultSeconds', '30', '-WaitCdcSeconds', '20',
        '-Workspace', $workspace, '-HostSourceRoot', $root
    )
    $pwsh = (Get-Command pwsh.exe -ErrorAction Stop).Source
    $trialProcess = Start-Process -FilePath $pwsh -ArgumentList (Join-WindowsArguments $batchArgs) `
        -WorkingDirectory $root -PassThru -Wait -WindowStyle Hidden `
        -RedirectStandardOutput $trialStdout -RedirectStandardError $trialStderr
    $exitCode = $trialProcess.ExitCode
    Write-RunLog "TRIAL_EXIT code=$exitCode stdout=$trialStdout stderr=$trialStderr"
}
catch {
    Write-RunLog ("ERROR " + $_.Exception.Message)
    if ($exitCode -eq 1) { $exitCode = 2 }
}
finally {
    if ($traceStarted) {
        try {
            $stopOutput = @(& $collectorScript -Action Stop 2>&1 | ForEach-Object { [string]$_ })
            foreach ($line in $stopOutput) { Write-RunLog "ETW_STOP $line" }
            $pointerPath = Join-Path $outputRoot 'active.json'
            if (Test-Path -LiteralPath $pointerPath) {
                $pointer = Get-Content -LiteralPath $pointerPath -Raw | ConvertFrom-Json
                $traceManifest = Get-Content -LiteralPath $pointer.manifest_path -Raw | ConvertFrom-Json
                $etlPath = [string]$traceManifest.output_etl
            }
        }
        catch {
            Write-RunLog ("ETW_STOP_ERROR " + $_.Exception.Message)
            if ($exitCode -eq 0) { $exitCode = 3 }
        }
    }
    Write-RunLog "G7_ETW_SINGLE_DONE exit_code=$exitCode baseline=$baselineResultPath etl=$etlPath"
}

Write-Output "G7_ETW_SINGLE_DONE exit_code=$exitCode baseline=$baselineResultPath etl=$etlPath launcher=$script:launcherLog"
if ($exitCode -ne 0) { exit $exitCode }
