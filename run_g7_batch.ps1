param(
    [ValidateSet('ReceiverExit')][string]$Mode = 'ReceiverExit',
    [int]$Attempts = 20,
    [int]$RecoverySeconds = 2,
    [int]$FaultSeconds = 600,
    [int]$WaitCdcSeconds = 20,
    [switch]$DryRun,
    [switch]$Mock,
    [int]$MockFailAt = 0,
    [int]$MockFramesBeforeKill = 2,
    [string]$ResumeDirectory,
    [string]$Workspace = (Join-Path $PSScriptRoot 'build/vitis/usbfix3_20261007'),
    [string]$HostSourceRoot = $PSScriptRoot
)
$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot
$hostSourceRoot = [IO.Path]::GetFullPath($HostSourceRoot)
$workspace = if ([IO.Path]::IsPathRooted($Workspace)) { [IO.Path]::GetFullPath($Workspace) } else { [IO.Path]::GetFullPath((Join-Path $root $Workspace)) }
$python = Join-Path $root '.venv/Scripts/python.exe'
$diagScript = Join-Path $root 'prj/capture_g6_rekey_diag.py'
$hostScript = Join-Path $hostSourceRoot 'src/host/g6_board.py'
$toolRoot = if ($env:EYEPQC_TOOL_ROOT) { $env:EYEPQC_TOOL_ROOT } else { 'E:/fpg/2026.1' }
if ($Attempts -lt 1 -or $Attempts -gt 20 -or $RecoverySeconds -lt 2 -or
    $FaultSeconds -lt 30 -or $WaitCdcSeconds -lt 10) {
    throw 'Use Attempts=1..20, RecoverySeconds>=2, FaultSeconds>=30, WaitCdcSeconds>=10.'
}
if (!(Test-Path -LiteralPath $python)) { throw 'Project .venv Python is missing.' }
if (!(Test-Path -LiteralPath $hostScript)) { throw "HostSourceRoot does not contain src/host/g6_board.py: $hostSourceRoot" }
if (!(Test-Path -LiteralPath (Join-Path $hostSourceRoot 'data/captures'))) { throw "HostSourceRoot has no data/captures directory: $hostSourceRoot" }
if (!(Test-Path -LiteralPath (Join-Path $hostSourceRoot 'report'))) { throw "HostSourceRoot has no report directory: $hostSourceRoot" }

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

