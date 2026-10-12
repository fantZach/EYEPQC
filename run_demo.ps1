param(
    [ValidateSet('Check', 'Build', 'Prepare', 'Preflight', 'JtagCheck', 'G3', 'G6', 'G7', 'Demo')][string]$Mode = 'Check',
    [string]$ToolRoot = $(if ($env:EYEPQC_TOOL_ROOT) { $env:EYEPQC_TOOL_ROOT } else { 'E:/fpg/2026.1' }),
    [string]$Workspace = 'build/vitis/usbfix3_20261007',
    [string]$Xsa = 'build/vivado/g3_gui/m01.xsa',
    [double]$Seconds = 10,
    [switch]$Show,
    [switch]$Offline
)
$ErrorActionPreference = 'Stop'
$python = Join-Path $PSScriptRoot '.venv/Scripts/python.exe'
if (!(Test-Path -LiteralPath $python)) { throw 'Create .venv with Python 3.12 and install requirements.txt first.' }
$savedPath = $env:PATH
$savedTools = $env:EYEPQC_TOOL_ROOT
Push-Location $PSScriptRoot
try {
    $env:EYEPQC_TOOL_ROOT = $ToolRoot
    if ($Offline -and $Mode -ne 'Demo') { throw '-Offline is available only for Demo.' }
    if (Test-Path -LiteralPath 'C:/msys64/ucrt64/bin') { $env:PATH = 'C:/msys64/ucrt64/bin;' + $env:PATH }
    switch ($Mode) {
        'Check' { & $python board/prj/check_software.py --tool-root $ToolRoot }
        'Build' { & $python board/prj/build_software.py --xsa $Xsa --output $Workspace --tool-root $ToolRoot --boot-images }
        'Prepare' { & $python board/prj/prepare_demo.py }
        'Preflight' { & $python board/prj/verify_software.py $Workspace }
        'JtagCheck' { & $python board/prj/check_jtag.py --tool-root $ToolRoot }
        'G3' {
            & $python board/prj/verify_software.py $Workspace
            if ($LASTEXITCODE -ne 0) { throw 'Software preflight failed' }
            & $python pc/src/host/g3_board.py $Workspace --boot --count 1 --tool-root $ToolRoot
        }
        'G6' {
            & $python board/prj/verify_software.py $Workspace
            if ($LASTEXITCODE -ne 0) { throw 'Software preflight failed' }
            $arguments = @('pc/src/host/g6_board.py', '--workspace', $Workspace, '--tool-root', $ToolRoot,
                           '--seconds', $Seconds, '--sessions', '2', '--fault-check')
            if ($Show) { $arguments += '--show' }
            & $python @arguments
        }
        'G7' {
            & ./run_g7_recovery.ps1 -Workspace $Workspace -ToolRoot $ToolRoot `
                -Seconds ([Math]::Max(2, [Math]::Ceiling($Seconds)))
        }
        'Demo' {
            $arguments = @('pc/src/host/demo_window.py', '--workspace', $Workspace)
            if ($Offline) { $arguments += '--offline' }
            & $python @arguments
        }
    }
    if ($LASTEXITCODE -ne 0) { throw "$Mode failed; inspect the printed log path." }
} finally {
    $env:PATH = $savedPath
    $env:EYEPQC_TOOL_ROOT = $savedTools
    Pop-Location
}
