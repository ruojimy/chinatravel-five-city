[CmdletBinding()]
param(
    [string]$Out = (Join-Path $env:LOCALAPPDATA 'ShortTrip\8795'),
    [string]$UpstreamZip,
    [string]$Python,
    [switch]$UseConfiguredDatabase,
    [switch]$VerifySourceOnly
)
$ErrorActionPreference = 'Stop'
$version = 'workbench-8795-20261123'
$zipName = 'ShortTrip-Workbench-8795-20261123.zip'
$expected = 'e16568379d614757ac4f4e2662bc20a883d45d169a91ea1bfdc1cad73831cfc1'
$snapshots = @('5e0ee8a', '6de12f4')
$archive = 'result/experiments/P042_search_budget/paired_release/shanghai_hangzhou/new'
if ($Python) {
    $pythonExe = (Get-Command $Python -CommandType Application -ErrorAction Stop).Source
} elseif ($specific = Get-Command python3.12.exe -CommandType Application -ErrorAction SilentlyContinue) {
    $pythonExe = $specific.Source
} elseif ($launcher = Get-Command py.exe -CommandType Application -ErrorAction SilentlyContinue) {
    $pythonExe = & $launcher.Source -3.12 -c 'import sys; print(sys.executable)'
    if ($LASTEXITCODE -ne 0) { throw '请安装 64 位 Python 3.12。' }
} else {
    $pythonExe = (Get-Command python.exe -CommandType Application -ErrorAction Stop).Source
}
& $pythonExe -c 'import sys; sys.exit(sys.version_info[:2] != (3, 12) or sys.maxsize <= 2**32)'
if ($LASTEXITCODE -ne 0) { throw '请使用 64 位 Python 3.12，可用 -Python 指定 python.exe 的路径。' }

if ($UpstreamZip) { $UpstreamZip = (Resolve-Path -LiteralPath $UpstreamZip).Path }
$Out = $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($Out)
$temp = (Resolve-Path -LiteralPath $env:TEMP).Path
$stage = Join-Path $temp ('st-' + [guid]::NewGuid().ToString('N').Substring(0, 10))
$null = New-Item -ItemType Directory -Path $stage
$oldPythonPath = $env:PYTHONPATH
$oldNoBytecode = $env:PYTHONDONTWRITEBYTECODE
try {
    $sourceZip = Join-Path $stage $zipName
    if ($UpstreamZip) {
        Copy-Item -LiteralPath $UpstreamZip -Destination $sourceZip
    } else {
        $uri = "https://github.com/ccc-cccst/travel-assistant/releases/download/$version/$zipName"
        & curl.exe --fail --location --silent --show-error --retry 3 --output $sourceZip $uri
        if ($LASTEXITCODE -ne 0) { throw '上游下载失败，可下载后通过 -UpstreamZip 指定 ZIP。' }
    }
    if ((Get-FileHash -LiteralPath $sourceZip -Algorithm SHA256).Hash -ne $expected) {
        throw '上游 ZIP 的 SHA-256 与固定发布记录不符。'
    }
    & $pythonExe -m zipfile -e $sourceZip $stage
    if ($LASTEXITCODE -ne 0) { throw '上游 ZIP 解压失败。' }
    $source = Join-Path $stage 'ShortTrip-Workbench-8795'
    foreach ($relative in @(
        "combined version_personalized/$archive",
        'shorttrip-webui/shorttrip-webui',
        'ShortTrip/artifacts/data/5e0ee8a',
        'ShortTrip/artifacts/data/6de12f4'
    )) {
        if (!(Test-Path -LiteralPath (Join-Path $source $relative) -PathType Container)) {
            throw "上游发布缺少 $relative"
        }
    }
    Write-Host "上游工作台与两份快照已验证，SHA-256 $expected"
    if ($VerifySourceOnly) { return }

    $scripts = Join-Path $PSScriptRoot 'scripts'
    if (!$UseConfiguredDatabase) {
        & (Join-Path $scripts 'Initialize-GaussDB.ps1')
    }
    & (Join-Path $scripts 'New-ShortTripRelease.ps1') -Upstream $source -Out $Out `
        -Version $version -Snapshots $snapshots -Archive $archive -Python $pythonExe

    $release = Join-Path $Out 'ShortTrip'
    $venv = Join-Path $release 'combined version_personalized\.venv\Scripts\python.exe'
    $env:PYTHONPATH = $release
    $env:PYTHONDONTWRITEBYTECODE = '1'
    & $venv -X utf8 -m shorttrip_cloud materialize $snapshots[-1] --to (Join-Path $release 'ShortTrip/artifacts/data')
    if ($LASTEXITCODE -ne 0) { throw '从 openGauss 还原数据失败。' }
    & $venv -X utf8 (Join-Path $scripts 'import_v20_city_catalog.py') --release $release --report (Join-Path $Out 'catalog-v20.json') | Out-Null
    if ($LASTEXITCODE -ne 0) { throw '西安与厦门基础目录导入失败。' }
    $hasReferences = @'
from shorttrip_cloud.__main__ import connect
_, db = connect()
try:
    receipt = db.one("SELECT 1 FROM st_meta WHERE key=%s", ("city_catalog_v20_references",))
    print("present" if receipt else "missing")
finally:
    db.close()
'@ | & $venv -X utf8 -
    if ($LASTEXITCODE -ne 0 -or $hasReferences -notin @('present', 'missing')) {
        throw '读取目录补充批次状态失败。'
    }
    if ($hasReferences -eq 'missing') {
        & $venv -X utf8 (Join-Path $scripts 'extend_v20_city_references.py') --release $release --report (Join-Path $Out 'catalog-v20-references.json') | Out-Null
        if ($LASTEXITCODE -ne 0) { throw '免费景点等参考目录导入失败。' }
    } else {
        Write-Host '已保留数据库现有的参考目录批次。'
    }
    Write-Host ("安装完成，启动入口 {0}" -f (Join-Path $release 'Start.cmd'))
} finally {
    $env:PYTHONPATH = $oldPythonPath
    $env:PYTHONDONTWRITEBYTECODE = $oldNoBytecode
    if (Test-Path -LiteralPath $stage -PathType Container) {
        $resolvedStage = (Resolve-Path -LiteralPath $stage).Path
        if ((Split-Path -Parent $resolvedStage) -eq $temp -and (Split-Path -Leaf $resolvedStage) -match '^st-[a-f0-9]{10}$') {
            Remove-Item -LiteralPath $resolvedStage -Recurse -Force
        }
    }
}
