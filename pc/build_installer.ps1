[CmdletBinding()]
param(
    [string]$Compiler = '',
    [switch]$SkipExeBuild,
    [string]$FixtureRoot = ''
)
$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent $PSScriptRoot
$buildRoot = Join-Path $repo 'build/pc_installer'
if (-not $Compiler) { $Compiler = Join-Path $buildRoot 'tools/inno-6.7.3/ISCC.exe' }
if (-not (Test-Path -LiteralPath $Compiler -PathType Leaf)) {
    throw 'Offline compiler missing. Supply an existing trusted Inno Setup 6.7.3 ISCC.exe with -Compiler.'
}
$Compiler = (Resolve-Path -LiteralPath $Compiler).Path
$signature = Get-AuthenticodeSignature -FilePath $Compiler
$compilerHash = (Get-FileHash -LiteralPath $Compiler -Algorithm SHA256).Hash
if ($signature.Status -ne 'Valid' -or $signature.SignerCertificate.Subject -notmatch '^CN=Pyrsys B\.V\.,' -or
    $compilerHash -ne '0A8757031B33777E4C9CBFFEE40F11A5062B36D25CBE144C1DB73B6102B80AD7') {
    throw 'Existing compiler publisher, signature or pinned binary hash validation failed.'
}
if (-not $SkipExeBuild) { & (Join-Path $PSScriptRoot 'build_exe.ps1') -Name eyepqc-1.2.1 }
$exe = Join-Path $repo 'build/pc_cli/dist/eyepqc-1.2.1.exe'
if (-not (Test-Path -LiteralPath $exe -PathType Leaf)) { throw 'Build eyepqc-1.2.1.exe first.' }
& $exe --version
if ($LASTEXITCODE -ne 0) { throw 'EXE smoke test failed.' }
$outputDirectory = Join-Path $buildRoot 'dist'
$defines = @("/DAppExecutable=$exe", "/DOutputDirectory=$outputDirectory")
if ($FixtureRoot) {
    if (-not [System.IO.Path]::IsPathRooted($FixtureRoot) -or $FixtureRoot.Contains("'")) {
        throw 'FixtureRoot must be an absolute isolated path without single quotes.'
    }
    $defines += '/DFixtureRoot=' + [System.IO.Path]::GetFullPath($FixtureRoot)
}
& $Compiler @defines (Join-Path $PSScriptRoot 'installer/eyepqc.iss')
if ($LASTEXITCODE -ne 0) { throw 'Setup compilation failed.' }
$name = if ($FixtureRoot) { 'EYEPQC-Setup-1.2.1-fixture.exe' } else { 'EYEPQC-Setup-1.2.1.exe' }
Get-FileHash -LiteralPath (Join-Path $buildRoot "dist/$name") -Algorithm SHA256
Write-Host 'Offline setup built. No materials bundled and no application installation performed.'
