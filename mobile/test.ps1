param([string]$Jdk = $env:JAVA_HOME, [switch]$FetchDependencies)
$ErrorActionPreference = 'Stop'
$repo = Split-Path $PSScriptRoot -Parent
$toolsDir = Join-Path $repo 'build/mobile_toolchain'
New-Item -ItemType Directory -Force $toolsDir | Out-Null
if (-not $Jdk) {
    $compiler = Get-Command javac -ErrorAction SilentlyContinue
    if ($compiler) { $Jdk = Split-Path (Split-Path $compiler.Source -Parent) -Parent }
}
if (-not $Jdk -or -not (Test-Path (Join-Path $Jdk 'bin/javac.exe'))) { throw 'Set -Jdk to a JDK 17+ directory.' }
$dependencies = @(
    @('bcprov.jar','org/bouncycastle/bcprov-jdk18on/1.81/bcprov-jdk18on-1.81.jar','249f396412b0c0ce67f25c8197da757b241b8be3ec4199386c00704a2457459b'),
    @('okhttp.jar','com/squareup/okhttp3/okhttp/4.12.0/okhttp-4.12.0.jar','b1050081b14bb7a3a7e55a4d3ef01b5dcfabc453b4573a4fc019767191d5f4e0'),
    @('okio.jar','com/squareup/okio/okio-jvm/3.6.0/okio-jvm-3.6.0.jar','67543f0736fc422ae927ed0e504b98bc5e269fda0d3500579337cb713da28412'),
    @('kotlin.jar','org/jetbrains/kotlin/kotlin-stdlib/1.8.21/kotlin-stdlib-1.8.21.jar','042a1cd1ac976cdcfe5eb63f1d8e0b0b892c9248e15a69c8cfba495d546ea52a'),
    @('gson.jar','com/google/code/gson/gson/2.11.0/gson-2.11.0.jar','57928d6e5a6edeb2abd3770a8f95ba44dce45f3b23b7a9dc2b309c581552a78b')
)
$jars = foreach ($dep in $dependencies) {
    $target = Join-Path $toolsDir $dep[0]
    if (-not (Test-Path $target)) {
        if (-not $FetchDependencies) { throw "Missing $target; use -FetchDependencies once to download from Maven Central." }
        & curl.exe --noproxy '*' --fail --location --connect-timeout 20 --max-time 180 --output $target "https://repo.maven.apache.org/maven2/$($dep[1])"
        if ($LASTEXITCODE -ne 0) { throw "Download failed: $($dep[0])" }
    }
    if ((Get-FileHash $target -Algorithm SHA256).Hash.ToLowerInvariant() -ne $dep[2]) { throw "Dependency SHA256 mismatch: $target" }
    $target
}
$classes = Join-Path $toolsDir 'classes'
New-Item -ItemType Directory -Force $classes | Out-Null
$sources = @((Get-ChildItem (Join-Path $PSScriptRoot 'app/src/main/java/org/eyepqc/mobile/*.java') | Where-Object Name -ne 'MainActivity.java').FullName)
$sources += @((Get-ChildItem (Join-Path $PSScriptRoot 'test/org/eyepqc/mobile/*.java')).FullName)
$classpath = $jars -join ';'
& (Join-Path $Jdk 'bin/javac.exe') --release 8 -Xlint:-options -cp $classpath -d $classes $sources
if ($LASTEXITCODE -ne 0) { throw 'Java compilation failed.' }
& (Join-Path $Jdk 'bin/java.exe') -cp "$classes;$classpath" org.eyepqc.mobile.CoreTest $repo
if ($LASTEXITCODE -ne 0) { throw 'Android core tests failed.' }
& (Join-Path $Jdk 'bin/java.exe') -cp "$classes;$classpath" org.eyepqc.mobile.PairingConfigTest
if ($LASTEXITCODE -ne 0) { throw 'Pairing JSON tests failed.' }
