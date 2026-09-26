$ErrorActionPreference = 'Stop'
$workspace = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$pythonPath = Join-Path $workspace '.venv/Scripts/python.exe'
if (!(Test-Path -LiteralPath $pythonPath -PathType Leaf)) {
    throw 'Run python -m venv .venv and .venv/Scripts/python.exe -m pip install -r requirements.txt first.'
}
& $pythonPath (Join-Path $PSScriptRoot 'generate_vectors.py') --check
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
& $pythonPath (Join-Path $workspace 'sim/tb/test_m00.py')
exit $LASTEXITCODE
