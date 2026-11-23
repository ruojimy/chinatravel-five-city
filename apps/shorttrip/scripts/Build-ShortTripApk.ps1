[CmdletBinding()]
param(
    # Output folder (same -Out as New-ShortTripRelease.ps1). The Gradle project goes to <Out>\android.
    [Parameter(Mandatory)][string]$Out,
    [Parameter(Mandatory)][string]$Version,
    # Must increase for every APK that should install over the previous one (P042 thin client = 7).
    [Parameter(Mandatory)][int]$VersionCode,
    [string]$VersionName = '2.0',
    # Address baked in as the default; users can change it in the app. Default: this PC's LAN address.
    [string]$ServerUrl,
    [int]$Port = 8790,
    [string]$Gradle,
    [string]$JavaHome,
    [switch]$DebugBuild
)
$ErrorActionPreference = 'Stop'

function Invoke-Native([scriptblock]$Command) {
    # Windows PowerShell 5.1 turns native stderr (javac/pip warnings) into errors when output is
    # redirected; with 'Stop' that aborts a successful build. Judge native tools by exit code only.
    $saved = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try { & $Command 2>&1 | ForEach-Object { "$_" } } finally { $ErrorActionPreference = $saved }
}
$skill = Split-Path -Parent $PSScriptRoot
$Out = (New-Item -ItemType Directory -Force $Out).FullName
$project = Join-Path $Out 'android'

# ---------------------------------------------------------------- toolchain
if (!$Gradle) {
    $Gradle = (Get-Command gradle.bat, gradle -ErrorAction SilentlyContinue | Select-Object -First 1).Source
    if (!$Gradle) {
        $Gradle = Get-ChildItem (Join-Path $env:USERPROFILE '.gradle\wrapper\dists') -Filter gradle.bat -Recurse -ErrorAction SilentlyContinue |
                  Where-Object FullName -match '\\bin\\gradle\.bat$' | Sort-Object FullName -Descending | Select-Object -First 1 -ExpandProperty FullName
    }
}
if (!$Gradle) { throw '找不到 Gradle。用 -Gradle 指定 gradle.bat（8.11 以上）。' }
if (!$JavaHome) {
    $JavaHome = @($env:JAVA_HOME) + @(Get-ChildItem 'C:\Program Files\Java', 'C:\Program Files\Eclipse Adoptium', 'C:\Program Files\Microsoft' -Directory -Filter 'jdk*' -ErrorAction SilentlyContinue | Sort-Object Name -Descending | ForEach-Object FullName) |
                Where-Object { $_ -and (Test-Path -LiteralPath (Join-Path $_ 'bin\javac.exe')) } | Select-Object -First 1
}
if (!$JavaHome) { throw '找不到 JDK 17+。用 -JavaHome 指定（JAVA_HOME 不能指向安装包 .exe）。' }
$sdk = @($env:ANDROID_HOME, $env:ANDROID_SDK_ROOT, (Join-Path $env:LOCALAPPDATA 'Android\Sdk'), (Join-Path $env:USERPROFILE 'android-sdk')) |
       Where-Object { $_ -and (Test-Path -LiteralPath (Join-Path $_ 'platforms')) } | Select-Object -First 1
if (!$sdk) { throw '找不到 Android SDK（ANDROID_HOME）。' }

if (!$PSBoundParameters.ContainsKey('ServerUrl')) {
    $ip = Get-NetIPConfiguration | Where-Object { $_.IPv4DefaultGateway -and $_.NetAdapter.Status -eq 'Up' } |
          ForEach-Object { $_.IPv4Address.IPAddress } | Where-Object { $_ -notmatch '^(169\.254|198\.18)\.' } | Select-Object -First 1
    $ServerUrl = if ($ip) { "http://${ip}:$Port" } else { '' }
}
Write-Host "Gradle: $Gradle`nJDK: $JavaHome`nSDK: $sdk`n默认服务器: $(if ($ServerUrl) { $ServerUrl } else { '（首次打开时填写）' })"

