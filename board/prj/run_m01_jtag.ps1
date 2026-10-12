param(
    [Parameter(Mandatory)][string]$Workspace,
    [string]$ToolRoot = 'D:/AmdDesignTools/2026.1'
)
$ErrorActionPreference = 'Stop'
$repo = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$Workspace = (Resolve-Path -LiteralPath $Workspace).Path
$manifest = Get-Content -LiteralPath "$Workspace/build_manifest.json" -Raw | ConvertFrom-Json
$phy = "$Workspace/m01_platform/ps7_cortexa9_0/standalone_a9_0/bsp/libsrc/lwip220/src/lwip-2.2.0/contrib/ports/xilinx/netif"
foreach ($item in @(
    @($manifest.xsa, $manifest.xsa_sha256),
    @("$repo/board/src/ps/src/m01.c", $manifest.source_sha256),
    @("$repo/board/src/ps/src/m01_yt8521.inc", $manifest.phy_adapter_sha256),
    @("$Workspace/m01/build/m01.elf", $manifest.elf_sha256),
    @("$phy/xemacpsif_physpeed.c", $manifest.phy_driver_sha256),
    @("$phy/xadapter.c", $manifest.link_driver_sha256)
)) {
    if ((Get-FileHash -LiteralPath $item[0]).Hash.ToLower() -ne $item[1]) {
        throw "Artifact/source changed; rebuild before JTAG: $($item[0])"
    }
}
Add-Type -AssemblyName System.IO.Compression.FileSystem
$zip = [IO.Compression.ZipFile]::OpenRead($manifest.xsa)
try {
    foreach ($item in @(@('m01.bit', "$Workspace/m01/_ide/bitstream/m01.bit"),
                        @('ps7_init.tcl', "$Workspace/m01/_ide/psinit/ps7_init.tcl"))) {
        $stream = $zip.GetEntry($item[0]).Open()
        $sha = [Security.Cryptography.SHA256]::Create()
        try { $hash = [BitConverter]::ToString($sha.ComputeHash($stream)).Replace('-', '') }
        finally { $stream.Dispose(); $sha.Dispose() }
        if ($hash -ne (Get-FileHash -LiteralPath $item[1]).Hash) {
            throw "Artifact is not from the manifest XSA: $($item[1])"
        }
    }
} finally { $zip.Dispose() }
$log = Join-Path $repo ("build/m01_jtag_{0}.log" -f (Get-Date -Format 'yyyyMMdd_HHmmss_fff'))
$result = & "$ToolRoot/Vivado/bin/xsdb.bat" "$PSScriptRoot/run_m01_jtag.tcl" $Workspace 2>&1
$result | Tee-Object -FilePath $log | ForEach-Object { Write-Host $_ }
# The vendor .bat wrapper can return 0 even when Tcl calls exit 1.
if ($LASTEXITCODE -ne 0 -or !($result -contains 'M01_JTAG_RUNNING')) {
    throw "JTAG failed; inspect $log"
}