function Write-JsonAtomic($Path, $Value) {
    $temp = "$Path.tmp"
    $Value | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath $temp -Encoding utf8
    Move-Item -LiteralPath $temp -Destination $Path -Force
}
function Get-BuildIdentity {
    $manifestPath = Join-Path $workspace 'g6_usb_manifest.json'
    $elfPath = Join-Path $workspace 'g6_usb/build/g6_usb.elf'
    if (!(Test-Path -LiteralPath $manifestPath) -or !(Test-Path -LiteralPath $elfPath)) { throw 'G6 build artifacts are missing.' }
    $manifest = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
    $manifestHash = (Get-FileHash -LiteralPath $manifestPath -Algorithm SHA256).Hash.ToLowerInvariant()
    $elfHash = (Get-FileHash -LiteralPath $elfPath -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($manifest.artifacts.'g6_usb/build/g6_usb.elf' -ne $elfHash) { throw 'ELF hash differs from manifest.' }
    if (!$manifest.xsa -or !$manifest.xsa_sha256) { throw 'Manifest has no complete XSA identity.' }
    if (!(Test-Path -LiteralPath $manifest.xsa)) { throw "Manifest XSA is missing: $($manifest.xsa)" }
    $xsaHash = (Get-FileHash -LiteralPath $manifest.xsa -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($xsaHash -ne $manifest.xsa_sha256) { throw 'XSA hash differs from manifest.' }
    $diagAddress=[uint64]0; $diagSize=[uint32]0
    $diagProperty=$manifest.owned.PSObject.Properties['g6_rekey_diagnostic']
    if ($diagProperty) {
        $diagOwned=$diagProperty.Value
        $diagAddress=[uint64]$diagOwned.address; $diagSize=[uint32]$diagOwned.size
        if ($diagAddress -lt 0x00100000 -or $diagAddress -ge 0x40000000 -or
            ($diagAddress % 64) -ne 0 -or $diagSize -ne 144) {
            throw 'Manifest has an invalid G6 rekey diagnostic DDR range.'
        }
    }
    return [pscustomobject]@{ manifest_sha256=$manifestHash; elf_sha256=$elfHash; xsa_sha256=$manifest.xsa_sha256;
        rekey_diag_address=$diagAddress; rekey_diag_size=$diagSize }
}
function Read-RekeyDiagnostic($Identity, [string]$OutputPrefix) {
    if (!$Identity.rekey_diag_address -or $Identity.rekey_diag_size -ne 144) {
        throw 'This build has no owned G6 rekey diagnostic symbol; use the receiver-exit diagnostic candidate.'
    }
    if (!(Test-Path -LiteralPath $diagScript)) { throw "G6 diagnostic reader is missing: $diagScript" }
    $arguments=@('-u',$diagScript,'--workspace',$workspace,'--tool-root',$toolRoot,'--output-prefix',$OutputPrefix)
    $output = & $python @arguments 2>&1
    $exitCode=$LASTEXITCODE
    $output | Set-Content -LiteralPath ($OutputPrefix + '_launcher.log') -Encoding utf8
    if ($exitCode -ne 0) { throw "Read-only G6 rekey diagnostic capture failed (exit=$exitCode)." }
    $jsonPath=$OutputPrefix + '.json'
    if (!(Test-Path -LiteralPath $jsonPath)) { throw 'G6 rekey diagnostic capture did not write its JSON snapshot.' }
    $record=Get-Content -LiteralPath $jsonPath -Raw | ConvertFrom-Json
    if ($record.build.manifest_sha256 -ne $Identity.manifest_sha256 -or
        $record.build.elf_sha256 -ne $Identity.elf_sha256 -or
        $record.build.xsa_sha256 -ne $Identity.xsa_sha256) {
        throw 'G6 rekey diagnostic snapshot build identity differs from the active batch.'
    }
    return $record.diagnostic
}
function Get-Baseline($Identity) {
    $files = Get-ChildItem (Join-Path $hostSourceRoot 'data/captures') -Directory -Filter 'g6_usb_*' -ErrorAction SilentlyContinue |
        Sort-Object CreationTimeUtc -Descending
    foreach ($dir in $files) {
        $path = Join-Path $dir.FullName 'result.json'
        if (!(Test-Path -LiteralPath $path)) { continue }
        try { $j = Get-Content -LiteralPath $path -Raw | ConvertFrom-Json } catch { continue }
        if ($j.status -eq 'passed' -and $j.parameters.jtag_load -eq $true -and
            $j.build.manifest_sha256 -eq $Identity.manifest_sha256 -and
            $j.build.elf_sha256 -eq $Identity.elf_sha256 -and
            $j.build.xsa_sha256 -eq $Identity.xsa_sha256 -and
            $j.sessions.Count -ge 1 -and $j.sessions[0].frames -ge 2) { return $path }
    }
    return $null
}
function Save-Summary($Directory, $Identity, $Status, $BaselinePath, $Passed, $CurrentTrial) {
    $summaryPath = Join-Path $Directory 'batch_summary.json'
    Write-JsonAtomic $summaryPath ([ordered]@{
        schema='eyepqc-g7-batch-v1'; mode=$Mode; status=$Status; attempts_required=$Attempts
        attempts_passed=$Passed; recovery_seconds=$RecoverySeconds; fault_seconds=$FaultSeconds
        build=$Identity; workspace=$workspace; host_source_root=$hostSourceRoot
        baseline_result=$BaselinePath; current_trial=$CurrentTrial
        jtag_reload_during_trials=$false; generated_utc=[DateTime]::UtcNow.ToString('o')
        note='Each attempt requires >=2 authenticated and decoded JPEG frames before termination and after a new handshake. Key fingerprints are SHA-256 only; no key material is recorded.'
    })
}
function Assert-BuildAndNoJtag($Result, $Identity, [string]$Context) {
    if ($Result.build.manifest_sha256 -ne $Identity.manifest_sha256 -or
        $Result.build.elf_sha256 -ne $Identity.elf_sha256 -or
        $Result.build.xsa_sha256 -ne $Identity.xsa_sha256 -or
        $Result.parameters.jtag_load -ne $false) {
        throw "$Context result has a mismatched manifest/ELF/XSA or records JTAG reload."
    }
}
function Get-RunResultMarker([string]$StdoutPath, [int]$TimeoutSeconds = 5) {
    $deadline = [DateTime]::UtcNow.AddSeconds($TimeoutSeconds)
    while ([DateTime]::UtcNow -lt $deadline) {
        if (Test-Path -LiteralPath $StdoutPath) {
            $marker = Get-Content -LiteralPath $StdoutPath -ErrorAction SilentlyContinue |
                Where-Object { $_ -match '^G6_RUN_RESULT path=(.+)$' } | Select-Object -Last 1
            if ($marker -and $marker -match '^G6_RUN_RESULT path=(.+)$') {
                $candidate = [IO.Path]::GetFullPath($Matches[1].Trim().Trim('"'))
                $capturesRoot = [IO.Path]::GetFullPath((Join-Path $hostSourceRoot 'data/captures')).TrimEnd([IO.Path]::DirectorySeparatorChar) + [IO.Path]::DirectorySeparatorChar
                if (!$candidate.StartsWith($capturesRoot, [StringComparison]::OrdinalIgnoreCase)) {
                    throw "G6_RUN_RESULT is outside HostSourceRoot/data/captures: $candidate"
                }
                return $candidate
            }
        }
        Start-Sleep -Milliseconds 100
    }
    throw "Timed out waiting for G6_RUN_RESULT marker in $StdoutPath."
}
function Get-MockFingerprint($Text) {
    $sha = [System.Security.Cryptography.SHA256]::Create()
    try { return ([BitConverter]::ToString($sha.ComputeHash([Text.Encoding]::UTF8.GetBytes($Text)))).Replace('-', '').ToLowerInvariant() }
    finally { $sha.Dispose() }
}
function Get-ValidatedPassedTrials([string]$Directory,[object]$Identity,[int]$Required) {
    $passed=@{}
    foreach ($path in Get-ChildItem -LiteralPath $Directory -Filter 'trial_*_try*.json' -ErrorAction SilentlyContinue) {
        if ($path.BaseName -notmatch '^trial_(\d+)_try(\d+)$') { continue }
        $nameTrial=[int]$Matches[1];$nameTry=[int]$Matches[2]
        try { $old=Get-Content -LiteralPath $path.FullName -Raw|ConvertFrom-Json } catch { throw "Unreadable trial record: $($path.Name)" }
        if ([int]$old.trial -ne $nameTrial -or [int]$old.try -ne $nameTry) { throw "Trial JSON identity does not match filename: $($path.Name)" }
        if ($old.status -ne 'passed') { continue }
        if ($old.mock -eq $true -or [int]$old.trial -lt 1 -or [int]$old.trial -gt $Required -or $old.jtag_reload -ne $false -or
            $old.build.elf_sha256 -ne $Identity.elf_sha256 -or $old.build.manifest_sha256 -ne $Identity.manifest_sha256 -or
            $old.build.xsa_sha256 -ne $Identity.xsa_sha256 -or $old.interrupted_verified_frames -lt 2 -or $old.recovery_frames -lt 2 -or
            !$old.session_id_changed -or !$old.key_changed -or
            $old.interrupted_key_fingerprint_sha256 -notmatch '^[0-9a-f]{64}$' -or
            $old.recovery_key_fingerprint_sha256 -notmatch '^[0-9a-f]{64}$') { throw "Passed trial record failed integrity checks: $($path.Name)" }
        if ($passed.ContainsKey([int]$old.trial)) { throw "Duplicate passed trial number $($old.trial)." }
        $passed[[int]$old.trial]=$path.Name
    }
    for ($n=1;$n -le $passed.Count;$n++) { if (!$passed.ContainsKey($n)) { throw "Passed trial set is not a contiguous prefix 1..N; missing trial $n." } }
    return ,$passed
}
function Get-NextTryNumber([string]$Directory, [int]$Trial) {
    $pattern = '^trial_{0:d2}_try(\d+)$' -f $Trial
    $numbers = @()
    foreach ($file in Get-ChildItem -LiteralPath $Directory -File -Filter ('trial_{0:d2}_try*.json' -f $Trial) -ErrorAction SilentlyContinue) {
        if ($file.BaseName -match $pattern) { $numbers += [int]$Matches[1] }
    }
    if ($numbers.Count -eq 0) { return 1 }
    return (($numbers | Measure-Object -Maximum).Maximum + 1)
}

$identity = Get-BuildIdentity
if ($DryRun) {
    "G7_BATCH_DRY_RUN_OK mode=$Mode attempts=$Attempts recovery_seconds=$RecoverySeconds fault_seconds=$FaultSeconds jtag_reload_during_trials=false build=$($identity.elf_sha256) workspace=$workspace hostsource=$hostSourceRoot"
    exit 0
}
if ($Mock -and $ResumeDirectory) { throw 'Mock runs create a fresh directory; ResumeDirectory is for physical evidence only.' }

if ($ResumeDirectory) {
    $runDir = [IO.Path]::GetFullPath($ResumeDirectory)
    if (!(Test-Path -LiteralPath $runDir)) { throw "ResumeDirectory does not exist: $runDir" }
    if ((Split-Path $runDir -Leaf) -like 'g7_batch_mock_*') { throw 'Mock evidence cannot be resumed as a physical batch.' }
    $oldSummaryPath = Join-Path $runDir 'batch_summary.json'
    if (!(Test-Path -LiteralPath $oldSummaryPath)) { throw 'Resume directory has no batch_summary.json.' }
    $oldSummary = Get-Content -LiteralPath $oldSummaryPath -Raw | ConvertFrom-Json
    if ($oldSummary.schema -ne 'eyepqc-g7-batch-v1' -or $oldSummary.mode -ne 'ReceiverExit' -or
        $oldSummary.build.elf_sha256 -ne $identity.elf_sha256 -or
        $oldSummary.build.manifest_sha256 -ne $identity.manifest_sha256 -or
        $oldSummary.build.xsa_sha256 -ne $identity.xsa_sha256) {
        throw 'Resume summary schema/mode/build identity does not match this physical batch.'
    }
    if ($oldSummary.host_source_root -and
        [IO.Path]::GetFullPath([string]$oldSummary.host_source_root) -ne $hostSourceRoot) {
        throw 'Resume summary HostSourceRoot does not match this batch.'
    }
    if (!$oldSummary.host_source_root -and $hostSourceRoot -ne [IO.Path]::GetFullPath($root)) {
        throw 'Legacy resume summary has no HostSourceRoot and can only resume with the default source root.'
    }
} else {
    $stamp = Get-Date -Format 'yyyyMMdd_HHmmss_fff'
    $suffix = [guid]::NewGuid().ToString('N').Substring(0,8)
    $leaf = if ($Mock) { "g7_batch_mock_${stamp}_$suffix" } else { "g7_batch_receiver_exit_${stamp}_$suffix" }
    $runDir = Join-Path $hostSourceRoot "report/g7_runs/$leaf"
    New-Item -ItemType Directory -Path $runDir -Force | Out-Null
}

if ($Mock) {
    $passed = 0
    for ($trial = 1; $trial -le $Attempts; $trial++) {
        $sid1 = [uint32](Get-Random -Minimum 1 -Maximum 2147483647)
        $sid2 = [uint32](Get-Random -Minimum 1 -Maximum 2147483647)
        $fp1 = Get-MockFingerprint ([guid]::NewGuid().ToString('N'))
        $fp2 = Get-MockFingerprint ([guid]::NewGuid().ToString('N'))
        $case = [ordered]@{ trial=$trial; status='passed'; mock=$true; fault_stage='two_verified_frames';
            kill_after_verified_frames=$MockFramesBeforeKill; interrupted_session_id=$sid1; interrupted_verified_frames=$MockFramesBeforeKill; interrupted_auth_failures=0;
            recovery_session_id=$sid2; recovery_key_fingerprint_sha256=$fp2; interrupted_key_fingerprint_sha256=$fp1;
            session_id_changed=($sid1 -ne $sid2); key_changed=($fp1 -ne $fp2); recovery_frames=2;
            recovery_errors=@{}; jtag_reload=$false }
        if ($MockFramesBeforeKill -lt 2) {
            $case.status='failed'; $case.stage='minimum_verified_frame_gate'; $case.error='Scheduler stopped before killing a receiver with fewer than two verified frames.'
            Write-JsonAtomic (Join-Path $runDir ('trial_{0:d2}_try01.json' -f $trial)) $case
            Save-Summary $runDir $identity 'failed' $null $passed $trial
            "G7_BATCH_MOCK_FAIL_STOP trial=$trial stage=minimum_verified_frame_gate evidence=$runDir"
            exit 2
        }
        if ($sid1 -eq $sid2 -or $fp1 -eq $fp2 -or $fp1.Length -ne 64 -or $fp2.Length -ne 64) { throw 'Mock invariant failed: uniqueness/fingerprint check did not trip.' }
        if ($MockFailAt -eq $trial) {
            $case.status='failed'; $case.stage='mock_recovery'; $case.error='Injected mock failure; scheduler must stop immediately.'
            Write-JsonAtomic (Join-Path $runDir ('trial_{0:d2}_try01.json' -f $trial)) $case
            Save-Summary $runDir $identity 'failed' $null $passed $trial
            "G7_BATCH_MOCK_FAIL_STOP trial=$trial previous_passes=$passed evidence=$runDir"
            exit 2
        }
        Write-JsonAtomic (Join-Path $runDir ('trial_{0:d2}_try01.json' -f $trial)) $case
        $passed++
        Save-Summary $runDir $identity 'mock_complete' $null $passed $null
    }
    "G7_BATCH_MOCK_OK attempts=$passed evidence=$runDir"
    exit 0
}

$savedPath = $env:PATH
$savedTool = $env:EYEPQC_TOOL_ROOT
$worker=$null;$recovery=$null
try {
    $env:EYEPQC_TOOL_ROOT = $toolRoot
    if (Test-Path 'C:/msys64/ucrt64/bin') { $env:PATH = 'C:/msys64/ucrt64/bin;' + $env:PATH }
    & $python $hostScript --workspace $workspace --tool-root $toolRoot --verify-only
    if ($LASTEXITCODE -ne 0) { throw 'G6 software/build verification failed.' }
    $busy = @(Get-CimInstance Win32_Process | Where-Object {
        $_.CommandLine -match 'demo_window\.py|demo_controller\.py|g6_board\.py|run_g7_recovery\.ps1'
    })
    if ($busy.Count) { throw "G6/demo process already present; refusing to contend for USB: $($busy.ProcessId -join ',')." }
    $devices = @(Get-PnpDevice -PresentOnly -ErrorAction SilentlyContinue | Where-Object { $_.InstanceId -match 'VID_03FD&PID_7020' })
    if ($devices.Count -ne 1) { throw "Expected one enumerated G6 CDC device; found $($devices.Count). Load/recover through the existing approved G6 entry first." }
    $baselinePath = Get-Baseline $identity
    if (!$baselinePath) { throw 'No matching passed JTAG-loaded G6 baseline with >=2 frames; run existing run_g7_recovery.ps1 -BaselineOnly first.' }

    $passedTrials=Get-ValidatedPassedTrials $runDir $identity $Attempts
    $passed = $passedTrials.Count
    if ($ResumeDirectory -and [int]$oldSummary.attempts_passed -ne $passed) { throw 'Resume summary passed count differs from valid trial records.' }
    if ($passed -ge $Attempts) { throw "Batch already contains $passed passed attempts." }
    Save-Summary $runDir $identity 'running' $baselinePath $passed $null

    while ($passed -lt $Attempts) {
        $trial = $passed + 1
        $tryNumber = Get-NextTryNumber $runDir $trial
        $casePath = Join-Path $runDir ('trial_{0:d2}_try{1:d2}.json' -f $trial,$tryNumber)
        $workerOut = Join-Path $runDir ('trial_{0:d2}_try{1:d2}_interrupted.stdout.log' -f $trial,$tryNumber)
        $workerErr = Join-Path $runDir ('trial_{0:d2}_try{1:d2}_interrupted.stderr.log' -f $trial,$tryNumber)
        $case = [ordered]@{ trial=$trial; try=$tryNumber; status='running'; stage='start_interrupted_receiver';
            build=$identity; baseline_result=$baselinePath; jtag_reload=$false; started_utc=[DateTime]::UtcNow.ToString('o') }
        Write-JsonAtomic $casePath $case
        Save-Summary $runDir $identity 'running' $baselinePath $passed $trial
        $workerArgs = @('-u',$hostScript,'--workspace',$workspace,'--tool-root',$toolRoot,
            '--no-jtag','--seconds',"$FaultSeconds",'--wait-cdc',"$WaitCdcSeconds",'--sessions','1','--report-key-fingerprint','--debug-stage')
        $worker = $null
        $recovery = $null
        try {
            $worker = Start-Process -FilePath $python -ArgumentList (Join-WindowsArguments $workerArgs) -WorkingDirectory $hostSourceRoot `
                -RedirectStandardOutput $workerOut -RedirectStandardError $workerErr -PassThru -WindowStyle Hidden
            $deadline = [DateTime]::UtcNow.AddSeconds($WaitCdcSeconds + 60)
            $established = $null; $ready = $null; $runMarker = $null
            while ([DateTime]::UtcNow -lt $deadline) {
                if (Test-Path -LiteralPath $workerOut) {
                    $lines = Get-Content -LiteralPath $workerOut -ErrorAction SilentlyContinue
                    $established = $lines | Where-Object { $_ -match '^G6_SESSION_ESTABLISHED ' } | Select-Object -Last 1
                    $ready = $lines | Where-Object { $_ -match '^G6_STREAM_READY ' } | Select-Object -Last 1
                    $runMarker = $lines | Where-Object { $_ -match '^G6_RUN_RESULT path=' } | Select-Object -Last 1
                }
                if ($ready) { break }
                if ($worker.HasExited) { throw "Interrupted receiver exited before verified-frame readiness (exit=$($worker.ExitCode))." }
                Start-Sleep -Milliseconds 200
            }
            if (!$ready -or !$established -or !$runMarker) { throw 'Timed out waiting for authenticated, decoded JPEG stream readiness and its result-path marker.' }
            if ($ready -notmatch 'frames=(\d+)') { throw 'Readiness marker did not report frame count.' }
            $observedFrames = [int]$Matches[1]
            if ($observedFrames -lt 2) { throw "Only $observedFrames verified frames before termination; minimum is 2." }
            if ($established -notmatch 'session_id=(\d+).*video_key_sha256=([0-9a-f]{64})') { throw 'Session marker lacks session ID/key fingerprint.' }
            $interruptedId = [uint32]$Matches[1]; $interruptedFp = $Matches[2]
            $partialResult = Get-RunResultMarker $workerOut
            $partial = $null; $partialSession = $null
            $persistDeadline = [DateTime]::UtcNow.AddSeconds(5)
            while ([DateTime]::UtcNow -lt $persistDeadline -and !$partialSession) {
                if (Test-Path -LiteralPath $partialResult) {
                    try {
                        $partial = Get-Content -LiteralPath $partialResult -Raw | ConvertFrom-Json
                        foreach ($candidateSession in @($partial.sessions)) {
                            if ([string]$candidateSession.session_id -ceq [string]$interruptedId) { $partialSession=$candidateSession; break }
                        }
                    } catch { $partial=$null }
                }
                if (!$partialSession) { Start-Sleep -Milliseconds 100 }
            }
            if (!$partialSession) {
                $seenIds = (@($partial.sessions) | ForEach-Object { $_.session_id }) -join ','
                throw "Interrupted result marker/session does not match stdout session $interruptedId; found [$seenIds] in $partialResult."
            }
            Assert-BuildAndNoJtag $partial $identity 'Interrupted receiver'
            if ($partialSession.video_key_sha256 -cne $interruptedFp) {
                throw 'Interrupted result session/key does not match this process stdout.'
            }
            if ([int]$partialSession.observed_verified_frames -lt 2) { throw 'Interrupted result has fewer than two verified/decode-success frames.' }
            $oldErrors=$partialSession.observed_statistics
            foreach ($counter in @('auth_failures','invalid_authenticated_jpeg','replay_rejects','sequence_gaps','out_of_order','fragment_errors','dropped_frames')) {
                $property=$oldErrors.PSObject.Properties[$counter]
                if ($property -and [int]$property.Value -gt 0) { throw "Interrupted receiver observed $counter=$($property.Value)." }
            }
            foreach ($imageName in @('first.jpg','last.jpg')) {
                if (!(Test-Path -LiteralPath (Join-Path $partialSession.capture_directory $imageName))) { throw "Interrupted frame evidence missing: $imageName" }
            }
            $case.stage='verified_stream_ready'; $case.interrupted_session_id=$interruptedId
            $case.interrupted_key_fingerprint_sha256=$interruptedFp; $case.interrupted_verified_frames=$partialSession.observed_verified_frames
            $case.interrupted_verified_bytes=$partialSession.observed_verified_bytes; $case.interrupted_statistics=$partialSession.observed_statistics
            $case.interrupted_result=$partialResult
            $case.interrupted_first_jpeg=(Join-Path $partialSession.capture_directory 'first.jpg')
            $case.interrupted_last_jpeg=(Join-Path $partialSession.capture_directory 'last.jpg')
            Write-JsonAtomic $casePath $case
            if ($worker.HasExited) { throw 'Receiver ended before the forced-exit action; trial not counted.' }
            Stop-Process -Id $worker.Id -Force
            $worker.WaitForExit()
            $case.stage='receiver_terminated'; $case.receiver_exit_code=$worker.ExitCode; Write-JsonAtomic $casePath $case

            $case.stage='read_pre_recovery_rekey_diag'; Write-JsonAtomic $casePath $case
            $preRekeyDiag=Read-RekeyDiagnostic $identity (Join-Path $runDir ('trial_{0:d2}_try{1:d2}_rekey_before' -f $trial,$tryNumber))
            $case.pre_recovery_rekey_diag=$preRekeyDiag

            $recoverOut = Join-Path $runDir ('trial_{0:d2}_try{1:d2}_recovery.stdout.log' -f $trial,$tryNumber)
            $recoverErr = Join-Path $runDir ('trial_{0:d2}_try{1:d2}_recovery.stderr.log' -f $trial,$tryNumber)
            $recoverArgs = @('-u',$hostScript,'--workspace',$workspace,'--tool-root',$toolRoot,
                '--no-jtag','--seconds',"$RecoverySeconds",'--wait-cdc',"$WaitCdcSeconds",'--sessions','1','--report-key-fingerprint','--debug-stage')
            $recovery = Start-Process -FilePath $python -ArgumentList (Join-WindowsArguments $recoverArgs) -WorkingDirectory $hostSourceRoot `
                -RedirectStandardOutput $recoverOut -RedirectStandardError $recoverErr -PassThru -WindowStyle Hidden
            $recoveryTimedOut=$false
            if (!$recovery.WaitForExit(($RecoverySeconds + $WaitCdcSeconds + 60) * 1000)) {
                Stop-Process -Id $recovery.Id -Force -ErrorAction SilentlyContinue
                $recovery.WaitForExit()
                $recoveryTimedOut=$true
            }
            $case.stage='read_post_recovery_rekey_diag'; Write-JsonAtomic $casePath $case
            $postRekeyDiag=Read-RekeyDiagnostic $identity (Join-Path $runDir ('trial_{0:d2}_try{1:d2}_rekey_after' -f $trial,$tryNumber))
            $helloAttemptDelta = ([long]$postRekeyDiag.hello_attempts - [long]$preRekeyDiag.hello_attempts + 4294967296) % 4294967296
            $ackAttemptDelta = ([long]$postRekeyDiag.hello_ack_send_attempts - [long]$preRekeyDiag.hello_ack_send_attempts + 4294967296) % 4294967296
            $case.post_recovery_rekey_diag=$postRekeyDiag
            $case.rekey_hello_attempt_delta=$helloAttemptDelta
            $case.rekey_ack_attempt_delta=$ackAttemptDelta
            Write-JsonAtomic $casePath $case
            if ($recoveryTimedOut) { throw 'Recovery receiver exceeded bounded wait; AP0 rekey snapshot was captured afterward.' }
            if ($recovery.ExitCode -ne 0) { throw "Recovery receiver failed (exit=$($recovery.ExitCode)); inspect $recoverErr." }
            if ($helloAttemptDelta -lt 1 -or $ackAttemptDelta -lt 1 -or $postRekeyDiag.hello_ack_send_status -ne 0) {
                throw 'Recovery succeeded on the host but board AP0 evidence lacks a fresh HELLO and successful ACK-send attempt.'
            }
            $recoveryResultPath = Get-RunResultMarker $recoverOut
            if (!(Test-Path -LiteralPath $recoveryResultPath)) { throw "Recovery result marker target does not exist: $recoveryResultPath" }
            $recoveryResult=Get-Content -LiteralPath $recoveryResultPath -Raw | ConvertFrom-Json
            Assert-BuildAndNoJtag $recoveryResult $identity 'Recovery receiver'
            if ($recoveryResult.status -ne 'passed' -or @($recoveryResult.sessions).Count -ne 1) { throw 'Marked recovery result is not a passed single-session result.' }
            $recovery=$null
            $new = $recoveryResult.sessions[0]
            $recoveryEstablished = Get-Content -LiteralPath $recoverOut -ErrorAction SilentlyContinue |
                Where-Object { $_ -match '^G6_SESSION_ESTABLISHED ' } | Select-Object -Last 1
            if (!$recoveryEstablished -or $recoveryEstablished -notmatch 'session_id=(\d+).*video_key_sha256=([0-9a-f]{64})') {
                throw 'Recovery stdout lacks a valid established session/key fingerprint marker.'
            }
            if ([string]$new.session_id -cne $Matches[1] -or $new.video_key_sha256 -cne $Matches[2]) {
                throw 'Marked recovery result session/key does not match this process stdout.'
            }
            if ($new.frames -lt 2 -or $new.session_id -eq $interruptedId) { throw 'Recovery did not produce >=2 frames with a fresh session ID.' }
            if (!$new.video_key_sha256 -or $new.video_key_sha256 -eq $interruptedFp) { throw 'Recovery video-key fingerprint was absent or reused.' }
            $bad = @('auth_failures','replay_rejects','sequence_gaps','out_of_order','fragment_errors','invalid_authenticated_jpeg','malformed_video','invalid_session_or_header','dropped_frames') |
                Where-Object { [int]$new.errors.$_ -gt 0 }
            if ($bad.Count -or $new.packets -ne $new.errors.authenticated_packets) { throw "Recovery integrity/error counters failed: $($bad -join ',')." }
            $case.stage='complete'; $case.status='passed'; $case.recovery_result=$recoveryResultPath
            $case.recovery_session_id=$new.session_id; $case.recovery_key_fingerprint_sha256=$new.video_key_sha256
            $case.session_id_changed=$true; $case.key_changed=$true; $case.recovery_frames=$new.frames
            $case.recovery_packets=$new.packets; $case.recovery_fps=$new.fps; $case.recovery_errors=$new.errors
            $case.recovery_first_jpeg=(Join-Path $new.output 'first.jpg'); $case.recovery_last_jpeg=(Join-Path $new.output 'last.jpg')
            $case.completed_utc=[DateTime]::UtcNow.ToString('o'); Write-JsonAtomic $casePath $case
            $passed++
            Save-Summary $runDir $identity 'running' $baselinePath $passed $null
            Write-Host "G7_RECEIVER_EXIT_PASS trial=$passed/$Attempts old_session=$interruptedId new_session=$($new.session_id) frames=$($new.frames) fps=$([Math]::Round($new.fps,3))"
        } catch {
            if ($worker -and !$worker.HasExited) { Stop-Process -Id $worker.Id -Force -ErrorAction SilentlyContinue }
            if ($recovery -and !$recovery.HasExited) { Stop-Process -Id $recovery.Id -Force -ErrorAction SilentlyContinue }
            $worker=$null;$recovery=$null
            $case.status='failed'; $case.stage_failed=$case.stage; $case.error=$_.Exception.Message
            $case.failed_utc=[DateTime]::UtcNow.ToString('o'); Write-JsonAtomic $casePath $case
            Save-Summary $runDir $identity 'failed' $baselinePath $passed $trial
            Write-Host "G7_BATCH_FAILED trial=$trial stage=$($case.stage_failed) evidence=$casePath"
            throw
        }
    }
    Save-Summary $runDir $identity 'passed' $baselinePath $passed $null
    "G7_RECEIVER_EXIT_BATCH_OK attempts=$passed evidence=$runDir"
} finally {
    if ($worker -and !$worker.HasExited) { Stop-Process -Id $worker.Id -Force -ErrorAction SilentlyContinue }
    if ($recovery -and !$recovery.HasExited) { Stop-Process -Id $recovery.Id -Force -ErrorAction SilentlyContinue }
    $env:PATH=$savedPath; $env:EYEPQC_TOOL_ROOT=$savedTool
}
