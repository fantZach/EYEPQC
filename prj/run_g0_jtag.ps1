param(
    [Parameter(Mandatory)][string]$Workspace,
    [string]$ToolRoot = 'E:/fpg/2026.1',
    [switch]$Execute
)
$ErrorActionPreference = 'Stop'
$repo = Split-Path $PSScriptRoot -Parent
$Workspace = (Resolve-Path -LiteralPath $Workspace).Path
$manifestPath = Join-Path $Workspace 'g0_manifest.json'
if (!(Test-Path -LiteralPath $manifestPath)) { throw "Missing G0 manifest: $manifestPath" }
$preflight = & "$repo/.venv/Scripts/python.exe" "$PSScriptRoot/g0_acceptance.py" preflight `
    --manifest $manifestPath 2>&1
$preflight | ForEach-Object { Write-Host $_ }
if ($LASTEXITCODE -ne 0) { throw 'G0 artifact preflight failed; no JTAG action taken' }
$manifest = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
$app = Join-Path $Workspace 'g0_startup'
$bit = Join-Path $app '_ide/bitstream/m01.bit'
$init = Join-Path $app '_ide/psinit/ps7_init.tcl'
Add-Type -AssemblyName System.IO.Compression.FileSystem
$zip = [IO.Compression.ZipFile]::OpenRead($manifest.xsa)
try {
    foreach ($item in @(@('m01.bit', $bit, $manifest.bit_sha256),
                        @('ps7_init.tcl', $init, $manifest.ps7_init_sha256))) {
        $entry = $zip.GetEntry($item[0])
        if (!$entry) { throw "XSA is missing $($item[0])" }
        $stream = $entry.Open()
        $sha = [Security.Cryptography.SHA256]::Create()
        try { $xsaHash = [BitConverter]::ToString($sha.ComputeHash($stream)).Replace('-', '').ToLowerInvariant() }
        finally { $stream.Dispose(); $sha.Dispose() }
        if ($xsaHash -ne $item[2] -or
            (Get-FileHash -LiteralPath $item[1] -Algorithm SHA256).Hash.ToLowerInvariant() -ne $item[2]) {
            throw "G0 artifact does not match input XSA: $($item[0])"
        }
    }
} finally { $zip.Dispose() }
Write-Host "G0 image build=$($manifest.build_id) ELF=$app/build/g0_startup.elf"
Write-Host "BOOT.BIN (not written by this command)=$($manifest.boot_bin)"
if (!$Execute) {
    Write-Host 'G0_JTAG_DRY_RUN_ONLY: supply -Execute only in the coordinated board-exclusive window.'
    return
}
$xsdb = Join-Path $ToolRoot 'Vivado/bin/xsdb.bat'
if (!(Test-Path -LiteralPath $xsdb)) { throw "Missing XSDB: $xsdb" }
$log = Join-Path $repo ("build/g0_jtag_{0}.log" -f (Get-Date -Format 'yyyyMMdd_HHmmss_fff'))
if (Test-Path -LiteralPath $log) { throw "Refusing to overwrite JTAG log: $log" }
$result = & $xsdb "$PSScriptRoot/run_g0_jtag.tcl" $Workspace 2>&1
$result | Tee-Object -FilePath $log | ForEach-Object { Write-Host $_ }
if ($LASTEXITCODE -ne 0 -or !($result -contains 'G0_JTAG_RUNNING')) {
    throw "G0 volatile JTAG load failed; inspect $log"
}
Write-Host 'G0_JTAG_LOADED_VOLATILE_ONLY; SD/Flash untouched'
