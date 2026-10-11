param(
    [ValidateSet('Plan', 'Start', 'Stop', 'Status')]
    [string]$Action = 'Status'
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$sessionName = 'EYEPQCG7USB'
$maxTraceSeconds = 300
$maxTraceMegabytes = 128
$providerKeywords = '(Default,HeadersBusTrace,StateMachine,Rundown)'
$usbProviders = @(
    'Microsoft-Windows-USB-USBXHCI',
    'Microsoft-Windows-USB-UCX',
    'Microsoft-Windows-USB-USBHUB3'
)
$ioProvider = 'Microsoft-Windows-Kernel-IoTrace'
$repoRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$outputRootFull = [IO.Path]::GetFullPath((Join-Path $repoRoot 'build/g7_usb_etw'))
$pointerPath = Join-Path $outputRootFull 'active.json'
$logman = Join-Path $env:SystemRoot 'System32/logman.exe'

function Test-IsAdministrator {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = [Security.Principal.WindowsPrincipal]::new($identity)
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Invoke-Logman([string[]]$Arguments, [switch]$AllowFailure) {
    $output = @(& $script:logman @Arguments 2>&1 | ForEach-Object { [string]$_ })
    $code = $LASTEXITCODE
    if ($code -ne 0 -and !$AllowFailure) {
        $detail = $output -join [Environment]::NewLine
        throw "logman $($Arguments -join ' ') failed with exit code $code. $detail"
    }
    return [pscustomobject]@{ ExitCode = $code; Output = $output }
}

function Test-TraceActive {
    $result = Invoke-Logman @('query', '-n', $script:sessionName, '-ets') -AllowFailure
    return ($result.ExitCode -eq 0)
}

function Write-JsonAtomic([string]$Path, $Value) {
    $temporary = "$Path.tmp"
    $Value | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $temporary -Encoding utf8
    Move-Item -LiteralPath $temporary -Destination $Path -Force
}

function Read-CurrentRecord {
    if (!(Test-Path -LiteralPath $script:pointerPath)) {
        throw "No capture manifest exists at $script:pointerPath. Start a capture first."
    }
    $pointer = Get-Content -LiteralPath $script:pointerPath -Raw | ConvertFrom-Json
    if (!$pointer.manifest_path) { throw 'Capture pointer has no manifest_path.' }
    $manifestPath = [IO.Path]::GetFullPath([string]$pointer.manifest_path)
    $outputPrefix = $script:outputRootFull.TrimEnd([IO.Path]::DirectorySeparatorChar) + [IO.Path]::DirectorySeparatorChar
    if (!$manifestPath.StartsWith($outputPrefix, [StringComparison]::OrdinalIgnoreCase)) {
        throw 'Capture manifest points outside the configured output directory.'
    }
    if (!(Test-Path -LiteralPath $manifestPath)) { throw "Capture manifest is missing: $manifestPath" }
    return Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
}

if (!(Test-Path -LiteralPath $logman)) { throw "Windows logman.exe was not found: $logman" }

if ($Action -eq 'Plan') {
    [pscustomobject]@{
        action = 'PlanOnly'
        administrator_required = $true
        session = $sessionName
        output_root = $outputRootFull
        max_duration_seconds = $maxTraceSeconds
        max_file_megabytes = $maxTraceMegabytes
        usb_providers = $usbProviders
        usb_keywords = $providerKeywords
        kernel_io_provider = $ioProvider
        kernel_io_flags = 0
        kernel_io_level = 2
        payload_capture = $false
        note = 'HeadersBusTrace records USB transfer events without USB data packets; PartialDataBusTrace and FullDataBusTrace are not enabled.'
    } | ConvertTo-Json -Depth 5
    exit 0
}

if (!(Test-IsAdministrator)) {
    throw 'USB ETW Start/Stop/Status requires an elevated PowerShell window. Plan does not require elevation.'
}

switch ($Action) {
    'Start' {
        if (Test-TraceActive) { throw "ETW session $sessionName is already active; stop it before starting another capture." }

        $devices = @(Get-PnpDevice -Class Ports -PresentOnly -ErrorAction Stop | Where-Object {
            ([string]$_.InstanceId).StartsWith('USB\VID_03FD&PID_7020\', [StringComparison]::OrdinalIgnoreCase)
        })
        if ($devices.Count -ne 1 -or $devices[0].Status -ne 'OK') {
            throw "Expected exactly one present, healthy EYEPQC CDC device (VID_03FD&PID_7020); found $($devices.Count). No trace was started."
        }

        New-Item -ItemType Directory -Path $outputRootFull -Force | Out-Null
        $existingCollector = Invoke-Logman @('query', '-n', $sessionName) -AllowFailure
        if ($existingCollector.ExitCode -eq 0) {
            if (!(Test-Path -LiteralPath $pointerPath)) {
                throw "A Logman collector named $sessionName exists without this tool's ownership manifest; refusing to replace it."
            }
            $oldManifest = Read-CurrentRecord
            if ($oldManifest.schema -ne 'eyepqc-g7-usb-etw-v1' -or $oldManifest.session_name -ne $sessionName) {
                throw 'Existing Logman collector does not match the EYEPQC ETW manifest; refusing to replace it.'
            }
            [void](Invoke-Logman @('stop', '-n', $sessionName) -AllowFailure)
            [void](Invoke-Logman @('delete', '-n', $sessionName))
            $oldManifest | Add-Member -MemberType NoteProperty -Name stopped_utc -Value ([DateTime]::UtcNow.ToString('o')) -Force
            $oldManifest | Add-Member -MemberType NoteProperty -Name etl_bytes -Value 0 -Force
            if (Test-Path -LiteralPath $oldManifest.output_etl) {
                $oldManifest.etl_bytes = (Get-Item -LiteralPath $oldManifest.output_etl).Length
                $oldManifest.state = 'stale_collector_removed'
            } else {
                $oldManifest.state = 'stale_collector_removed_no_etl'
            }
            $oldManifest | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath ([string](Get-Content -LiteralPath $pointerPath -Raw | ConvertFrom-Json).manifest_path) -Encoding utf8
        }

        $stamp = Get-Date -Format 'yyyyMMdd_HHmmss_fff'
        $prefix = Join-Path $outputRootFull "g7_usb_etw_$stamp"
        $etlPath = "$prefix.etl"
        $manifestPath = "$prefix.json"
        $manifest = [ordered]@{
            schema = 'eyepqc-g7-usb-etw-v1'
            state = 'creating'
            session_name = $sessionName
            started_utc = [DateTime]::UtcNow.ToString('o')
            max_duration_seconds = $maxTraceSeconds
            max_file_megabytes = $maxTraceMegabytes
            output_etl = $etlPath
            stopped_utc = $null
            etl_bytes = 0
            device_instance_id = [string]$devices[0].InstanceId
            device_name = [string]$devices[0].FriendlyName
            git_head = ((& git -C $repoRoot rev-parse HEAD 2>$null) | Select-Object -First 1)
            providers = @($usbProviders) + @($ioProvider)
            usb_keywords = 'Default,HeadersBusTrace,StateMachine,Rundown'
            kernel_io_flags = 0
            kernel_io_level = 2
            payload_capture = $false
            note = 'Local diagnostic metadata only; USB transfer payload keywords are disabled.'
        }
        Write-JsonAtomic $manifestPath $manifest

        $created = $false
        try {
            [void](Invoke-Logman @(
                'create', 'trace', '-n', $sessionName,
                '-o', $etlPath, '-f', 'bincirc', '-max', [string]$maxTraceMegabytes,
                '-nb', '16', '64', '-bs', '64', '-rf', '00:05:00'
            ))
            $created = $true
            foreach ($provider in $usbProviders) {
                [void](Invoke-Logman @('update', 'trace', '-n', $sessionName, '-p', $provider, $providerKeywords))
            }
            [void](Invoke-Logman @('update', 'trace', '-n', $sessionName, '-p', $ioProvider, '0', '2'))
            [void](Invoke-Logman @('start', '-n', $sessionName))

            $manifest.state = 'running'
            $manifest.started_utc = [DateTime]::UtcNow.ToString('o')
            Write-JsonAtomic $manifestPath $manifest
            Write-JsonAtomic $pointerPath ([ordered]@{ manifest_path = $manifestPath; updated_utc = [DateTime]::UtcNow.ToString('o') })
            "G7_USB_ETW_STARTED session=$sessionName max_seconds=$maxTraceSeconds max_mb=$maxTraceMegabytes output=$etlPath"
        }
        catch {
            if ($created) {
                [void](Invoke-Logman @('stop', '-n', $sessionName) -AllowFailure)
                [void](Invoke-Logman @('delete', '-n', $sessionName) -AllowFailure)
            }
            $manifest.state = 'start_failed'
            $manifest.error = $_.Exception.Message
            Write-JsonAtomic $manifestPath $manifest
            throw
        }
    }
    'Stop' {
        $manifest = Read-CurrentRecord
        if ($manifest.session_name -ne $sessionName) { throw 'Active manifest has an unexpected ETW session name.' }
        $active = Test-TraceActive
        if ($active) {
            [void](Invoke-Logman @('stop', '-n', $sessionName))
            $manifest.state = 'stopped_by_operator'
        }
        else {
            $manifest.state = 'session_already_stopped'
        }
        $manifest.stopped_utc = [DateTime]::UtcNow.ToString('o')
        $deadline = [DateTime]::UtcNow.AddSeconds(10)
        while (!(Test-Path -LiteralPath $manifest.output_etl) -and [DateTime]::UtcNow -lt $deadline) {
            Start-Sleep -Milliseconds 100
        }
        $manifest.etl_bytes = if (Test-Path -LiteralPath $manifest.output_etl) { (Get-Item -LiteralPath $manifest.output_etl).Length } else { 0 }
        $manifestPath = [string](Get-Content -LiteralPath $pointerPath -Raw | ConvertFrom-Json).manifest_path
        Write-JsonAtomic $manifestPath $manifest
        if ($manifest.etl_bytes -le 0) { throw 'Logman stopped, but the expected ETL file is missing or empty.' }
        if (Test-TraceActive) { throw "ETW session $sessionName is still active after logman stop." }
        [void](Invoke-Logman @('delete', '-n', $sessionName))
        "G7_USB_ETW_STOPPED state=$($manifest.state) etl_bytes=$($manifest.etl_bytes) output=$($manifest.output_etl)"
    }
    'Status' {
        if (!(Test-Path -LiteralPath $pointerPath)) {
            'G7_USB_ETW_STATUS no_current_manifest'
            break
        }
        $manifest = Read-CurrentRecord
        $active = Test-TraceActive
        $etlBytes = if (Test-Path -LiteralPath $manifest.output_etl) { (Get-Item -LiteralPath $manifest.output_etl).Length } else { 0 }
        "G7_USB_ETW_STATUS active=$active state=$($manifest.state) etl_bytes=$etlBytes output=$($manifest.output_etl)"
    }
}
