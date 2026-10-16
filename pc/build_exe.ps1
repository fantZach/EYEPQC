[CmdletBinding()]
param([string]$Python = '', [switch]$InstallDependencies, [ValidatePattern('^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$')][string]$Name = 'eyepqc-1.3')
$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent $PSScriptRoot
if (-not $Python) { $Python = Join-Path $repo '.venv/Scripts/python.exe' }
$buildRoot = Join-Path $repo 'build/pc_cli'
$packPython = Join-Path $buildRoot 'venv/Scripts/python.exe'
if (-not (Test-Path -LiteralPath $packPython)) {
    if (-not $InstallDependencies) { throw 'First build: pass -InstallDependencies to create the isolated packaging environment.' }
    & $Python -m venv (Join-Path $buildRoot 'venv')
    if ($LASTEXITCODE -ne 0) { throw 'Packaging environment creation failed.' }
}
if ($InstallDependencies) {
    & $packPython -m pip install -r (Join-Path $PSScriptRoot 'requirements-build.txt')
    if ($LASTEXITCODE -ne 0) { throw 'Packaging dependency installation failed.' }
}
& $packPython -m PyInstaller --noconfirm --clean --onefile --console --noupx --name $Name `
    --paths (Join-Path $PSScriptRoot 'src/host') `
    --distpath (Join-Path $buildRoot 'dist') --workpath (Join-Path $buildRoot 'work') `
    --specpath (Join-Path $buildRoot 'spec') (Join-Path $PSScriptRoot 'src/host/eyepqc.py')
if ($LASTEXITCODE -ne 0) { throw 'EXE build failed.' }
$exe = Join-Path $buildRoot "dist/$Name.exe"
& $exe --version
if ($LASTEXITCODE -ne 0) { throw 'EXE smoke test failed.' }
Get-FileHash -LiteralPath $exe -Algorithm SHA256
Write-Host 'Build complete. No config, credentials, certificates or SSH keys are bundled.'
