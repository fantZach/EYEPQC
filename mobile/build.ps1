param(
    [string]$Jdk=$env:JAVA_HOME,
    [string]$Sdk=$env:ANDROID_HOME,
    [string]$Gradle='gradle',
    [ValidateSet('Debug','Release')][string]$Variant='Debug',
    [string]$TrustCaFile='',
    [string]$InitScript='',
    [switch]$RequireSigned,
    [switch]$Offline,
    [string]$OutputDirectory=''
)
$ErrorActionPreference='Stop'
if(-not $Jdk -or -not (Test-Path (Join-Path $Jdk 'bin/java.exe'))){throw 'Set -Jdk to JDK 17+.'}
if(-not $Sdk -or -not (Test-Path (Join-Path $Sdk 'platforms/android-35/android.jar'))){throw 'Set -Sdk to an Android SDK with platforms;android-35 and build-tools;35.0.0 installed.'}
if($RequireSigned -and $Variant -ne 'Release'){throw 'RequireSigned is release-only.'}
$signingNames=@('EYEPQC_ANDROID_KEYSTORE','EYEPQC_ANDROID_KEY_ALIAS','EYEPQC_ANDROID_STORE_PASSWORD','EYEPQC_ANDROID_KEY_PASSWORD')
$signingValues=@($signingNames | ForEach-Object { [Environment]::GetEnvironmentVariable($_) })
$signed=($signingValues.Where({$_}).Count -eq 4)
if($signingValues.Where({$_}).Count -notin @(0,4)){throw 'Provide all four release signing environment values, or none.'}
if($RequireSigned -and -not $signed){throw 'Release signing material is missing; no debug-signing fallback.'}
if($OutputDirectory){
    if(-not [IO.Path]::IsPathRooted($OutputDirectory) -or (Test-Path -LiteralPath $OutputDirectory)){throw 'OutputDirectory must be a new absolute directory; no overwrite.'}
    $outputParent=Split-Path -Parent $OutputDirectory
    if(-not (Test-Path -LiteralPath $outputParent -PathType Container)){throw 'OutputDirectory parent must already exist.'}
}
$oldJava=$env:JAVA_HOME;$oldSdk=$env:ANDROID_HOME
try{
    $env:JAVA_HOME=$Jdk;$env:ANDROID_HOME=$Sdk
    $arguments=@('--no-daemon','-p',$PSScriptRoot,":app:assemble$Variant")
    if($Offline){$arguments+='--offline'}
    if($InitScript){$arguments+=@('--init-script',(Resolve-Path -LiteralPath $InitScript).Path)}
    if($TrustCaFile){$arguments+='-PeyepqcTrustCaFile='+$TrustCaFile}
    & $Gradle @arguments
    if($LASTEXITCODE -ne 0){throw 'APK build failed. No signing secrets should be included in diagnostic reports.'}
    $name=if($Variant -eq 'Debug'){'app-debug.apk'}elseif($signed){'app-release.apk'}else{'app-release-unsigned.apk'}
    $apk=Join-Path $PSScriptRoot ('app/build/outputs/apk/'+$Variant.ToLowerInvariant()+'/'+$name)
    $projectLicense=Join-Path (Split-Path -Parent $PSScriptRoot) 'LICENSE'
    Copy-Item -LiteralPath $projectLicense -Destination (Join-Path (Split-Path -Parent $apk) 'LICENSE')
    $signer=Join-Path $Sdk 'build-tools/35.0.0/apksigner.bat'
    $aapt=Join-Path $Sdk 'build-tools/35.0.0/aapt.exe'
    $badging=& $aapt dump badging $apk
    if($LASTEXITCODE -ne 0){throw 'Cannot inspect APK version.'}
    $version=[regex]::Match(($badging -join "`n"),"versionName='([^']+)'").Groups[1].Value
    if(-not $version){throw 'APK version is missing.'}
    $manifest=& $aapt dump xmltree $apk AndroidManifest.xml
    if($LASTEXITCODE -ne 0){throw 'Cannot inspect APK manifest.'}
    if($Variant -eq 'Release'){
        if(($manifest -join "`n") -match 'android:debuggable[^\r\n]*0xffffffff'){throw 'Release APK must not be debuggable.'}
        if(($manifest -join "`n") -notmatch 'android:usesCleartextTraffic[^\r\n]*0x0'){throw 'Release APK must prohibit cleartext traffic.'}
    }
    $certificate=$null
    if($Variant -eq 'Debug' -or $signed){
        $verification=& $signer verify --min-sdk-version 26 --print-certs $apk
        if($LASTEXITCODE -ne 0){throw 'APK signature verification failed.'}
        if($Variant -eq 'Release' -and ($verification -join "`n") -match 'certificate DN:.*CN=Android Debug'){throw 'Debug signer is not an acceptable release signer.'}
        $certificate=($verification | Where-Object {$_ -match '^Signer #1 certificate SHA-256 digest:'}) -replace '^Signer #1 certificate SHA-256 digest:\s*',''
    }
    $trust=if($TrustCaFile){'explicit-deployment-ca-plus-system'}else{'system-only'}
    $metadata=[ordered]@{component='android';version=$version;variant=$Variant.ToLowerInvariant();signing=if($Variant -eq 'Debug'){'debug'}elseif($signed){'external-release-key'}else{'unsigned'};sha256=(Get-FileHash -LiteralPath $apk -Algorithm SHA256).Hash.ToLowerInvariant();signer_sha256=$certificate;tls_trust=$trust;user_acceptance='pending';production_security_accepted=$false}
    if($OutputDirectory){
        New-Item -ItemType Directory -Path $OutputDirectory -ErrorAction Stop | Out-Null
        $label=if($Variant -eq 'Debug'){'debug'}elseif($signed){'release-signed'}else{'release-unsigned'}
        $target=Join-Path $OutputDirectory ('EYEPQC-Android-'+$version+'-'+$label+'.apk')
        [IO.File]::Copy($apk,$target,$false)
        [IO.File]::Copy($projectLicense,(Join-Path $OutputDirectory 'LICENSE'),$false)
        $metadata.apk=Split-Path -Leaf $target
        [IO.File]::WriteAllText((Join-Path $OutputDirectory 'manifest.json'),($metadata | ConvertTo-Json),[Text.UTF8Encoding]::new($false))
    }
    $metadata | ConvertTo-Json
}finally{$env:JAVA_HOME=$oldJava;$env:ANDROID_HOME=$oldSdk}
