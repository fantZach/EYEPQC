param([string]$Jdk=$env:JAVA_HOME,[string]$Sdk=$env:ANDROID_HOME,[string]$Gradle='gradle')
$ErrorActionPreference='Stop'
if(-not $Jdk -or -not (Test-Path (Join-Path $Jdk 'bin/java.exe'))){throw 'Set -Jdk to JDK 17+.'}
if(-not $Sdk -or -not (Test-Path (Join-Path $Sdk 'platforms/android-35/android.jar'))){throw 'Set -Sdk to an Android SDK with platforms;android-35 and build-tools;35.0.0 installed.'}
$env:JAVA_HOME=$Jdk
$env:ANDROID_HOME=$Sdk
& $Gradle --no-daemon -p $PSScriptRoot :app:assembleDebug
if($LASTEXITCODE -ne 0){throw 'APK build failed.'}
Get-Item (Join-Path $PSScriptRoot 'app/build/outputs/apk/debug/app-debug.apk')
