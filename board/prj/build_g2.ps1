param(
    [string]$ToolRoot = 'D:/AmdDesignTools/2026.1',
    [ValidatePattern('^[A-Za-z0-9_-]+$')][string]$BuildName = 'g2'
)
$ErrorActionPreference = 'Stop'
$repo = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$hw = Join-Path $repo "build/vivado/$BuildName"
$sw = Join-Path $repo "build/vitis/$BuildName"
if ((Test-Path -LiteralPath $hw) -or (Test-Path -LiteralPath $sw)) { throw 'Use a fresh BuildName' }
$oldXsa = $env:EYEPQC_G2_XSA
$oldWorkspace = $env:EYEPQC_G2_VITIS
$oldTools = $env:EYEPQC_TOOL_ROOT
Push-Location $repo
try {
    & ./.venv/Scripts/python.exe sim/tb/test_m08.py
    if ($LASTEXITCODE -ne 0) { throw 'M08 offline checks failed' }
    & "$ToolRoot/Vivado/bin/vivado.bat" -mode batch -source board/prj/build_g2.tcl `
        -log "build/${BuildName}_vivado.log" -journal "build/${BuildName}_vivado.jou" -tclargs $hw
    if ($LASTEXITCODE -ne 0 -or !(Test-Path "$hw/m01.xsa")) { throw 'G2 hardware failed' }
    $env:EYEPQC_G2_XSA = "$hw/m01.xsa"
    $env:EYEPQC_G2_VITIS = $sw
    $env:EYEPQC_TOOL_ROOT = $ToolRoot
    & "$ToolRoot/Vitis/bin/vitis.bat" -s board/prj/build_g2.py
    if ($LASTEXITCODE -ne 0 -or !(Test-Path "$sw/build_manifest.json")) { throw 'G2 software failed' }
    Write-Host "G2_BUILD_OK $sw"
} finally {
    $env:EYEPQC_G2_XSA = $oldXsa
    $env:EYEPQC_G2_VITIS = $oldWorkspace
    $env:EYEPQC_TOOL_ROOT = $oldTools
    Pop-Location
}
