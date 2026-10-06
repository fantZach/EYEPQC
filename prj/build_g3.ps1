param(
    [string]$ToolRoot = $(if ($env:EYEPQC_TOOL_ROOT) { $env:EYEPQC_TOOL_ROOT } else { 'D:/AmdDesignTools/2026.1' }),
    [ValidatePattern('^[A-Za-z0-9_-]+$')][string]$BuildName = 'g3'
)
$ErrorActionPreference = 'Stop'
$repo = Split-Path $PSScriptRoot -Parent
$hw = Join-Path $repo "build/vivado/$BuildName"
$sw = Join-Path $repo "build/vitis/$BuildName"
if ((Test-Path -LiteralPath $hw) -or (Test-Path -LiteralPath $sw)) { throw 'Use a fresh BuildName' }
$oldXsa = $env:EYEPQC_G3_XSA
$oldWorkspace = $env:EYEPQC_G3_VITIS
$oldTools = $env:EYEPQC_TOOL_ROOT
Push-Location $repo
try {
    & ./.venv/Scripts/python.exe sim/tb/test_m05.py
    if ($LASTEXITCODE -ne 0) { throw 'M05 offline checks failed' }
    & ./.venv/Scripts/python.exe sim/tb/test_m08.py
    if ($LASTEXITCODE -ne 0) { throw 'M08 offline checks failed' }
    & ./.venv/Scripts/python.exe sim/tb/test_g3.py
    if ($LASTEXITCODE -ne 0) { throw 'G3 host checks failed' }
    & "$ToolRoot/Vivado/bin/vivado.bat" -mode batch -source prj/build_g3.tcl `
        -log "build/${BuildName}_vivado.log" -journal "build/${BuildName}_vivado.jou" -tclargs $hw
    if ($LASTEXITCODE -ne 0 -or !(Test-Path "$hw/m01.xsa")) { throw 'G3 hardware failed' }
    & "$ToolRoot/Vivado/bin/vivado.bat" -mode batch -source prj/report_m05.tcl `
        -log "build/${BuildName}_report.log" -journal "build/${BuildName}_report.jou" -tclargs $hw
    if ($LASTEXITCODE -ne 0 -or !(Test-Path "$hw/cdc.txt")) { throw 'G3 physical reports failed' }
    $env:EYEPQC_G3_XSA = "$hw/m01.xsa"
    $env:EYEPQC_G3_VITIS = $sw
    $env:EYEPQC_TOOL_ROOT = $ToolRoot
    & "$ToolRoot/Vitis/bin/vitis.bat" -s prj/build_g3.py
    if ($LASTEXITCODE -ne 0 -or !(Test-Path "$sw/build_manifest.json")) { throw 'G3 software failed' }
    Write-Host "G3_BUILD_OK $sw"
} finally {
    $env:EYEPQC_G3_XSA = $oldXsa
    $env:EYEPQC_G3_VITIS = $oldWorkspace
    $env:EYEPQC_TOOL_ROOT = $oldTools
    Pop-Location
}
