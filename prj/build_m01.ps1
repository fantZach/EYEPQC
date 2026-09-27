param(
    [string]$ToolRoot = 'D:/AmdDesignTools/2026.1',
    [ValidatePattern('^[A-Za-z0-9_-]+$')][string]$BuildName = 'm01'
)
$ErrorActionPreference = 'Stop'
$repo = Split-Path $PSScriptRoot -Parent
$vivado = Join-Path $ToolRoot 'Vivado/bin/vivado.bat'
$vitis = Join-Path $ToolRoot 'Vitis/bin/vitis.bat'
foreach ($tool in @($vivado, $vitis)) {
    if (!(Test-Path -LiteralPath $tool)) { throw "Missing tool: $tool" }
}
$hw = Join-Path $repo "build/vivado/$BuildName"
$sw = Join-Path $repo "build/vitis/$BuildName"
foreach ($output in @($hw, $sw)) {
    if (Test-Path -LiteralPath $output) { throw "Use a fresh -BuildName; output exists: $output" }
}
$oldXsa = $env:EYEPQC_M01_XSA
$oldVitis = $env:EYEPQC_M01_VITIS
Push-Location $repo
try {
    & ./sim/scripts/run_m01.ps1
    New-Item -ItemType Directory -Force -Path (Join-Path $repo 'build') | Out-Null
    & $vivado -mode batch -source prj/build_m01.tcl `
        -log "build/${BuildName}_vivado.log" -journal "build/${BuildName}_vivado.jou" -tclargs $hw
    if ($LASTEXITCODE -ne 0 -or !(Test-Path -LiteralPath "$hw/m01.xsa")) {
        throw 'Vivado failed; do not continue with an old/vendor XSA'
    }
    $env:EYEPQC_M01_XSA = "$hw/m01.xsa"
    $env:EYEPQC_M01_VITIS = $sw
    & $vitis -s prj/build_m01.py
    # Vitis -s may return 0 even on a Python exception, so verify the fresh artifact.
    if ($LASTEXITCODE -ne 0 -or !(Test-Path -LiteralPath "$sw/m01/build/m01.elf") -or
        !(Test-Path -LiteralPath "$sw/build_manifest.json")) {
        throw 'Vitis failed; inspect its error log'
    }
    Write-Host "M01 built: $hw/m01.xsa; $sw/m01/build/m01.elf. Board validation pending."
} finally {
    $env:EYEPQC_M01_XSA = $oldXsa
    $env:EYEPQC_M01_VITIS = $oldVitis
    Pop-Location
}
