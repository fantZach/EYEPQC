param(
    [int]$Attempts = 20,
    [int]$FaultSeconds = 600,
    [int]$RecoverySeconds = 2,
    [int]$WaitTimeoutSeconds = 120,
    [ValidateSet('Normal','Ambiguous','Timeout','Cleanup','PrePromptExit','AtomicFailure','SerialTimingMismatch','ResultStillRunning')][string]$MockScenario = 'Normal',
    [int]$MockFailAt = 0,
    [switch]$DryRun,
    [switch]$Mock,
    [switch]$ReplacementForUnverified,
    [string]$ResumeDirectory
)
$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot
$workspace = Join-Path $root 'build/vitis/usbfix3_20261007'
$python = Join-Path $root '.venv/Scripts/python.exe'
$toolRoot = if ($env:EYEPQC_TOOL_ROOT) { $env:EYEPQC_TOOL_ROOT } else { 'E:/fpg/2026.1' }
if ($Attempts -lt 1 -or $Attempts -gt 20 -or $FaultSeconds -lt 30 -or $RecoverySeconds -lt 2 -or $WaitTimeoutSeconds -lt 10) {
    throw 'Use Attempts=1..20, FaultSeconds>=30, RecoverySeconds>=2, WaitTimeoutSeconds>=10.'
}
if ($ReplacementForUnverified -and ($Attempts -ne 3 -or $ResumeDirectory -or $Mock)) {
    throw 'ReplacementForUnverified is for a new physical three-trial batch only.'
}
if (!(Test-Path -LiteralPath $python)) { throw 'Project .venv Python is missing.' }

