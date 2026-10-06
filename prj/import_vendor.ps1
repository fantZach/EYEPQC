param([string]$SourceRoot = '')

$ErrorActionPreference = 'Stop'
if (!$SourceRoot -or !(Test-Path -LiteralPath $SourceRoot -PathType Container)) {
    throw "Pass -SourceRoot with the path to the official 4_Source_Code directory."
}
$workspace = Split-Path -Parent $PSScriptRoot
$destination = Join-Path $workspace 'board/vendor'
$archives = @(
    @{ Path = '1_FPGA_Design/ZYNQ_7020_FPGA.rar'; Projects = '1_led|42_ov5640_udp_pc' },
    @{ Path = '2_Embedded_Vitis/ZYNQ_Vitis_7020.rar'; Projects = '1_hello_world|3_gpio_emio|8_uart_intr_loop|9_timer_intr_led|40_lwip_echo_server|44_ov5640_ps_eth_udp_pc' }
)

New-Item -ItemType Directory -Force -Path $destination | Out-Null
$manifest = @()
foreach ($archive in $archives) {
    $path = Join-Path $SourceRoot $archive.Path
    $entries = @(& tar -tf $path)
    if ($LASTEXITCODE -ne 0) { throw "Cannot read archive: $path" }
    $selected = @($entries | Where-Object {
        $_ -match "/($($archive.Projects))/" -and
        $_ -match '\.(xpr|xdc|bd|tcl|v|sv|c|h|ld|xml|html)$' -and
        $_ -notmatch '(\.cache/|\.runs/|/\.metadata/|/bsp/|/libsrc/|/Debug/|/Release/)' -and
        ($_ -notmatch '\.gen/' -or $_ -match '(system_bd\.tcl|ps7_init\.html)$')
    })
    if (!$selected.Count) { throw "No selected source files: $path" }
    foreach ($entry in $selected) {
        $target = [IO.Path]::GetFullPath((Join-Path $destination $entry))
        if ($entry -match '(^|/)\.\.(/|$)' -or
            !$target.StartsWith($destination + [IO.Path]::DirectorySeparatorChar,
                                [StringComparison]::OrdinalIgnoreCase)) {
            throw "Archive entry outside destination: $entry"
        }
    }
    Write-Output "Extracting $($selected.Count) selected source files: $path"
    $selectionFile = [IO.Path]::GetTempFileName()
    try {
        [IO.File]::WriteAllLines($selectionFile, [string[]]$selected, [Text.UTF8Encoding]::new($false))
        & tar -xf $path -C $destination -k -T $selectionFile
        if ($LASTEXITCODE -ne 0) { throw 'Extraction failed; existing files are never overwritten. Inspect partial output before retrying.' }
    } finally {
        Remove-Item -LiteralPath $selectionFile
    }
    $manifest += [ordered]@{
        archive = $path
        bytes = (Get-Item -LiteralPath $path).Length
        sha256 = (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant()
        entries = $selected
    }
}
$json = $manifest | ConvertTo-Json -Depth 4
[IO.File]::WriteAllText((Join-Path $destination 'manifest.json'), $json + "`n",
                       [Text.UTF8Encoding]::new($false))
Write-Output "Imported source subsets into $destination"
