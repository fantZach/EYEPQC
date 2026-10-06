param(
    [ValidateSet('Check', 'Build', 'Prepare', 'Preflight', 'G3', 'G6')][string]$Mode = 'Check',
    [string]$ToolRoot = $(if ($env:EYEPQC_TOOL_ROOT) { $env:EYEPQC_TOOL_ROOT } else { 'E:/fpg/2026.1' }),
    [string]$Workspace = 'build/vitis/software_ready',
    [string]$Xsa = 'build/vivado/g3_gui/m01.xsa',
    [double]$Seconds = 10,
    [switch]$Show
)
$ErrorActionPreference = 'Stop'
$python = Join-Path $PSScriptRoot '.venv/Scripts/python.exe'
if (!(Test-Path -LiteralPath $python)) { throw 'Create .venv with Python 3.12 and install requirements.txt first.' }
$savedPath = $env:PATH
$savedTools = $env:EYEPQC_TOOL_ROOT
Push-Location $PSScriptRoot
try {
    $env:EYEPQC_TOOL_ROOT = $ToolRoot
    if (Test-Path -LiteralPath 'C:/msys64/ucrt64/bin') { $env:PATH = 'C:/msys64/ucrt64/bin;' + $env:PATH }
    switch ($Mode) {
        'Check' { & $python prj/check_software.py --tool-root $ToolRoot }
        'Build' { & $python prj/build_software.py --xsa $Xsa --output $Workspace --tool-root $ToolRoot --boot-images }
        'Prepare' { & $python prj/prepare_demo.py }
        'Preflight' { & $python prj/verify_software.py $Workspace }
        'G3' {
            & $python prj/verify_software.py $Workspace
            if ($LASTEXITCODE -ne 0) { throw 'Software preflight failed' }
            & $python src/host/g3_board.py $Workspace --boot --count 1 --tool-root $ToolRoot
        }
        'G6' {
            & $python prj/verify_software.py $Workspace
            if ($LASTEXITCODE -ne 0) { throw 'Software preflight failed' }
            $arguments = @('src/host/g6_board.py', '--workspace', $Workspace, '--tool-root', $ToolRoot,
                           '--seconds', $Seconds, '--sessions', '2', '--fault-check')
            if ($Show) { $arguments += '--show' }
            & $python @arguments
        }
    }
    if ($LASTEXITCODE -ne 0) { throw "$Mode failed; inspect the printed log path." }
} finally {
    $env:PATH = $savedPath
    $env:EYEPQC_TOOL_ROOT = $savedTools
    Pop-Location
}