function Write-JsonAtomic($Path, $Value) {
    $temp = "$Path.tmp"
    $Value | ConvertTo-Json -Depth 14 | Set-Content -LiteralPath $temp -Encoding utf8
    Move-Item -LiteralPath $temp -Destination $Path -Force
}
function Get-Fingerprint([string]$Text) {
    $sha=[System.Security.Cryptography.SHA256]::Create()
    try { return ([BitConverter]::ToString($sha.ComputeHash([Text.Encoding]::UTF8.GetBytes($Text)))).Replace('-','').ToLowerInvariant() }
    finally { $sha.Dispose() }
}
function Get-BuildIdentity {
    $manifestPath = Join-Path $workspace 'g6_usb_manifest.json'
    $elfPath = Join-Path $workspace 'g6_usb/build/g6_usb.elf'
    if (!(Test-Path -LiteralPath $manifestPath) -or !(Test-Path -LiteralPath $elfPath)) { throw 'G6 artifacts are missing.' }
    $manifest = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
    $manifestHash = (Get-FileHash -LiteralPath $manifestPath -Algorithm SHA256).Hash.ToLowerInvariant()
    $elfHash = (Get-FileHash -LiteralPath $elfPath -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($manifest.artifacts.'g6_usb/build/g6_usb.elf' -ne $elfHash) { throw 'G6 ELF hash differs from manifest.' }
    [pscustomobject]@{ manifest_sha256=$manifestHash; elf_sha256=$elfHash; xsa_sha256=$manifest.xsa_sha256 }
}
function Write-Summary($Dir,$Identity,$Status,$Baseline,$Passed,$MockMode) {
    Write-JsonAtomic (Join-Path $Dir 'batch_summary.json') ([ordered]@{
        schema='eyepqc-g7-usb-unplug-v1'; mode='UsbUnplug'; status=$Status; mock=$MockMode
        purpose=if($ReplacementForUnverified){'three_replacement_trials_for_original_08_14_18'}else{'full_twenty_trial_batch'}
        attempts_required=$Attempts; attempts_passed=$Passed; build=$Identity; baseline_result=$Baseline
        recovery_seconds=$RecoverySeconds; fault_seconds=$FaultSeconds; jtag_reload_during_trials=$false
        current_trial=$null; generated_utc=[DateTime]::UtcNow.ToString('o')
        note='Every pass requires a stable present->missing->present PnP observation and a fresh authenticated video session. No JTAG load is allowed inside a trial.'
    })
}
function Get-DeviceState {
    try {
        $items = @(Get-PnpDevice -PresentOnly -ErrorAction Stop | Where-Object { $_.InstanceId -match 'VID_03FD&PID_7020' })
        if ($items.Count -eq 0) { return [pscustomobject]@{state='missing';count=0} }
        if ($items.Count -eq 1) { return [pscustomobject]@{state='present';count=1;instance=$items[0].InstanceId} }
        return [pscustomobject]@{state='ambiguous';count=$items.Count}
    } catch { return [pscustomobject]@{state='error';count=-1;error=$_.Exception.Message} }
}
function Update-PnpStableCount([object]$State,[string]$Expected,[int]$Previous) {
    if ($State.state -in @('ambiguous','error')) { throw "USB PnP state is $($State.state); refusing to count this trial." }
    if ($State.state -eq $Expected) { return $Previous+1 }
    return 0
}
function Assert-MockTransition([string[]]$Trace,[string]$Expected) {
    $stable=0
    foreach ($state in $Trace) {
        $observation=[pscustomobject]@{state=$state;count=if($state -eq 'present'){1}elseif($state -eq 'missing'){0}else{2}}
        $stable=Update-PnpStableCount $observation $Expected $stable
        if ($stable -ge 2) { return }
    }
    throw "Mock trace did not produce two stable '$Expected' observations."
}
function Add-Observation($Csv,$State,[datetime]$ObservedAt=[DateTime]::UtcNow) {
    Add-Content -LiteralPath $Csv -Value ('{0:o},{1},{2},{3}' -f $ObservedAt,$State.state,$State.count,($State.instance -replace ',',';'))
}
function Wait-StableDevice([string]$Expected,[string]$Csv,[int]$Timeout,[switch]$MockMode) {
    if ($MockMode) { return [pscustomobject]@{first_observation_utc=[DateTime]::UtcNow;confirmed_utc=[DateTime]::UtcNow} }
    $deadline=[DateTime]::UtcNow.AddSeconds($Timeout); $stable=0;$firstExpected=$null
    while ([DateTime]::UtcNow -lt $deadline) {
        $s=Get-DeviceState;$observedAt=[DateTime]::UtcNow;Add-Observation $Csv $s $observedAt
        if ($s.state -eq $Expected -and $stable -eq 0) {$firstExpected=$observedAt}
        $stable=Update-PnpStableCount $s $Expected $stable
        if ($stable -ge 2) { return [pscustomobject]@{first_observation_utc=$firstExpected;confirmed_utc=$observedAt} }
        if ($s.state -ne $Expected) {$firstExpected=$null}
        Start-Sleep -Milliseconds 250
    }
    throw "Timed out waiting for two consecutive '$Expected' PnP observations."
}
function Get-ReceiverExitKind([string]$StderrPath) {
    if (!(Test-Path -LiteralPath $StderrPath)) { return 'missing_stderr' }
    $stderr=Get-Content -LiteralPath $StderrPath -Raw -ErrorAction SilentlyContinue
    if ($stderr -match 'PermissionError: \[WinError 5\].*result\.json') { return 'atomic_result_replace_failure' }
    if ($stderr -match 'serial\.serialutil\.SerialException: ClearCommError failed') { return 'serial_disconnect' }
    if ([string]::IsNullOrWhiteSpace($stderr)) { return 'empty_stderr' }
    return 'unexpected_error'
}
function Test-UsbBatchProcessActive([object]$Process) {
    if ($Process.CommandLine -notmatch 'run_g7_usb_unplug\.ps1') {return $true}
    foreach ($dir in Get-ChildItem (Join-Path $root 'report/g7_runs') -Directory -Filter 'g7_batch_usb_unplug*' -ErrorAction SilentlyContinue) {
        $transcript=Join-Path $dir.FullName 'operator_console.txt';$summaryPath=Join-Path $dir.FullName 'batch_summary.json'
        if (!(Test-Path -LiteralPath $transcript) -or !(Test-Path -LiteralPath $summaryPath)) {continue}
        if (!(Select-String -LiteralPath $transcript -Pattern ("^Process ID: {0}$" -f [int]$Process.ProcessId) -Quiet -ErrorAction SilentlyContinue)) {continue}
        try {$summary=Get-Content -LiteralPath $summaryPath -Raw|ConvertFrom-Json} catch {return $true}
        return ($summary.status -notin @('passed','failed','mock_complete'))
    }
    return $true
}
function Confirm-ExpectedDisconnect($Process,[string]$StderrPath,[string]$ResultPath,[uint32]$SessionId,[datetime]$FirstMissingAt) {
    $Process.Refresh()
    if (!$Process.HasExited) {[void]$Process.WaitForExit(3000);$Process.Refresh()}
    if (!$Process.HasExited) {throw 'Receiver did not exit after the USB device was stably removed.'}
    $exitAt=$Process.ExitTime.ToUniversalTime();$delta=($exitAt-$FirstMissingAt.ToUniversalTime()).TotalSeconds
    $kind=Get-ReceiverExitKind $StderrPath
    if ($kind -ne 'serial_disconnect') {throw "Unexpected receiver exit during unplug: $kind; inspect $StderrPath."}
    if ($delta -lt -1.5 -or $delta -gt 2.0) {throw "Receiver exit was outside the unplug observation window (delta=${delta}s)."}
    $deadline=[DateTime]::UtcNow.AddSeconds(4);$result=$null;$session=$null
    while ([DateTime]::UtcNow -lt $deadline) {
        if (Test-Path -LiteralPath $ResultPath) {
            try {
                $candidate=Get-Content -LiteralPath $ResultPath -Raw|ConvertFrom-Json
                $match=@($candidate.sessions|Where-Object {[string]$_.session_id -ceq [string]$SessionId})|Select-Object -First 1
                if ($candidate.status -ne 'running' -and $candidate.error.class -eq 'SerialException' -and
                    $candidate.error.message -match 'ClearCommError failed' -and $match) {$result=$candidate;$session=$match;break}
            } catch {}
        }
        Start-Sleep -Milliseconds 100
    }
    if (!$result) {throw 'Interrupted result did not finish as a ClearCommError SerialException after unplug.'}
    if ([int]$session.observed_verified_frames -lt 2) {throw 'Final interrupted result lost the authenticated/decode frame evidence.'}
    foreach ($counter in @('auth_failures','invalid_authenticated_jpeg','replay_rejects','sequence_gaps','out_of_order','fragment_errors','dropped_frames')) {
        $prop=$session.observed_statistics.PSObject.Properties[$counter]
        if ($prop -and [int]$prop.Value -gt 0) {throw "Interrupted stream recorded $counter=$($prop.Value)."}
    }
    return [pscustomobject]@{kind=$kind;exit_utc=$exitAt;delta_seconds=$delta;result_status=$result.status;
        error_class=$result.error.class;error_message=$result.error.message;verified_frames=[int]$session.observed_verified_frames;
        statistics=$session.observed_statistics}
}
function Assert-DisconnectEvidence([bool]$AliveBeforePrompt,[string]$ExitKind,[double]$DeltaSeconds,[string]$ResultStatus,[string]$ErrorClass) {
    if (!$AliveBeforePrompt) {throw 'Receiver was not alive immediately before the unplug prompt.'}
    if ($ExitKind -ne 'serial_disconnect') {throw "Unplug did not produce the expected serial disconnect; observed $ExitKind."}
    if ($DeltaSeconds -lt -1.5 -or $DeltaSeconds -gt 2.0) {throw "Receiver exit is outside the stable PnP unplug window: ${DeltaSeconds}s."}
    if ($ResultStatus -eq 'running' -or $ErrorClass -ne 'SerialException') {throw 'Interrupted result is not finalized with a serial disconnect error.'}
}
function Get-MatchingBaseline($Identity) {
    $dirs=Get-ChildItem (Join-Path $root 'data/captures') -Directory -Filter 'g6_usb_*' -ErrorAction SilentlyContinue | Sort-Object CreationTimeUtc -Descending
    foreach ($dir in $dirs) {
        $path=Join-Path $dir.FullName 'result.json'; if (!(Test-Path -LiteralPath $path)) { continue }
        try { $j=Get-Content $path -Raw|ConvertFrom-Json } catch { continue }
        if ($j.status -eq 'passed' -and $j.jtag_completed -eq $true -and $j.build.manifest_sha256 -eq $Identity.manifest_sha256 -and
            $j.build.elf_sha256 -eq $Identity.elf_sha256 -and $j.build.xsa_sha256 -eq $Identity.xsa_sha256 -and
            $j.sessions.Count -gt 0 -and $j.sessions[0].frames -ge 2) { return $path }
    }
    return $null
}
function Get-NewSessionRecord($ResultPath,[uint32]$SessionId,[datetime]$Deadline) {
    while ([DateTime]::UtcNow -lt $Deadline) {
        if (Test-Path -LiteralPath $ResultPath) {
            try {
                $j=Get-Content -LiteralPath $ResultPath -Raw|ConvertFrom-Json
                foreach ($s in @($j.sessions)) { if ([string]$s.session_id -ceq [string]$SessionId) { return [pscustomobject]@{result=$j;session=$s} } }
            } catch {}
        }
        Start-Sleep -Milliseconds 100
    }
    return $null
}
function Get-ValidatedPassedRecords([string]$Directory,[object]$Identity,[int]$Required,[bool]$MockMode) {
    $passed=@{}
    foreach ($file in Get-ChildItem -LiteralPath $Directory -Filter 'trial_*_try*.json' -ErrorAction SilentlyContinue) {
        if ($file.BaseName -notmatch '^trial_(\d+)_try(\d+)$') { continue }
        $nameTrial=[int]$Matches[1];$nameTry=[int]$Matches[2]
        try { $r=Get-Content -LiteralPath $file.FullName -Raw|ConvertFrom-Json } catch { throw "Unreadable trial record: $($file.Name)" }
        if ([int]$r.trial -ne $nameTrial -or [int]$r.try -ne $nameTry) { throw "Trial JSON identity does not match filename: $($file.Name)" }
        if ($r.status -ne 'passed') { continue }
        if ($r.mock -ne $MockMode -or [int]$r.trial -lt 1 -or [int]$r.trial -gt $Required -or
            $r.build.elf_sha256 -ne $Identity.elf_sha256 -or $r.build.manifest_sha256 -ne $Identity.manifest_sha256 -or
            $r.build.xsa_sha256 -ne $Identity.xsa_sha256 -or $r.jtag_reload -ne $false -or
            (@($r.pnp_states) -join ',') -ne 'present,missing,present' -or $r.recovery_frames -lt 2 -or
            !$r.session_id_changed -or !$r.key_changed -or $r.recovery_key_fingerprint_sha256 -notmatch '^[0-9a-f]{64}$' -or
            $r.interrupted_key_fingerprint_sha256 -notmatch '^[0-9a-f]{64}$' -or
            !$r.receiver_alive_before_unplug -or $r.receiver_exit_kind -ne 'serial_disconnect' -or
            $r.receiver_exit_delta_from_missing_seconds -lt -1.5 -or $r.receiver_exit_delta_from_missing_seconds -gt 2.0 -or
            $r.interrupted_result_status_before_unplug -ne 'running' -or $r.interrupted_result_final_status -eq 'running' -or
            $r.interrupted_error_class -ne 'SerialException' -or $r.interrupted_verified_frames_final -lt 2) { throw "Passed trial record failed identity/evidence checks: $($file.Name)" }
        if ($MockMode -and ($r.recovery_session_id -eq $r.interrupted_session_id -or
            $r.recovery_key_fingerprint_sha256 -eq $r.interrupted_key_fingerprint_sha256)) { throw "Mock pass does not prove fresh session/key: $($file.Name)" }
        if ($passed.ContainsKey([int]$r.trial)) { throw "Duplicate passed trial number $($r.trial)." }
        $passed[[int]$r.trial]=$file.Name
    }
    for ($n=1;$n -le $passed.Count;$n++) { if (!$passed.ContainsKey($n)) { throw "Passed trial set is not a contiguous prefix 1..N; missing trial $n." } }
    return ,$passed
}
function Start-G6Process([string]$Out,[string]$Err,[int]$Seconds) {
    $args=@('-u','pc/src/host/g6_board.py','--workspace',$workspace,'--tool-root',$toolRoot,'--no-jtag',
        '--seconds',"$Seconds",'--wait-cdc',"$WaitTimeoutSeconds",'--sessions','1','--report-key-fingerprint')
    Start-Process -FilePath $python -ArgumentList ($args -join ' ') -WorkingDirectory $root `
        -RedirectStandardOutput $Out -RedirectStandardError $Err -PassThru -WindowStyle Hidden
}
function Wait-ReadyMarkers($Process,[string]$Out,[int]$Timeout) {
    $deadline=[DateTime]::UtcNow.AddSeconds($Timeout); $run=$null;$session=$null;$ready=$null
    while ([DateTime]::UtcNow -lt $deadline) {
        if (Test-Path $Out) {
            $lines=Get-Content -LiteralPath $Out -ErrorAction SilentlyContinue
            $run=$lines|Where-Object {$_ -match '^G6_RUN_RESULT path='}|Select-Object -Last 1
            $session=$lines|Where-Object {$_ -match '^G6_SESSION_ESTABLISHED '}|Select-Object -Last 1
            $ready=$lines|Where-Object {$_ -match '^G6_STREAM_READY '}|Select-Object -Last 1
        }
        if ($run -and $session -and $ready) { return [pscustomobject]@{run=$run;session=$session;ready=$ready} }
        if ($Process.HasExited) { throw "G6 receiver exited before stream-ready (exit=$($Process.ExitCode))." }
        Start-Sleep -Milliseconds 200
    }
    throw 'Timed out waiting for fresh authenticated/decode-ready G6 video.'
}
function Get-SessionData($Markers,[object]$Identity) {
    if ($Markers.session -notmatch 'session_id=(\d+).*video_key_sha256=([0-9a-f]{64})') { throw 'G6 session marker is malformed.' }
    if ($Markers.ready -notmatch 'frames=(\d+)') { throw 'G6 stream marker lacks the frame count.' }
    # Re-read the session match because PowerShell shares $Matches between regex calls.
    [void]($Markers.session -match 'session_id=(\d+).*video_key_sha256=([0-9a-f]{64})')
    $id=[uint32]$Matches[1]; $fp=$Matches[2]
    $path=($Markers.run -replace '^G6_RUN_RESULT path=','').Trim()
    $entry=Get-NewSessionRecord $path $id ([DateTime]::UtcNow.AddSeconds(5))
    if (!$entry) { throw "G6 partial result does not yet contain session ${id}: $path" }
    $j=$entry.result;$s=$entry.session
    if ($j.build.elf_sha256 -ne $Identity.elf_sha256 -or $j.build.manifest_sha256 -ne $Identity.manifest_sha256 -or
        $j.build.xsa_sha256 -ne $Identity.xsa_sha256 -or $j.parameters.jtag_load -ne $false) { throw 'G6 run build differs or JTAG was reloaded.' }
    if ([int]$s.observed_verified_frames -lt 2 -or !$s.video_key_sha256) { throw 'G6 result lacks two verified decoded frames or key fingerprint.' }
    foreach ($counter in @('auth_failures','invalid_authenticated_jpeg','replay_rejects','sequence_gaps','out_of_order','fragment_errors','dropped_frames')) {
        $prop=$s.observed_statistics.PSObject.Properties[$counter]
        if ($prop -and [int]$prop.Value -gt 0) { throw "Pre-fault G6 stream recorded $counter=$($prop.Value)." }
    }
    if ($s.video_key_sha256 -ne $fp) { throw 'G6 stdout and persisted session fingerprint differ.' }
    [pscustomobject]@{session_id=$id;key_fingerprint=$fp;verified_frames=[int]$s.observed_verified_frames;run_path=$path;capture_directory=$s.capture_directory;result_status=$j.status;statistics=$s.observed_statistics}
}

$identity=Get-BuildIdentity
if ($DryRun) { "G7_USB_UNPLUG_DRY_RUN_OK attempts=$Attempts states=present,missing,present stable_samples=2 jtag_reload_during_trials=false build=$($identity.elf_sha256)"; exit 0 }
if (!(Test-Path -LiteralPath $workspace)) { throw 'G6 workspace is missing.' }

if ($ResumeDirectory) {
    $runDir=[IO.Path]::GetFullPath($ResumeDirectory)
    if (!(Test-Path $runDir)) { throw 'Resume directory does not exist.' }
    $oldSummary=Get-Content (Join-Path $runDir 'batch_summary.json') -Raw|ConvertFrom-Json
    if ($oldSummary.schema -ne 'eyepqc-g7-usb-unplug-v1' -or $oldSummary.mode -ne 'UsbUnplug' -or
        $oldSummary.mock -ne [bool]$Mock -or $oldSummary.attempts_required -ne $Attempts -or
        $oldSummary.purpose -ne $(if($ReplacementForUnverified){'three_replacement_trials_for_original_08_14_18'}else{'full_twenty_trial_batch'}) -or
        $oldSummary.build.elf_sha256 -ne $identity.elf_sha256 -or $oldSummary.build.manifest_sha256 -ne $identity.manifest_sha256 -or
        $oldSummary.build.xsa_sha256 -ne $identity.xsa_sha256) { throw 'Resume summary mode/attempt count/build identity mismatch.' }
} else {
    $stamp=Get-Date -Format 'yyyyMMdd_HHmmss_fff';$suffix=[guid]::NewGuid().ToString('N').Substring(0,8)
    $leaf=if($Mock){"g7_batch_usb_mock_${stamp}_$suffix"}elseif($ReplacementForUnverified){"g7_batch_usb_unplug_replacement_${stamp}_$suffix"}else{"g7_batch_usb_unplug_${stamp}_$suffix"}
    $runDir=Join-Path $root "report/g7_runs/$leaf";New-Item -ItemType Directory -Path $runDir -Force|Out-Null
}

$baseline=$null
if ($Mock) {
    $baseline='MOCK_BASELINE'
} elseif ($ResumeDirectory) {
    $baseline=$oldSummary.baseline_result
    if (!(Test-Path -LiteralPath $baseline)) { throw 'Saved physical baseline result is missing.' }
    $b=Get-Content $baseline -Raw|ConvertFrom-Json
    if ($b.status -ne 'passed' -or $b.jtag_completed -ne $true -or $b.build.elf_sha256 -ne $identity.elf_sha256 -or
        $b.build.manifest_sha256 -ne $identity.manifest_sha256 -or $b.build.xsa_sha256 -ne $identity.xsa_sha256) { throw 'Saved baseline no longer matches this build.' }
} else {
    $baseline=Get-MatchingBaseline $identity
    if (!$baseline) { throw 'No matching JTAG-loaded baseline found. Use the existing approved -BaselineOnly path once before this batch.' }
}

if ($Mock) {
    $passedRecords=Get-ValidatedPassedRecords $runDir $identity $Attempts $true
    $passed=$passedRecords.Count
    if ($ResumeDirectory -and [int]$oldSummary.attempts_passed -ne $passed) { throw 'Resume summary passed count differs from valid trial records.' }
    for ($trial=$passed+1;$trial -le $Attempts;$trial++) {
        $prior=@(Get-ChildItem $runDir -Filter ('trial_{0:d2}_try*.json' -f $trial) -ErrorAction SilentlyContinue)
        $tryNumber=$prior.Count+1;$casePath=Join-Path $runDir ('trial_{0:d2}_try{1:d2}.json' -f $trial,$tryNumber)
        $states=if($MockScenario -eq 'Ambiguous'){@('present','ambiguous')}elseif($MockScenario -eq 'Timeout'){@('present','present','present')}else{@('present','missing','present')}
        $case=[ordered]@{trial=$trial;try=$tryNumber;mock=$true;status='running';stage='streaming';build=$identity;pnp_states=@('present');worker_started=$true;jtag_reload=$false}
        if ($MockScenario -eq 'Cleanup') {
            $case.status='failed';$case.stage_failed='injected_exception';$case.worker_cleanup_attempted=$true;$case.worker_cleaned=$true;$case.error='Injected failure exercised owned receiver cleanup.'
            Write-JsonAtomic $casePath $case;Write-Summary $runDir $identity 'failed' $baseline $passed $true
            throw 'G7_USB_UNPLUG_MOCK_FAIL_STOP cleanup path exercised.'
        }
        try {
            Assert-MockTransition @('present','present') 'present'
            if ($MockScenario -eq 'Ambiguous') { Assert-MockTransition @('present','ambiguous') 'missing' }
            elseif ($MockScenario -eq 'Timeout') { Assert-MockTransition @('present','present','present') 'missing' }
            else {
                Assert-MockTransition @('present','missing','missing') 'missing'
                Assert-MockTransition @('missing','present','present') 'present'
            }
        } catch {
            $case.status='failed';$case.stage_failed=if($MockScenario -eq 'Ambiguous'){'remove_observation'}else{'remove_timeout'}
            $case.pnp_states=$states;$case.error=$_.Exception.Message;$case.worker_cleanup_attempted=$true;$case.worker_cleaned=$true
            Write-JsonAtomic $casePath $case;Write-Summary $runDir $identity 'failed' $baseline $passed $true
            throw "G7_USB_UNPLUG_MOCK_FAIL_STOP PnP transition rejected: $($case.error)"
        }
        if ($MockScenario -eq 'PrePromptExit') {
            $case.status='failed';$case.stage_failed='pre_unplug_worker_liveness';$case.receiver_alive_before_unplug=$false
            $case.worker_cleanup_attempted=$true;$case.worker_cleaned=$true;$case.error='Injected receiver exit before unplug prompt.'
            Write-JsonAtomic $casePath $case;Write-Summary $runDir $identity 'failed' $baseline $passed $true
            throw 'G7_USB_UNPLUG_MOCK_FAIL_STOP receiver must be alive before unplug prompt.'
        }
        $exitKind=if($MockScenario -eq 'AtomicFailure'){'atomic_result_replace'}else{'serial_disconnect'}
        $exitDelta=if($MockScenario -eq 'SerialTimingMismatch' -or $MockScenario -eq 'AtomicFailure'){-2.6}else{-0.35}
        $resultStatus=if($MockScenario -eq 'ResultStillRunning' -or $MockScenario -eq 'AtomicFailure'){'running'}else{'failed'}
        $errorClass=if($resultStatus -eq 'running'){$null}else{'SerialException'}
        try {Assert-DisconnectEvidence $true $exitKind $exitDelta $resultStatus $errorClass}
        catch {
            $case.status='failed';$case.stage_failed='receiver_disconnect_evidence';$case.pnp_states=$states
            $case.receiver_alive_before_unplug=$true;$case.receiver_exit_kind=$exitKind;$case.receiver_exit_delta_from_missing_seconds=$exitDelta
            $case.interrupted_result_final_status=$resultStatus;$case.interrupted_error_class=$errorClass
            $case.worker_cleanup_attempted=$true;$case.worker_cleaned=$true;$case.error=$_.Exception.Message
            Write-JsonAtomic $casePath $case;Write-Summary $runDir $identity 'failed' $baseline $passed $true
            throw "G7_USB_UNPLUG_MOCK_FAIL_STOP disconnect evidence rejected: $($case.error)"
        }
        if ($MockFailAt -eq $trial) {
            $case.status='failed';$case.stage_failed='recovery';$case.pnp_states=$states;$case.error='Injected failure after complete physical-state sequence.'
            Write-JsonAtomic $casePath $case;Write-Summary $runDir $identity 'failed' $baseline $passed $true
            throw 'G7_USB_UNPLUG_MOCK_FAIL_STOP injected recovery failure.'
        }
        $sidA=[uint32](Get-Random -Minimum 1 -Maximum 2147483647);$sidB=[uint32](Get-Random -Minimum 1 -Maximum 2147483647)
        $fpA=Get-Fingerprint ([guid]::NewGuid().ToString());$fpB=Get-Fingerprint ([guid]::NewGuid().ToString())
        $case.status='passed';$case.stage='complete';$case.pnp_states=$states;$case.interrupted_session_id=$sidA;$case.interrupted_key_fingerprint_sha256=$fpA
        $case.receiver_alive_before_unplug=$true;$case.receiver_exit_kind=$exitKind;$case.receiver_exit_delta_from_missing_seconds=$exitDelta
        $case.interrupted_result_status_before_unplug='running';$case.interrupted_result_final_status=$resultStatus
        $case.interrupted_error_class=$errorClass;$case.interrupted_verified_frames=2;$case.interrupted_verified_frames_final=2
        $case.recovery_session_id=$sidB;$case.recovery_key_fingerprint_sha256=$fpB
        $case.recovery_frames=2;$case.session_id_changed=$true;$case.key_changed=$true;$case.worker_cleanup_attempted=$true;$case.worker_cleaned=$true
        Write-JsonAtomic $casePath $case;$passed++
        Write-Summary $runDir $identity 'running' $baseline $passed $true
    }
    Write-Summary $runDir $identity 'mock_complete' $baseline $passed $true
    "G7_USB_UNPLUG_MOCK_OK attempts=$passed evidence=$runDir";exit 0
}

$savedPath=$env:PATH;$savedTool=$env:EYEPQC_TOOL_ROOT;$worker=$null;$recovery=$null;$activeCase=$null;$activeCasePath=$null;$activeCsv=$null
$transcriptStarted=$false
try {
    Start-Transcript -LiteralPath (Join-Path $runDir 'operator_console.txt') -Force|Out-Null
    $transcriptStarted=$true
    $env:EYEPQC_TOOL_ROOT=$toolRoot
    if (Test-Path 'C:/msys64/ucrt64/bin') {$env:PATH='C:/msys64/ucrt64/bin;'+$env:PATH}
    & $python 'pc/src/host/g6_board.py' --workspace $workspace --tool-root $toolRoot --verify-only
    if ($LASTEXITCODE -ne 0) {throw 'G6 host/build preflight failed.'}
    $selfPid=$PID
    $selfProcess=Get-CimInstance Win32_Process -Filter "ProcessId=$selfPid" -ErrorAction SilentlyContinue
    $launcherPid=if($selfProcess){[int]$selfProcess.ParentProcessId}else{-1}
    $processes=@(Get-CimInstance Win32_Process|Where-Object {
        $_.ProcessId -ne $selfPid -and
        -not ($_.ProcessId -eq $launcherPid -and $_.CommandLine -match 'run_g7_usb_unplug\.ps1') -and
        $_.CommandLine -match 'demo_window\.py|demo_controller\.py|g6_board\.py|run_g7_batch\.ps1|run_g7_usb_unplug\.ps1'
    })
    $busy=@($processes|Where-Object {Test-UsbBatchProcessActive $_})
    if ($busy.Count) {throw "A G6/demo process already owns or may own the CDC port: $($busy.ProcessId -join ',')."}
    $initial=Get-DeviceState
    if ($initial.state -ne 'present') {throw "USB CDC must be one present device before each trial; current state=$($initial.state)."}

    $passedRecords=Get-ValidatedPassedRecords $runDir $identity $Attempts $false
    $passed=$passedRecords.Count
    if ($ResumeDirectory -and [int]$oldSummary.attempts_passed -ne $passed) { throw 'Resume summary passed count differs from valid trial records.' }
    if ($passed -ge $Attempts) {throw "This batch already has $passed successful trials."}
    Write-Summary $runDir $identity 'awaiting_operator' $baseline $passed $false
    $purposeLabel=if($ReplacementForUnverified){'替补补测（仅补原批次8/14/18的三轮）'}else{'正式USB拔插批次'}
    Write-Host "G7_USB_UNPLUG_READY batch=$runDir attempts=$Attempts purpose=$purposeLabel device=COM16 VID_03FD&PID_7020" -ForegroundColor Cyan
    Write-Host "本窗口用途：$purposeLabel。请先确认现场说明已收到。全程只拔插电脑端的USB Slave数据线，板端接头、JTAG线和电源保持不动。每轮请等脚本显示提示后再拔/插；不要提前操作。" -ForegroundColor Yellow
    [void](Read-Host '准备好开始本窗口现场测试后按 Enter；现在取消请按 Ctrl+C')
    Write-Summary $runDir $identity 'running' $baseline $passed $false

    while ($passed -lt $Attempts) {
        $trial=$passed+1;$prior=@(Get-ChildItem $runDir -Filter ('trial_{0:d2}_try*.json' -f $trial) -ErrorAction SilentlyContinue)
        $tryNumber=$prior.Count+1;$stem=('trial_{0:d2}_try{1:d2}' -f $trial,$tryNumber)
        $activeCasePath=Join-Path $runDir ($stem+'.json');$activeCsv=Join-Path $runDir ($stem+'_pnp.csv')
        "utc,state,count,instance"|Set-Content -LiteralPath $activeCsv -Encoding utf8
            $activeCase=[ordered]@{trial=$trial;try=$tryNumber;mock=$false;status='running';stage='start_g6_receiver';batch_purpose=$purposeLabel;build=$identity;baseline_result=$baseline;jtag_reload=$false;pnp_log=$activeCsv;started_utc=[DateTime]::UtcNow.ToString('o')}
        Write-JsonAtomic $activeCasePath $activeCase
        $out=Join-Path $runDir ($stem+'_receiver.stdout.log');$err=Join-Path $runDir ($stem+'_receiver.stderr.log')
        try {
            $worker=Start-G6Process $out $err $FaultSeconds
            $markers=Wait-ReadyMarkers $worker $out ($WaitTimeoutSeconds+90)
            $live=Get-SessionData $markers $identity
            $activeCase.stage='live_authenticated_video';$activeCase.interrupted_session_id=$live.session_id
            $activeCase.interrupted_key_fingerprint_sha256=$live.key_fingerprint;$activeCase.interrupted_verified_frames=$live.verified_frames
            $activeCase.interrupted_result=$live.run_path;$activeCase.interrupted_capture_directory=$live.capture_directory
            Write-JsonAtomic $activeCasePath $activeCase
            $startState=Get-DeviceState;Add-Observation $activeCsv $startState
            if ($startState.state -ne 'present') {throw 'Expected exactly one present G6 USB device before unplug prompt.'}
            $worker.Refresh()
            if ($worker.HasExited) {throw 'Receiver exited after stream readiness but before the unplug prompt.'}
            if ($live.result_status -ne 'running') {throw "Receiver result is not active before unplug (status=$($live.result_status))."}
            $activeCase.receiver_alive_before_unplug=$true;$activeCase.receiver_live_confirmed_utc=[DateTime]::UtcNow.ToString('o')
            $activeCase.interrupted_result_status_before_unplug=$live.result_status
            $activeCase.interrupted_statistics_before_unplug=$live.statistics
            $activeCase.unplug_prompt_utc=[DateTime]::UtcNow.ToString('o');Write-JsonAtomic $activeCasePath $activeCase
            $trialLabel=if($ReplacementForUnverified){'G7 USB拔插替补补测'}else{'G7 USB拔插验收'}
            Write-Host "$trialLabel $trial/$Attempts：当前会话已有$($live.verified_frames)帧认证并解码。请拔下USB Slave数据线并保持拔出；脚本将等待PnP连续两次确认missing（最多${WaitTimeoutSeconds}秒）。" -ForegroundColor Yellow
            $activeCase.stage='wait_for_usb_removal';Write-JsonAtomic $activeCasePath $activeCase
            $removed=Wait-StableDevice 'missing' $activeCsv $WaitTimeoutSeconds
            $activeCase.pnp_missing_first_utc=$removed.first_observation_utc.ToString('o')
            $activeCase.pnp_missing_confirmed_utc=$removed.confirmed_utc.ToString('o');$activeCase.pnp_states=@('present','missing')
            $disconnect=Confirm-ExpectedDisconnect $worker $err $live.run_path $live.session_id $removed.first_observation_utc
            Assert-DisconnectEvidence $true $disconnect.kind $disconnect.delta_seconds $disconnect.result_status $disconnect.error_class
            $activeCase.receiver_exit_kind=$disconnect.kind;$activeCase.receiver_exit_utc=$disconnect.exit_utc.ToString('o')
            $activeCase.receiver_exit_delta_from_missing_seconds=[Math]::Round($disconnect.delta_seconds,3)
            $activeCase.interrupted_result_final_status=$disconnect.result_status;$activeCase.interrupted_error_class=$disconnect.error_class
            $activeCase.interrupted_error_message=$disconnect.error_message
            $activeCase.interrupted_verified_frames_final=$disconnect.verified_frames;$activeCase.interrupted_statistics_final=$disconnect.statistics
            Write-JsonAtomic $activeCasePath $activeCase
        $activeCase.stage='wait_for_usb_reinsert';Write-JsonAtomic $activeCasePath $activeCase
            Write-Host "已确认USB Slave设备移除。请插回同一根USB数据线；脚本将等待唯一设备连续两次重新枚举（最多${WaitTimeoutSeconds}秒）。" -ForegroundColor Yellow
            $inserted=Wait-StableDevice 'present' $activeCsv $WaitTimeoutSeconds
            $activeCase.pnp_present_first_utc=$inserted.first_observation_utc.ToString('o')
            $activeCase.pnp_present_confirmed_utc=$inserted.confirmed_utc.ToString('o');$activeCase.pnp_states=@('present','missing','present')
            $activeCase.stage='close_old_receiver';Write-JsonAtomic $activeCasePath $activeCase
            $workerExited=$worker.HasExited
            if (!$workerExited) {Stop-Process -Id $worker.Id -Force -ErrorAction SilentlyContinue;$worker.WaitForExit()}
            $activeCase.old_receiver_exited=$workerExited;$activeCase.old_receiver_cleanup_killed=(!$workerExited);$activeCase.worker_cleanup_attempted=$true
            $worker=$null;Write-JsonAtomic $activeCasePath $activeCase

            $recOut=Join-Path $runDir ($stem+'_recovery.stdout.log');$recErr=Join-Path $runDir ($stem+'_recovery.stderr.log')
            $recovery=Start-G6Process $recOut $recErr $RecoverySeconds
            if (!$recovery.WaitForExit(($RecoverySeconds+$WaitTimeoutSeconds+60)*1000)) {Stop-Process -Id $recovery.Id -Force -ErrorAction SilentlyContinue;throw 'Fresh-handshake recovery exceeded bounded wait.'}
            if ($recovery.ExitCode -ne 0) {throw "Fresh-handshake recovery failed (exit=$($recovery.ExitCode)); inspect $recErr."}
            $recovery=$null
            $runLine=Get-Content $recOut|Where-Object {$_ -match '^G6_RUN_RESULT path='}|Select-Object -Last 1
            $sessionLine=Get-Content $recOut|Where-Object {$_ -match '^G6_SESSION_ESTABLISHED '}|Select-Object -Last 1
            if (!$runLine -or !$sessionLine) {throw 'Recovery output lacks run/session markers.'}
            $runPath=($runLine -replace '^G6_RUN_RESULT path=','').Trim()
            if ($sessionLine -notmatch 'session_id=(\d+).*video_key_sha256=([0-9a-f]{64})') {throw 'Recovery session marker malformed.'}
            $newId=[uint32]$Matches[1];$newFp=$Matches[2]
            $fresh=Get-Content $runPath -Raw|ConvertFrom-Json
            if ($fresh.status -ne 'passed' -or $fresh.parameters.jtag_load -ne $false -or $fresh.build.elf_sha256 -ne $identity.elf_sha256 -or
                $fresh.build.manifest_sha256 -ne $identity.manifest_sha256 -or $fresh.build.xsa_sha256 -ne $identity.xsa_sha256 -or $fresh.sessions.Count -ne 1) {throw 'Recovery result status/build/JTAG state mismatch.'}
            $session=$fresh.sessions[0]
            if ($session.frames -lt 2 -or $session.session_id -ne $newId -or $session.video_key_sha256 -ne $newFp -or
                $newId -eq $live.session_id -or $newFp -eq $live.key_fingerprint) {throw 'Recovery did not prove a fresh session/key and at least two authenticated frames.'}
            $bad=@('auth_failures','replay_rejects','sequence_gaps','out_of_order','fragment_errors','invalid_authenticated_jpeg','malformed_video','invalid_session_or_header','dropped_frames')|Where-Object {[int]$session.errors.$_ -gt 0}
            if ($bad.Count -or $session.packets -ne $session.errors.authenticated_packets) {throw "Recovery stream integrity errors: $($bad -join ',')."}
            $activeCase.status='passed';$activeCase.stage='complete';$activeCase.recovery_result=$runPath;$activeCase.recovery_session_id=$newId
            $activeCase.recovery_key_fingerprint_sha256=$newFp;$activeCase.session_id_changed=$true;$activeCase.key_changed=$true
            $activeCase.recovery_frames=$session.frames;$activeCase.recovery_fps=$session.fps;$activeCase.recovery_packets=$session.packets
            $activeCase.recovery_errors=$session.errors;$activeCase.recovery_first_jpeg=Join-Path $session.output 'first.jpg';$activeCase.recovery_last_jpeg=Join-Path $session.output 'last.jpg'
            $activeCase.completed_utc=[DateTime]::UtcNow.ToString('o');Write-JsonAtomic $activeCasePath $activeCase
            $passed++;Write-Summary $runDir $identity 'running' $baseline $passed $false
            Write-Host "G7_USB_UNPLUG_PASS $passed/${Attempts}: $($live.session_id) -> $newId, $($session.frames)认证帧, $([Math]::Round($session.fps,3))fps" -ForegroundColor Green
        } catch {
            if ($worker -and !$worker.HasExited) {Stop-Process -Id $worker.Id -Force -ErrorAction SilentlyContinue}
            if ($recovery -and !$recovery.HasExited) {Stop-Process -Id $recovery.Id -Force -ErrorAction SilentlyContinue}
            $worker=$null;$recovery=$null;$activeCase.status='failed';$activeCase.stage_failed=$activeCase.stage;$activeCase.error=$_.Exception.Message
            $activeCase.failed_utc=[DateTime]::UtcNow.ToString('o');$activeCase.worker_cleanup_attempted=$true
            Write-JsonAtomic $activeCasePath $activeCase;Write-Summary $runDir $identity 'failed' $baseline $passed $false
            Write-Host "G7_USB_UNPLUG_FAILED trial=$trial; evidence=$activeCasePath" -ForegroundColor Red
            if ((Get-DeviceState).state -eq 'missing') {Write-Host '本轮失败且 USB CDC 仍未枚举；请插回 USB Slave 数据线并保持连接，本轮不计通过。' -ForegroundColor Yellow}
            throw
        }
    }
    Write-Summary $runDir $identity 'passed' $baseline $passed $false
    "G7_USB_UNPLUG_BATCH_OK attempts=$passed evidence=$runDir"
} finally {
    if ($worker -and !$worker.HasExited) {Stop-Process -Id $worker.Id -Force -ErrorAction SilentlyContinue}
    if ($recovery -and !$recovery.HasExited) {Stop-Process -Id $recovery.Id -Force -ErrorAction SilentlyContinue}
    if ($transcriptStarted) {Stop-Transcript|Out-Null}
    $env:PATH=$savedPath;$env:EYEPQC_TOOL_ROOT=$savedTool
}