# ---------------------------------------------------------------- project from template
robocopy (Join-Path $skill 'android-client') $project /MIR /NFL /NDL /NJH /NJS /NP /XD build .gradle /XF local.properties | Out-Null
if ($LASTEXITCODE -ge 8) { throw "复制安卓模板失败（robocopy $LASTEXITCODE）" }
"sdk.dir=$($sdk -replace '\\', '\\')" | Set-Content -Encoding ascii (Join-Path $project 'local.properties')

$env:JAVA_HOME = $JavaHome
$options = @('--console=plain', "-PshorttripVersionCode=$VersionCode", "-PshorttripVersionName=$VersionName",
             "-PshorttripServer=$ServerUrl", "-PshorttripRelease=$Version")
if ($env:HTTPS_PROXY) {
    $proxy = [Uri]$env:HTTPS_PROXY
    $options += "-Dhttps.proxyHost=$($proxy.Host)", "-Dhttps.proxyPort=$($proxy.Port)"
}
Push-Location $project
try {
    if ($DebugBuild) {
        Invoke-Native { & $Gradle @options ':app:assembleDebug' }
        $apk = Join-Path $project 'app\build\outputs\apk\debug\app-debug.apk'
    } else {
        # Same key as earlier ShortTrip APKs, so a new version installs over the old one.
        $signing = Join-Path $env:LOCALAPPDATA 'ShortTrip\signing'
        New-Item -ItemType Directory -Force $signing | Out-Null
        $env:SHORTTRIP_KEYSTORE = Join-Path $signing 'shorttrip.p12'
        $sealed = Join-Path $signing 'shorttrip.dpapi'
        if (!(Test-Path -LiteralPath $env:SHORTTRIP_KEYSTORE)) {
            $env:SHORTTRIP_STORE_PASSWORD = [Guid]::NewGuid().ToString('N') + [Guid]::NewGuid().ToString('N')
            & (Join-Path $JavaHome 'bin\keytool.exe') -genkeypair -alias shorttrip -keyalg RSA -keysize 3072 -sigalg SHA256withRSA `
                -validity 10000 -dname 'CN=ShortTrip Android' -storetype PKCS12 -keystore $env:SHORTTRIP_KEYSTORE `
                -storepass:env SHORTTRIP_STORE_PASSWORD -keypass:env SHORTTRIP_STORE_PASSWORD
            if ($LASTEXITCODE -ne 0) { throw '生成签名密钥失败。' }
            ConvertTo-SecureString $env:SHORTTRIP_STORE_PASSWORD -AsPlainText -Force | ConvertFrom-SecureString | Set-Content -LiteralPath $sealed
        } else {
            $secret = Get-Content -LiteralPath $sealed | ConvertTo-SecureString
            $env:SHORTTRIP_STORE_PASSWORD = [Net.NetworkCredential]::new('', $secret).Password
        }
        Invoke-Native { & $Gradle @options ':app:assembleRelease' }
        $apk = Join-Path $project 'app\build\outputs\apk\release\app-release.apk'
    }
    if ($LASTEXITCODE -ne 0) { throw "Gradle 构建失败（$LASTEXITCODE）。" }
} finally {
    Pop-Location
    Remove-Item Env:SHORTTRIP_STORE_PASSWORD -ErrorAction SilentlyContinue
    Remove-Item Env:SHORTTRIP_KEYSTORE -ErrorAction SilentlyContinue
}
$target = Join-Path $Out "ShortTrip-Android-$Version.apk"
Copy-Item -LiteralPath $apk -Destination $target -Force
Write-Host ("== APK：{0}（{1:N2} MB）" -f $target, ((Get-Item $target).Length / 1MB))

# Record the APK next to the PC release in GaussDB when the release exists.
$release = Join-Path $Out 'ShortTrip'
$python = Join-Path $release 'combined version_personalized\.venv\Scripts\python.exe'
if ((Test-Path -LiteralPath $python) -and (Test-Path -LiteralPath (Join-Path $release 'shorttrip_release.json'))) {
    $info = Get-Content -Raw (Join-Path $release 'shorttrip_release.json') | ConvertFrom-Json
    $env:PYTHONPATH = $release
    Invoke-Native { & $python -X utf8 -m shorttrip_cloud register-release $Version --snapshots ($info.snapshots -join ',') `
        --apk $target --version-code $VersionCode --server-url $ServerUrl --notes "PC release $release" }
}
