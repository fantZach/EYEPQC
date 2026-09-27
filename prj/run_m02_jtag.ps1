param(
    [string]$HardwareDirectory = 'build/vivado/m02_board_demo',
    [string]$ToolRoot = 'D:/AmdDesignTools/2026.1',
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
    $taskProbeOutput = @(& $xsdb prj/run_m02_jtag.tcl $HardwareDirectory 2>&1)
    $taskProbeExit = $LASTEXITCODE
    $taskProbeOutput | Tee-Object -FilePath $LogPath
    # xsdb.bat may return 0 after a Tcl error; require fresh successful evidence.
    if ($taskProbeExit -ne 0 -or !($taskProbeOutput -match '^M02_JTAG_OK sensor_resets=20 ')) {
        throw "M02 probe failed; see $LogPath"
    }
} finally { Pop-Location }
