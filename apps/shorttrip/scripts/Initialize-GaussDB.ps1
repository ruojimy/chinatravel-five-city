[CmdletBinding()]
param(
    # Docker container running openGauss (enmotech/opengauss). Created on first use if missing.
    [string]$Container = 'opengauss',
    [int]$HostPort = 8888,
    [string]$DataDir = (Join-Path $env:USERPROFILE 'opengauss_data'),
    [string]$Database = 'shorttrip',
    [string]$User = 'shorttrip'
)
# Starts openGauss and creates the ShortTrip database/user once. The generated password goes to
# %LOCALAPPDATA%\ShortTrip\server.env (never into a release or the skill folder).
$ErrorActionPreference = 'Stop'

function Wait-Docker {
    for ($i = 0; $i -lt 60; $i++) {
        docker info --format '{{.ServerVersion}}' 2>$null | Out-Null
        if ($LASTEXITCODE -eq 0) { return }
        if ($i -eq 0) {
            $desktop = Join-Path $env:ProgramFiles 'Docker\Docker\Docker Desktop.exe'
            if (Test-Path -LiteralPath $desktop) { Start-Process -FilePath $desktop -WindowStyle Hidden; Write-Host '正在启动 Docker Desktop…' }
        }
        Start-Sleep -Seconds 3
    }
    throw 'Docker 未就绪，请手动启动 Docker Desktop 后重试。'
}

function Invoke-Gsql([string]$Sql, [string]$Db = 'postgres') {
    # SQL goes through stdin: nested quoting through PowerShell -> docker -> su -> gsql silently drops statements.
    $saved = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'  # gsql NOTICE lines on stderr are not failures
    try { $output = $Sql | docker exec -i $Container su - omm -c "gsql -d $Db -p 5432 -v ON_ERROR_STOP=1 -t -A" 2>&1 }
    finally { $ErrorActionPreference = $saved }
    if ($LASTEXITCODE -ne 0) { throw "gsql 执行失败：$($Sql.Split("`n")[0] -replace "PASSWORD '[^']*'", "PASSWORD '***'")" }
    $output | ForEach-Object { "$_" } | Where-Object { $_ -notmatch '^(NOTICE|WARNING)' }
}

Wait-Docker
$exists = docker ps -a --filter "name=^/$Container$" --format '{{.Names}}'
if (!$exists) {
    New-Item -ItemType Directory -Force $DataDir | Out-Null
    $admin = 'Og' + [guid]::NewGuid().ToString('N').Substring(0, 16) + '@1a'
    docker run -d --name $Container --restart unless-stopped --privileged=true -e "GS_PASSWORD=$admin" `
        -p "127.0.0.1:${HostPort}:5432" -v "${DataDir}:/var/lib/opengauss" enmotech/opengauss:latest | Out-Null
    if ($LASTEXITCODE -ne 0) { throw '无法创建 openGauss 容器。' }
    Write-Host "已创建容器 $Container（端口 $HostPort）。"
}
if ((docker inspect -f '{{.State.Running}}' $Container) -ne 'true') {
    docker start $Container | Out-Null
}
$ready = $false
for ($i = 0; $i -lt 90; $i++) {
    $saved = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        # The image briefly starts a setup server before replacing PID 1 with the persistent server.
        $process = docker exec $Container cat /proc/1/comm 2>$null
        if ($process -eq 'gaussdb') {
            $result = 'SELECT 1;' | docker exec -i $Container su - omm -c 'gsql -d postgres -p 5432 -t -A' 2>$null
            $ready = $LASTEXITCODE -eq 0 -and '1' -in @($result)
        }
    } finally {
        $ErrorActionPreference = $saved
    }
    if ($ready) { break }
    Start-Sleep -Seconds 2
}
if (!$ready) { throw "openGauss 在等待时间内未就绪，请检查 docker logs $Container。" }
$port = (docker port $Container 5432/tcp | Select-Object -First 1) -replace '.*:', ''
if (!$port) { throw "容器 $Container 没有映射 5432 端口。" }

$folder = Join-Path $env:LOCALAPPDATA 'ShortTrip'
$envFile = Join-Path $folder 'server.env'
New-Item -ItemType Directory -Force $folder | Out-Null
$hasUser = Invoke-Gsql "select count(*) from pg_user where usename = '$User';"
if ([int]($hasUser | Select-Object -Last 1) -eq 0) {
    $password = 'St' + [guid]::NewGuid().ToString('N').Substring(0, 18) + '@9Q'
    Invoke-Gsql "CREATE USER $User WITH PASSWORD '$password';" | Out-Null
    $lines = @("SHORTTRIP_DB_HOST=127.0.0.1", "SHORTTRIP_DB_PORT=$port", "SHORTTRIP_DB_NAME=$Database",
               "SHORTTRIP_DB_USER=$User", "SHORTTRIP_DB_PASSWORD=$password", "SHORTTRIP_DB_SCHEMA=$Database")
    if (Test-Path -LiteralPath $envFile) {
        $keep = Get-Content -LiteralPath $envFile | Where-Object { $_ -notmatch '^SHORTTRIP_DB_' }
        $lines = $keep + $lines
    }
    $lines | Set-Content -Encoding utf8 -LiteralPath $envFile
    Write-Host "已创建数据库用户 $User，连接信息写入 $envFile"
} elseif (!(Test-Path -LiteralPath $envFile)) {
    throw "数据库用户 $User 已存在，但找不到 $envFile。请补写连接信息（SHORTTRIP_DB_PASSWORD 等）。"
}
$hasDb = Invoke-Gsql "select count(*) from pg_database where datname = '$Database';"
if ([int]($hasDb | Select-Object -Last 1) -eq 0) {
    Invoke-Gsql "CREATE DATABASE $Database OWNER $User ENCODING 'UTF8' TEMPLATE template0;" | Out-Null
    Write-Host "已创建数据库 $Database"
}
Write-Host "openGauss 就绪：127.0.0.1:$port / $Database"
