param(
    [string]$ToolRoot = 'D:/AmdDesignTools/2026.1',
    [ValidatePattern('^[A-Za-z0-9_-]+$')][string]$BuildName = 'm05'
)
$ErrorActionPreference = 'Stop'
$repo = Split-Path $PSScriptRoot -Parent
$hw = Join-Path $repo "build/vivado/$BuildName"
$sw = Join-Path $repo "build/vitis/$BuildName"
if ((Test-Path -LiteralPath $hw) -or (Test-Path -LiteralPath $sw)) { throw 'Use a fresh BuildName' }
$oldXsa = $env:EYEPQC_M05_XSA
$oldWorkspace = $env:EYEPQC_M05_VITIS
$oldTools = $env:EYEPQC_TOOL_ROOT
Push-Location $repo
try {
    & ./.venv/Scripts/python.exe sim/tb/test_m05.py
    if ($LASTEXITCODE -ne 0) { throw 'M05 offline checks failed' }
    & "$ToolRoot/Vivado/bin/vivado.bat" -mode batch -source prj/build_m05.tcl `
        -log "build/${BuildName}_vivado.log" -journal "build/${BuildName}_vivado.jou" -tclargs $hw
    if ($LASTEXITCODE -ne 0 -or !(Test-Path "$hw/m01.xsa")) { throw 'M05 hardware failed' }
    & "$ToolRoot/Vivado/bin/vivado.bat" -mode batch -source prj/report_m05.tcl `
        -log "build/${BuildName}_report.log" -journal "build/${BuildName}_report.jou" -tclargs $hw
    if ($LASTEXITCODE -ne 0 -or !(Test-Path "$hw/cdc.txt")) { throw 'M05 physical reports failed' }
    $env:EYEPQC_M05_XSA = "$hw/m01.xsa"
    $env:EYEPQC_M05_VITIS = $sw
    $env:EYEPQC_TOOL_ROOT = $ToolRoot
    & "$ToolRoot/Vitis/bin/vitis.bat" -s prj/build_m05.py
    if ($LASTEXITCODE -ne 0 -or !(Test-Path "$sw/build_manifest.json")) { throw 'M05 software failed' }
    Write-Host "M05_BUILD_OK $sw"
} finally {
    $env:EYEPQC_M05_XSA = $oldXsa
    $env:EYEPQC_M05_VITIS = $oldWorkspace
    $env:EYEPQC_TOOL_ROOT = $oldTools
    Pop-Location
}
