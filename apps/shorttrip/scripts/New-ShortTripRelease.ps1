[CmdletBinding()]
param(
    # Upstream ShortTrip folder: contains "combined version_personalized", "shorttrip-webui", "ShortTrip/artifacts/data".
    [Parameter(Mandatory)][string]$Upstream,
    # Output folder; the PC release is written to <Out>\ShortTrip.
    [Parameter(Mandatory)][string]$Out,
    # Release name shown in the app and stored in st_release, e.g. P043.
    [Parameter(Mandatory)][string]$Version,
    # Data snapshots in dependency order (each depends on the previous one). Default: detected.
    [string[]]$Snapshots,
    # Personalized archive relative to the planner folder. Default: read from Start-ShortTrip.ps1.
    [string]$Archive,
    [string]$Python = 'python3.12.exe',
    [string]$PipIndex = 'https://pypi.org/simple',
    [switch]$SkipImport,
    [switch]$SkipVenv
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
$Upstream = (Resolve-Path -LiteralPath $Upstream).Path
$planner = Join-Path $Upstream 'combined version_personalized'
$webui = Join-Path $Upstream 'shorttrip-webui\shorttrip-webui'
$data = Join-Path $Upstream 'ShortTrip\artifacts\data'
foreach ($required in @($planner, $webui, $data)) {
    if (!(Test-Path -LiteralPath $required -PathType Container)) { throw "上游目录缺少 $required" }
}
$release = Join-Path $Out 'ShortTrip'
New-Item -ItemType Directory -Force $release | Out-Null
$release = (Resolve-Path -LiteralPath $release).Path

# ---------------------------------------------------------------- 1. copy code (no data, no caches)
Write-Host '== 复制程序（不含数据快照）'
$excludeDirs = @('.venv', '__pycache__', '.pytest_cache', 'workbench_runtime', 'server_logs', 'api_errors',
                 'cli_errors', 'workbench_edits', 'workbench_feedback', 'route_cache', $data)
robocopy $Upstream $release /E /NFL /NDL /NJH /NJS /NP /XD @excludeDirs /XF '*.pyc' 'store.json' 'feedback.jsonl' | Out-Null
if ($LASTEXITCODE -ge 8) { throw "复制失败（robocopy $LASTEXITCODE）" }
robocopy (Join-Path $skill 'server\shorttrip_cloud') (Join-Path $release 'shorttrip_cloud') /MIR /NFL /NDL /NJH /NJS /NP /XD __pycache__ | Out-Null
if ($LASTEXITCODE -ge 8) { throw "复制 shorttrip_cloud 失败（robocopy $LASTEXITCODE）" }
Copy-Item -LiteralPath (Join-Path $skill 'server\start_server.py') -Destination $release -Force
Copy-Item -LiteralPath (Join-Path $skill 'server\Start-Server.cmd') -Destination $release -Force
Copy-Item -LiteralPath (Join-Path $skill 'server\Start-Server.cmd') -Destination (Join-Path $release 'Start.cmd') -Force
Copy-Item -LiteralPath (Join-Path $skill 'server\README-服务器.md') -Destination $release -Force
New-Item -ItemType Directory -Force (Join-Path $release 'ShortTrip\artifacts\data') | Out-Null

# ---------------------------------------------------------------- 2. release manifest
if (!$Snapshots) {
    # The original-format install.json ({"source": ...}) is the base; newer profiles depend on it.
    $dirs = Get-ChildItem -LiteralPath $data -Directory | Where-Object { Test-Path (Join-Path $_.FullName 'install.json') }
    $base = $dirs | Where-Object { (Get-Content -Raw (Join-Path $_.FullName 'install.json') | ConvertFrom-Json).PSObject.Properties['source'] }
    $Snapshots = @($base.Name) + @($dirs | Where-Object { $_.Name -notin $base.Name } | Sort-Object LastWriteTime | ForEach-Object Name)
}
if (!$Archive) {
    $launcher = Get-Content -Raw (Join-Path $webui 'Start-ShortTrip.ps1')
    if ($launcher -match "Join-Path \`$planner '(result/experiments/[^']+)'") { $Archive = $Matches[1] }
}
$publicJobs = @(Get-ChildItem -LiteralPath (Join-Path $planner 'result\manual') -Directory -ErrorAction SilentlyContinue |
                Where-Object Name -match '^[a-f0-9]{32}$' | ForEach-Object Name)
$publicRequests = @(Get-ChildItem -LiteralPath (Join-Path $planner 'result\tripspec') -Directory -ErrorAction SilentlyContinue |
                    Where-Object Name -match '^[a-f0-9]{32}$' | ForEach-Object Name)
$manifest = [ordered]@{
    version = $Version; built = (Get-Date).ToString('s'); upstream = $Upstream
    snapshots = @($Snapshots); archive = $Archive
    public_jobs = $publicJobs; public_requests = $publicRequests
}
$manifest | ConvertTo-Json -Depth 4 | Set-Content -Encoding utf8 (Join-Path $release 'shorttrip_release.json')
Write-Host "快照顺序：$($Snapshots -join ' -> ')；示例任务 $($publicJobs.Count) 个"
$longest = (Get-ChildItem -LiteralPath $data -Recurse -File | ForEach-Object { $_.FullName.Length - $data.Length } | Measure-Object -Maximum).Maximum
$restoredLongest = (Join-Path $release 'ShortTrip\artifacts\data').Length + $longest
$longPaths = (Get-ItemProperty 'HKLM:\SYSTEM\CurrentControlSet\Control\FileSystem' -Name LongPathsEnabled -ErrorAction SilentlyContinue).LongPathsEnabled
if ($restoredLongest -gt 259 -and $longPaths -ne 1) {
    Write-Warning "还原后最长路径 $restoredLongest 字符，超过 Windows 259 字符上限。请换更短的 -Out 目录（例如 D:\ShortTrip-$Version），或开启 LongPathsEnabled。"
}

# ---------------------------------------------------------------- 3. Python environment
$venvPython = Join-Path $release 'combined version_personalized\.venv\Scripts\python.exe'
if (!$SkipVenv) {
    if (!(Test-Path -LiteralPath $venvPython)) {
        & (Get-Command $Python).Source -m venv (Join-Path $release 'combined version_personalized\.venv')
    }
    $requirements = @('-r', (Join-Path $release 'combined version_personalized\requirements.txt'),
                      '-r', (Join-Path $release 'shorttrip_cloud\requirements-cloud.txt'))
    Invoke-Native { & $venvPython -m pip install --disable-pip-version-check -q --index-url $PipIndex @requirements }
    if ($LASTEXITCODE -ne 0) { throw 'pip 安装依赖失败。' }
    # Keep the launcher and the completed installation on the same requirements.
    $stamp = Join-Path $release 'combined version_personalized\.venv\shorttrip-requirements.txt'
    $installed = [IO.File]::ReadAllBytes($requirements[1]) + [IO.File]::ReadAllBytes($requirements[3])
    [IO.File]::WriteAllBytes($stamp, $installed)
}

# ---------------------------------------------------------------- 4. data into GaussDB
$env:PYTHONPATH = $release
Invoke-Native { & $venvPython -X utf8 -m shorttrip_cloud init-db }
if ($LASTEXITCODE -ne 0) { throw '数据库初始化失败。先运行 Initialize-GaussDB.ps1。' }
if (!$SkipImport) {
    $previous = $null
    foreach ($id in $Snapshots) {
        $arguments = @('-X', 'utf8', '-m', 'shorttrip_cloud', 'import-snapshot', (Join-Path $data $id), '--id', $id,
                       '--note', "$Version")
        if ($previous) { $arguments += @('--depends-on', $previous) }
        Invoke-Native { & $venvPython @arguments }
        if ($LASTEXITCODE -ne 0) { throw "快照 $id 入库失败。" }
        $previous = $id
    }
}
Invoke-Native { & $venvPython -X utf8 -m shorttrip_cloud register-release $Version --snapshots ($Snapshots -join ',') --notes "PC release $release" }
if ($LASTEXITCODE -ne 0) { throw '登记发布失败。' }

$size = (Get-ChildItem -LiteralPath $release -Recurse -File | Where-Object FullName -notmatch '\\\.venv\\' | Measure-Object Length -Sum).Sum
Write-Host ("== 完成：{0}（不含 .venv 约 {1:N1} MB；数据在 GaussDB，首次启动自动还原）" -f $release, ($size / 1MB))
