param(
    [string]$Workspace = 'build/vitis/usbfix3_20261007',
    [string]$ToolRoot = $(if ($env:EYEPQC_TOOL_ROOT) { $env:EYEPQC_TOOL_ROOT } else { 'E:/fpg/2026.1' }),
    [int]$Seconds = 10,
    [int]$WaitTimeoutSeconds = 120,
    [switch]$Reload,
    [switch]$BaselineOnly,
    [switch]$ConnectionCheckOnly,
    [switch]$CheckOnly,
    [switch]$Help
)
$ErrorActionPreference = 'Stop'
if ($Help) {
    Get-Help $PSCommandPath -Detailed
    exit 0
}
$root = $PSScriptRoot
$savedPath = $env:PATH
$savedTools = $env:EYEPQC_TOOL_ROOT
$python = Join-Path $root '.venv/Scripts/python.exe'
$workspacePath = [IO.Path]::GetFullPath((Join-Path $root $Workspace))
$toolPath = [IO.Path]::GetFullPath($ToolRoot)
if (!(Test-Path -LiteralPath $python)) { throw 'G7_NOT_RUN: project Python environment is missing.' }
if (!(Test-Path -LiteralPath $workspacePath)) { throw "G7_NOT_RUN: firmware workspace is missing: $workspacePath" }
if ($Seconds -lt 2 -or $WaitTimeoutSeconds -lt 10) { throw 'Seconds must be >=2 and WaitTimeoutSeconds >=10.' }
$worker = $watcher = $baseline = $usbLog = $null
$stage = 'preflight'
Push-Location $root
try {
    $env:EYEPQC_TOOL_ROOT = $toolPath
    if (Test-Path -LiteralPath 'C:/msys64/ucrt64/bin') { $env:PATH = 'C:/msys64/ucrt64/bin;' + $env:PATH }
    & $python board/prj/verify_software.py $workspacePath
    if ($LASTEXITCODE -ne 0) { throw 'G7_NOT_RUN: software preflight failed.' }
    if ($CheckOnly) {
        'G7_PROMPT_PREFLIGHT_OK board_accessed=false physical_action=false'
        exit 0
    }

    function Get-G6Device {
        @(Get-PnpDevice -PresentOnly -ErrorAction SilentlyContinue |
            Where-Object { $_.InstanceId -match 'VID_03FD&PID_7020' })
    }
    function Get-ReusableG6Run {
        # Reuse only the most recent recorded G6 JTAG load, with matching build
        # hashes and a completed video interval. A failed rekey may follow it.
        $manifestHash = (Get-FileHash -LiteralPath (Join-Path $workspacePath 'g6_usb_manifest.json') -Algorithm SHA256).Hash.ToLowerInvariant()
        $elfHash = (Get-FileHash -LiteralPath (Join-Path $workspacePath 'g6_usb/build/g6_usb.elf') -Algorithm SHA256).Hash.ToLowerInvariant()
        $manifest = Get-Content -LiteralPath (Join-Path $workspacePath 'g6_usb_manifest.json') -Raw | ConvertFrom-Json
        $runs = Get-ChildItem (Join-Path $root 'data/captures') -Directory -Filter 'g6_usb_*' |
            Sort-Object CreationTimeUtc -Descending
        foreach ($run in $runs) {
            $file = Join-Path $run.FullName 'result.json'
            if (!(Test-Path -LiteralPath $file)) { continue }
            try { $json = Get-Content -LiteralPath $file -Raw | ConvertFrom-Json } catch { continue }
            if (!$json.jtag_completed) { continue }
            $validFrames = @($json.sessions | Where-Object { $_.frames -ge 2 })
            if ($json.parameters.jtag_load -and $validFrames.Count -gt 0 -and
                $json.build.manifest_sha256 -eq $manifestHash -and
                $json.build.elf_sha256 -eq $elfHash -and
                $json.build.xsa_sha256 -eq $manifest.xsa_sha256) {
                return @{ result_path = $file
                          result_sha256 = (Get-FileHash -LiteralPath $file -Algorithm SHA256).Hash.ToLowerInvariant()
                          prior_status = $json.status
                          basis = 'prior_matching_jtag_load_and_completed_video; live firmware memory was not read back' }
            }
            return $null
        }
        return $null
    }
    function Wait-Enter([string]$Prompt, [int]$Timeout) {
        while ([Console]::KeyAvailable) { [void][Console]::ReadKey($true) }
        Write-Host $Prompt -ForegroundColor Yellow
        Write-Host "完成后按 Enter 继续（最多等待 $Timeout 秒）。"
        $until = [DateTime]::UtcNow.AddSeconds($Timeout)
        while ([DateTime]::UtcNow -lt $until) {
            if ([Console]::KeyAvailable) {
                $key = [Console]::ReadKey($true)
                if ($key.Key -eq [ConsoleKey]::Enter) { return $true }
            }
            Start-Sleep -Milliseconds 200
        }
        return $false
    }
    function Wait-UsbObservation($Job, [string]$Path, [int]$Timeout,
                                 [ValidateSet('present','missing')][string]$State = 'present',
                                 [switch]$AfterRemoval) {
        $until = [DateTime]::UtcNow.AddSeconds($Timeout)
        while ([DateTime]::UtcNow -lt $until) {
            if ($Job.State -eq 'Failed') { throw 'G7_INCOMPLETE: USB observation job failed.' }
            if (Test-Path -LiteralPath $Path) {
                $rows = @(Import-Csv -LiteralPath $Path -Delimiter "`t")
                if ($rows.Count -and $rows[-1].presence -eq $State -and
                    (!$AfterRemoval -or @($rows | Where-Object presence -eq 'missing').Count -gt 0)) {
                    return
                }
            }
            Start-Sleep -Milliseconds 200
        }
        throw 'G7_INCOMPLETE: USB observation did not confirm the required connection state.'
    }
    function Get-LatestRun([DateTime]$After) {
        Get-ChildItem (Join-Path $root 'data/captures') -Directory -Filter 'g6_usb_*' -ErrorAction SilentlyContinue |
            Where-Object { $_.CreationTimeUtc -ge $After } | Sort-Object CreationTimeUtc -Descending |
            ForEach-Object { $candidate = Join-Path $_.FullName 'result.json'; if (Test-Path $candidate) { Get-Item $candidate } } |
            Select-Object -First 1
    }
    function Invoke-G6Fresh([string]$Label, [switch]$LoadFirmware) {
        $started = [DateTime]::UtcNow
        $nativeArgs = @('pc/src/host/g6_board.py','--workspace',$workspacePath,'--tool-root',$toolPath,
                        '--sessions','1','--seconds',"$Seconds",'--wait-cdc',"$WaitTimeoutSeconds")
        if ($Label -eq 'baseline') { $nativeArgs += '--fault-check' }
        if (!$LoadFirmware) { $nativeArgs += '--no-jtag' }
        & $python @nativeArgs | Out-Host
        $exit = $LASTEXITCODE
        $file = Get-LatestRun $started
        if ($exit -ne 0 -or !$file) { throw "G7_RECOVERY_FAILED ($Label): G6 process exit=$exit; inspect latest result.json." }
        $json = Get-Content -LiteralPath $file.FullName -Raw | ConvertFrom-Json
        if ($json.status -ne 'passed' -or !$json.sessions -or $json.sessions[0].frames -lt 2) {
            throw "G7_RECOVERY_FAILED ($Label): fewer than two authenticated complete frames."
        }
        return @{ result = $json; path = $file.FullName }
    }
    function Start-G6Worker([string]$Label) {
        $started = [DateTime]::UtcNow
        $logDir = Join-Path $root 'report/g7_runs'
        New-Item -ItemType Directory -Path $logDir -Force | Out-Null
        $stamp = Get-Date -Format 'yyyyMMdd_HHmmss_fff'
        $stdout = Join-Path $logDir "$Label`_$stamp.stdout.log"
        $stderr = Join-Path $logDir "$Label`_$stamp.stderr.log"
        $args = @('pc/src/host/g6_board.py','--workspace',$workspacePath,'--tool-root',$toolPath,
                  '--no-jtag','--sessions','1','--seconds','600','--wait-cdc',"$WaitTimeoutSeconds")
        $p = Start-Process -FilePath $python -ArgumentList $args -WorkingDirectory $root `
            -PassThru -WindowStyle Hidden -RedirectStandardOutput $stdout -RedirectStandardError $stderr
        return @{ process = $p; started = $started; stdout = $stdout; stderr = $stderr }
    }
    function Wait-G6Stream($worker, [int]$Timeout) {
        $until = [DateTime]::UtcNow.AddSeconds($Timeout)
        while ([DateTime]::UtcNow -lt $until) {
            if ($worker.process.HasExited) { throw "G7_NOT_READY: receiver exited before authenticated video marker; see $($worker.stderr)" }
            if (Test-Path -LiteralPath $worker.stdout) {
                $match = Select-String -LiteralPath $worker.stdout -Pattern 'G6_STREAM_READY session_id=(\d+) frames=(\d+)' |
                    Select-Object -Last 1
                if ($match) {
                    if ($worker.process.HasExited) { throw 'G7_NOT_READY: receiver exited immediately after stream marker.' }
                    return @{ session_id = [uint32]$match.Matches[0].Groups[1].Value
                              frames = [int]$match.Matches[0].Groups[2].Value }
                }
            }
            Start-Sleep -Milliseconds 200
        }
        throw "G7_NOT_READY: no authenticated video marker within $Timeout seconds; see $($worker.stderr)"
    }
    function Stop-G6Worker($worker, [string]$Label) {
        $killed = !$worker.process.HasExited
        if ($killed) {
            Stop-Process -Id $worker.process.Id -Force
            $worker.process.WaitForExit()
        }
        $partial = Get-LatestRun $worker.started
        if ($partial) {
            $obj = Get-Content -LiteralPath $partial.FullName -Raw | ConvertFrom-Json
            if ($killed -and $obj.status -eq 'running') { $obj.status = 'operator_interruption' }
            $obj | Add-Member -MemberType NoteProperty -Name interruption -Value $Label -Force
            $obj | Add-Member -MemberType NoteProperty -Name operator_killed -Value $killed -Force
            $obj | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $partial.FullName -Encoding utf8
        }
        return $killed
    }

    $worker = $null
    $watcher = $null
    $stage = 'baseline'
    Write-Host 'G7 第三阶段：仅执行一次 USB 物理拔插和一次接收进程异常退出；不执行摄像头热拔插。' -ForegroundColor Cyan
    $reuseEvidence = $null
    $currentDevices = @(Get-G6Device)
    Write-Host "G7_DEVICE_CHECK matches=$($currentDevices.Count) reload=$Reload"
    if (!$Reload -and $currentDevices.Count -eq 1) { $reuseEvidence = Get-ReusableG6Run }
    if ($ConnectionCheckOnly) {
        Write-Host "G7_CONNECTION_CHECK_OK reuse_available=$([bool]$reuseEvidence) firmware_loaded=false"
        return
    }
    if ($reuseEvidence) {
        Write-Host 'G7_REUSE_G6：已识别视频设备，复用最近一次相同构建且已出图的 G6，不重新下载。'
    } else {
        Write-Host '先临时下载本次验证固件并完成认证视频基线；下载后等待 USB 枚举，等待本身不表示数据线未连接。'
    }
    $baseline = Invoke-G6Fresh 'baseline' -LoadFirmware:(!$reuseEvidence)
    $baseline.result | Add-Member NoteProperty g7_firmware_reloaded (!$reuseEvidence) -Force
    $baseline.result | Add-Member NoteProperty g7_reused_load_evidence $reuseEvidence -Force
    $baseline.result | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $baseline.path -Encoding utf8
    Write-Host "G7_BASELINE_OK result=$($baseline.path)"
    if ($BaselineOnly) {
        Write-Host 'G7_BASELINE_ONLY_OK physical_action=false'
        return
    }

    $logDir = Join-Path $root 'report/g7_runs'
    New-Item -ItemType Directory -Path $logDir -Force | Out-Null
    $usbLog = Join-Path $logDir ('usb_pnp_' + (Get-Date -Format 'yyyyMMdd_HHmmss_fff') + '.csv')
    $watcher = Start-Job -ArgumentList $usbLog -ScriptBlock {
        param($path)
        Add-Content -LiteralPath $path -Value "utc`tpresence`tcount"
        while ($true) {
            try {
                $items = @(Get-PnpDevice -PresentOnly -ErrorAction Stop |
                    Where-Object { $_.InstanceId -match 'VID_03FD&PID_7020' })
                $presence = if ($items.Count -eq 1) { 'present' } elseif (!$items.Count) { 'missing' } else { 'ambiguous' }
                $count = $items.Count
            } catch {
                $presence = 'error'
                $count = -1
            }
            Add-Content -LiteralPath $path -Value ("{0:o}`t{1}`t{2}" -f [DateTime]::UtcNow,$presence,$count)
            Start-Sleep -Milliseconds 200
        }
    }
    $worker = Start-G6Worker 'usb_unplug'
    $usbWorkerSession = Wait-G6Stream $worker $WaitTimeoutSeconds
    Wait-UsbObservation $watcher $usbLog $WaitTimeoutSeconds
    $stage = 'usb_remove'
    Write-Host '操作 1a：现在拔下 USB Slave 数据线，保持拔出；检测到拔出后才会提示插回。' -ForegroundColor Yellow
    Wait-UsbObservation $watcher $usbLog $WaitTimeoutSeconds -State missing
    $stage = 'usb_reinsert'
    Write-Host 'USB 拔出已确认。操作 1b：现在插回同一根数据线，等待自动检测；无需按 Enter。' -ForegroundColor Yellow
    Wait-UsbObservation $watcher $usbLog $WaitTimeoutSeconds -AfterRemoval
    $usbWorkerKilled = Stop-G6Worker $worker 'USB unplug/replug test window ended; receiver stopped before fresh handshake.'
    $worker = $null
    $watcherState = $watcher.State
    Stop-Job $watcher -ErrorAction SilentlyContinue
    Remove-Job $watcher -Force -ErrorAction SilentlyContinue
    $watcher = $null
    $observations = @(Import-Csv -LiteralPath $usbLog -Delimiter "`t")
    $states = @($observations | ForEach-Object presence)
    $missingIndex = [Array]::IndexOf($states, 'missing')
    $sawRemoval = [bool]($watcherState -ne 'Failed' -and !$states.Contains('error') -and !$states.Contains('ambiguous') -and
                  $missingIndex -gt 0 -and ($states | Select-Object -Skip ($missingIndex + 1) |
                  Where-Object { $_ -eq 'present' } | Select-Object -First 1))
    if (@(Get-G6Device).Count -ne 1) { throw 'G7_INCOMPLETE: CDC 拔插后未重新枚举。' }
    $stage = 'usb_fresh_handshake'
    $usbRecovery = Invoke-G6Fresh 'after_usb_replug'
    $usbRecoveryId = $usbRecovery.result.sessions[0].session_id
    if ($usbRecoveryId -eq $usbWorkerSession.session_id) { throw 'G7_FAILED: session id was reused after USB recovery.' }
    $usbStatus = if ($sawRemoval) { 'passed' } else { 'unverified_removal_not_observed' }

    $worker = Start-G6Worker 'receiver_exit'
    $exitWorkerSession = Wait-G6Stream $worker $WaitTimeoutSeconds
    $stage = 'receiver_exit'
    $exitConfirmed = Wait-Enter '操作 2/2：按 Enter 让脚本强制结束本次 G6 接收子进程（模拟 PC 接收程序异常退出）。' $WaitTimeoutSeconds
    if (!$exitConfirmed) {
        Stop-G6Worker $worker 'receiver-exit confirmation timed out'
        $worker = $null
        throw 'G7_INCOMPLETE: 接收程序退出步骤等待超时，未记录为通过。'
    }
    $receiverKilled = Stop-G6Worker $worker 'operator-triggered abrupt receiver process termination'
    $worker = $null
    if (!$receiverKilled) { throw 'G7_FAILED: receiver process had already exited; abnormal-exit case not performed.' }
    $stage = 'receiver_fresh_handshake'
    $exitRecovery = Invoke-G6Fresh 'after_receiver_exit'
    if ($exitRecovery.result.sessions[0].session_id -eq $exitWorkerSession.session_id) {
        throw 'G7_FAILED: session id was reused after receiver process restart.'
    }
    $report = [ordered]@{
        generated_utc = [DateTime]::UtcNow.ToString('o')
        status = if ($usbStatus -eq 'passed') { 'passed' } else { 'incomplete' }
        software_preflight = 'passed'
        baseline_result = $baseline.path
        baseline_frames = $baseline.result.sessions[0].frames
        baseline_firmware_reloaded = !$reuseEvidence
        reused_load_evidence = $reuseEvidence
        usb_unplug_observed = $sawRemoval
        usb_reenumerated = $true
        usb_worker_killed_by_script_after_action = $usbWorkerKilled
        pnp_watcher_state = [string]$watcherState
        usb_recovery_result = $usbRecovery.path
        receiver_process_killed = $receiverKilled
        receiver_session_id = $exitWorkerSession.session_id
        usb_worker_session_id = $usbWorkerSession.session_id
        receiver_recovery_result = $exitRecovery.path
        board_counters = $null
        note = 'No keys are recorded. A fresh authenticated session and >=2 decoded frames are required after each interruption. Board-side counters are unsupported in this host-only runner.'
    }
    $summary = Join-Path $logDir 'g7_recovery_summary.json'
    $report | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $summary -Encoding utf8
    if ($report.status -ne 'passed') { throw "G7_INCOMPLETE: USB physical removal was not observed; summary=$summary" }
    Write-Host "G7_RECOVERY_OK summary=$summary"
} catch {
    $failureDir = Join-Path $root 'report/g7_runs'
    New-Item -ItemType Directory -Path $failureDir -Force | Out-Null
    $failurePath = Join-Path $failureDir ('g7_failure_' + (Get-Date -Format 'yyyyMMdd_HHmmss_fff') + '.json')
    [ordered]@{ status = 'failed'; stage = $stage; error = $_.Exception.Message
        workspace = $workspacePath; usb_observation_log = $usbLog
        baseline_result = $baseline.path; generated_utc = [DateTime]::UtcNow.ToString('o') } |
        ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $failurePath -Encoding utf8
    Write-Host "G7_FAILURE_RECORD $failurePath"
    throw
} finally {
    if ($watcher) {
        Stop-Job $watcher -ErrorAction SilentlyContinue
        Remove-Job $watcher -Force -ErrorAction SilentlyContinue
    }
    if ($worker) {
        try { [void](Stop-G6Worker $worker 'cleanup after interrupted G7 prompt') } catch {}
    }
    $env:PATH = $savedPath
    $env:EYEPQC_TOOL_ROOT = $savedTools
    Pop-Location
}
