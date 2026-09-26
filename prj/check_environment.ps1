param(
    [string]$ToolRoot = '',
    [string]$VendorRoot = ''
)

$ErrorActionPreference = 'Stop'
$workspace = Split-Path -Parent $PSScriptRoot
if (!$VendorRoot) { $VendorRoot = Join-Path $workspace 'board/vendor' }

function Find-Tool([string]$Name, [string]$Relative) {
    if ($ToolRoot) {
        $candidate = Join-Path $ToolRoot $Relative
        if (Test-Path -LiteralPath $candidate -PathType Leaf) { return $candidate }
    }
    $command = Get-Command $Name -ErrorAction SilentlyContinue
    if ($command) { return $command.Source }
    return $null
}

$vivadoPath = Find-Tool 'vivado' 'Vivado/bin/vivado.bat'
$vitisPath = Find-Tool 'vitis' 'Vitis/bin/vitis.bat'
$compilerPath = Find-Tool 'gcc' 'tps/mingw/10.0.0/win64.o/nt/bin/gcc.exe'
$pythonPath = Join-Path $workspace '.venv/Scripts/python.exe'
if (!(Test-Path -LiteralPath $pythonPath)) { $pythonPath = Find-Tool 'python' '' }
$iverilogPath = Find-Tool 'iverilog' ''

[ordered]@{
    Vivado = $vivadoPath
    Vitis = $vitisPath
    Python = $pythonPath
    CCompiler = $compilerPath
    IcarusVerilog = $iverilogPath
    VendorRoot = $VendorRoot
} | ConvertTo-Json

$serialPorts = @(Get-CimInstance Win32_SerialPort | Select-Object DeviceID, Name)
Write-Output 'Detected serial ports:'
$serialPorts | Format-Table -AutoSize

if (Test-Path -LiteralPath $VendorRoot -PathType Container) {
    Write-Output 'Vendor source files for manual board-revision review:'
    $vendorFiles = @(Get-ChildItem -LiteralPath $VendorRoot -File -Recurse |
        Where-Object { $_.Extension -in '.xdc','.xpr','.tcl','.xml','.v','.sv' })
    $vendorFiles | Select-Object FullName, Length | Format-Table -AutoSize
} else {
    $vendorFiles = @()
    Write-Output 'PENDING: official OV5640/XDC/PS preset files not imported.'
}

if (!$vivadoPath -or !$vitisPath -or !$pythonPath -or !$compilerPath) {
    Write-Output 'PENDING: required build tools missing.'
    exit 2
}
if (!$vendorFiles.Count) { exit 2 }
Write-Output 'Tools and candidate files found; this does not certify M01/G0.'
exit 0
