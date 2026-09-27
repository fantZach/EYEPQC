param(
    [string]$ToolRoot = 'D:/AmdDesignTools/2026.1',
    [ValidatePattern('^[A-Za-z0-9_-]+$')][string]$BuildName = 'aes_mvp'
)
$ErrorActionPreference = 'Stop'
$repo = Split-Path $PSScriptRoot -Parent
$hw = Join-Path $repo "build/vivado/$BuildName"
$sw = Join-Path $repo "build/vitis/$BuildName"
if ((Test-Path -LiteralPath $hw) -or (Test-Path -LiteralPath $sw)) { throw 'Use a fresh BuildName' }
$oldXsa = $env:EYEPQC_MVP_XSA
$oldWorkspace = $env:EYEPQC_MVP_VITIS
$oldTools = $env:EYEPQC_TOOL_ROOT
Push-Location $repo
try {
    & ./.venv/Scripts/python.exe sim/tb/test_aes_mvp.py
    if ($LASTEXITCODE -ne 0) { throw 'MVP offline checks failed' }
    & "$ToolRoot/Vivado/bin/vivado.bat" -mode batch -source prj/build_aes_mvp.tcl `
        -log "build/${BuildName}_vivado.log" -journal "build/${BuildName}_vivado.jou" -tclargs $hw
    if ($LASTEXITCODE -ne 0 -or !(Test-Path "$hw/m01.xsa")) { throw 'MVP hardware failed' }
    $env:EYEPQC_MVP_XSA = "$hw/m01.xsa"
    $env:EYEPQC_MVP_VITIS = $sw
    $env:EYEPQC_TOOL_ROOT = $ToolRoot
    & "$ToolRoot/Vitis/bin/vitis.bat" -s prj/build_aes_mvp.py
    if ($LASTEXITCODE -ne 0 -or !(Test-Path "$sw/build_manifest.json")) { throw 'MVP software failed' }
    Write-Host "AES_MVP_BUILD_OK $sw"
} finally {
    $env:EYEPQC_MVP_XSA = $oldXsa
    $env:EYEPQC_MVP_VITIS = $oldWorkspace
    $env:EYEPQC_TOOL_ROOT = $oldTools
    Pop-Location
}
