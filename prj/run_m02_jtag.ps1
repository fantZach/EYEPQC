param(
    [string]$HardwareDirectory = 'build/vivado/m02_board_demo',
    [string]$ToolRoot = 'E:/fpg/2026.1',
    [ValidateRange(1, 20)]
    [int]$SensorResets = 20,
    [switch]$ExpectCameraFailure,
    [string]$LogPath = ''
)
$ErrorActionPreference = 'Stop'
$repo = Split-Path $PSScriptRoot -Parent
$xsdb = Join-Path $ToolRoot 'Vivado/bin/xsdb.bat'
if (!(Test-Path -LiteralPath $xsdb -PathType Leaf)) { throw "Missing tool: $xsdb" }
Push-Location $repo
try {
    if (!$LogPath) { $LogPath = "build/m02_jtag_$(Get-Date -Format 'yyyyMMdd_HHmmss_ffff').log" }
    if (Test-Path -LiteralPath $LogPath) { throw "Log already exists: $LogPath" }
    if ($ExpectCameraFailure -and $SensorResets -ne 1) {
        throw 'Expected-camera-failure probe requires exactly one sensor reset.'
    }
    $expectFailureFlag = if ($ExpectCameraFailure) { 1 } else { 0 }
    $taskProbeOutput = @(& $xsdb prj/run_m02_jtag.tcl $HardwareDirectory $SensorResets $expectFailureFlag 2>&1)
    $taskProbeExit = $LASTEXITCODE
    $taskProbeOutput | Tee-Object -FilePath $LogPath
    # xsdb.bat may return 0 after a Tcl error; require fresh successful evidence.
    if ($ExpectCameraFailure) {
        $expectedMarker = '^M02_JTAG_EXPECTED_FAILURE sensor_resets=1 configured=0 capture_resetn=0 failed=1 error=[1-5] '
    } else {
        $expectedMarker = '^M02_JTAG_OK sensor_resets={0} ' -f $SensorResets
    }
    if ($taskProbeExit -ne 0 -or !($taskProbeOutput -match $expectedMarker)) {
        throw "M02 probe failed; see $LogPath"
    }
} finally { Pop-Location }
