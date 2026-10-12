param(
    [string]$ToolRoot = 'E:/fpg/2026.1',
    [ValidatePattern('^[A-Za-z0-9_-]+$')][string]$BuildName = ("g0_{0}" -f (Get-Date -Format 'yyyyMMdd_HHmmss'))
)
$ErrorActionPreference = 'Stop'
$repo = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$vivado = Join-Path $ToolRoot 'Vivado/bin/vivado.bat'
$hw = Join-Path $repo "build/vivado/$BuildName"
$vitis = Join-Path $repo "build/vitis/$BuildName"
$software = Join-Path $repo "build/vitis/${BuildName}_startup"
$metadata = Join-Path $repo "build/g0_meta/$BuildName"
$snapshot = Join-Path $metadata 'source_inputs.json'
$implementedReport = Join-Path $metadata 'implemented_io.txt'
foreach ($path in @($hw, $vitis, $software)) {
    if (Test-Path -LiteralPath $path) { throw "Use a fresh -BuildName; output exists: $path" }
}
if (Test-Path -LiteralPath $metadata) { throw "Use a fresh -BuildName; output exists: $metadata" }
New-Item -ItemType Directory -Path $metadata -Force | Out-Null
Push-Location $repo
try {
    & ./.venv/Scripts/python.exe board/prj/g0_source_manifest.py capture $snapshot
    if ($LASTEXITCODE -ne 0) { throw 'Could not capture G0 source snapshot' }
    if (!(Test-Path -LiteralPath $vivado)) { throw "Missing Vivado: $vivado" }
    New-Item -ItemType Directory -Force -Path (Join-Path $repo 'build') | Out-Null
    & $vivado -mode batch -source board/prj/build_m01.tcl `
        -log "build/${BuildName}_vivado.log" -journal "build/${BuildName}_vivado.jou" -tclargs $hw
    if ($LASTEXITCODE -ne 0 -or !(Test-Path -LiteralPath "$hw/m01.xsa")) {
        throw 'Fresh G0 M01 hardware platform build failed'
    }
    & ./.venv/Scripts/python.exe board/prj/g0_source_manifest.py check $snapshot
    if ($LASTEXITCODE -ne 0) { throw 'G0 platform sources changed during Vivado build' }
    & $vivado -mode batch -source board/prj/check_g0_implemented.tcl `
        -log "$metadata/implemented_check.log" -journal "$metadata/implemented_check.jou" `
        -tclargs "$hw/m01.xpr" $implementedReport
    if ($LASTEXITCODE -ne 0 -or !(Test-Path -LiteralPath "$implementedReport.verified.txt")) {
        throw 'Implemented H15/clock verification failed; inspect Vivado report'
    }
    & ./.venv/Scripts/python.exe board/prj/build_g0_software.py `
        --xsa "$hw/m01.xsa" --output $software --tool-root $ToolRoot `
        --source-manifest $snapshot --implemented-evidence $implementedReport
    if ($LASTEXITCODE -ne 0 -or !(Test-Path -LiteralPath "$software/g0_manifest.json")) {
        throw 'G0 startup software/BOOT.BIN build failed; inspect output logs'
    }
    Write-Host "G0 startup build ready: $software/g0_startup/boot/BOOT.BIN"
    Write-Host "Implemented evidence: $implementedReport"
    Write-Host 'No UART, SD card, JTAG, or board was accessed.'
} finally {
    Pop-Location
}
