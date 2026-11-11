# Run the Act agent over a list of uids, one OS process per uid (parallel jobs).
param(
    [Parameter(Mandatory = $true)][string[]]$Uids,
    [string]$Split = 'easy_short',
    [string]$Agent = 'Act',
    [string]$Llm = 'deepseek-flash',
    [int]$TimeoutSec = 900
)

$ErrorActionPreference = 'Continue'
$here = Split-Path -Parent $PSCommandPath
$root = Resolve-Path (Join-Path $here '..\ChinaTravel')
Set-Location $root

$env:PYTHONUTF8 = '1'
Remove-Item Env:HTTP_PROXY, Env:HTTPS_PROXY, Env:ALL_PROXY, Env:NO_PROXY, Env:http_proxy, Env:https_proxy, Env:all_proxy, Env:no_proxy -ErrorAction SilentlyContinue
$env:OPENAI_API_KEY = (Get-Content (Join-Path $here '..\.secrets\deepseek.key') -Raw).Trim()
$env:OPENAI_BASE_URL = 'https://api.deepseek.com'

$py = Join-Path $here '..\.venv\Scripts\python.exe'
$logDir = Join-Path $root 'logs\llm_pure'
New-Item -ItemType Directory -Force -Path $logDir | Out-Null

$jobs = foreach ($u in $Uids) {
    Start-Job -Name "act_$u" -ArgumentList $u, $root, $py, $LogDir, $Split, $Agent, $Llm -ScriptBlock {
        param($u, $root, $py, $logDir, $split, $agent, $llm)
        Set-Location $root
        $log = Join-Path $logDir "$u.log"
        $sw = [System.Diagnostics.Stopwatch]::StartNew()
        & $py run_exp.py --splits $split --index $u --agent $agent --llm $llm *>&1 |
            Out-File -FilePath $log -Encoding utf8
        $code = $LASTEXITCODE
        $sw.Stop()
        [pscustomobject]@{
            uid     = $u
            exit    = $code
            seconds = [math]::Round($sw.Elapsed.TotalSeconds, 1)
            log     = $log
        }
    }
}

$done = $jobs | Wait-Job -Timeout $TimeoutSec
$results = $jobs | Receive-Job -Wait -AutoRemoveJob
$results | Sort-Object uid | Format-Table -AutoSize
Write-Host ("finished jobs: " + @($done).Count + " / " + @($jobs).Count)
