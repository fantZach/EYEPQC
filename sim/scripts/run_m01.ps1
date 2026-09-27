param([string]$Python = '', [string]$IcarusRoot = 'C:/iverilog/bin')
$ErrorActionPreference = 'Stop'
$repo = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
if (!$Python) { $Python = Join-Path $repo '.venv/Scripts/python.exe' }
if (!(Test-Path -LiteralPath $Python)) { throw "Python missing: $Python" }
if (Test-Path -LiteralPath $IcarusRoot) {
    $env:IVERILOG = Join-Path $IcarusRoot 'iverilog.exe'
    $env:VVP = Join-Path $IcarusRoot 'vvp.exe'
}
& $Python (Join-Path $repo 'sim/tb/test_m01.py')
if ($LASTEXITCODE -ne 0) { throw 'M01 offline checks failed' }
