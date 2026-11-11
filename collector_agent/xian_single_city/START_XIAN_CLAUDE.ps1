param(
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^xian_claude_[0-9]{8}_[0-9]{6}$')]
    [string]$RunId,
    [ValidatePattern('^xian_claude_[0-9]{8}_[0-9]{6}$')]
    [string]$ResumeFrom,
    [ValidateRange(1, 8)]
    [int]$MaxPasses = 4
)

$ErrorActionPreference = 'Stop'
$project = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..\..')).Path
Set-Location -LiteralPath $project

$utf8 = [System.Text.UTF8Encoding]::new($false)
[Console]::OutputEncoding = $utf8
$OutputEncoding = $utf8
$env:PYTHONIOENCODING = 'utf-8'
$env:OPENBLAS_NUM_THREADS = '4'
# The inherited effort override would also override the workers' effort.
Remove-Item Env:CLAUDE_CODE_EFFORT_LEVEL -ErrorAction SilentlyContinue
Remove-Item Env:CLAUDE_CODE_SUBAGENT_MODEL -ErrorAction SilentlyContinue
Remove-Item Env:CLAUDE_CODE_SUBAGENT_MODEL_FORCE -ErrorAction SilentlyContinue

$claude = (Get-Command claude.exe -CommandType Application | Select-Object -First 1).Source
$python = Join-Path $project '.venv\Scripts\python.exe'
$promptFile = Join-Path $PSScriptRoot 'XIAN_SINGLE_CITY_PROMPT.md'
$agentsFile = Join-Path $PSScriptRoot 'claude_agents.json'
$relativeOutput = "results/$RunId"
$outputDir = Join-Path $project $relativeOutput
$session = [guid]::NewGuid().ToString()
$sessionArguments = @('--session-id', $session)
$model = 'claude-sonnet-5-5'
$lockPath = Join-Path $project 'collector_agent\memory\xian_claude_terminal.lock'

if ($ResumeFrom) {
    $previousOutput = Join-Path $project "results\$ResumeFrom"
    if (-not (Test-Path -LiteralPath (Join-Path $previousOutput 'terminal_exit.json') -PathType Leaf)) {
        throw 'Previous launcher has no terminal exit receipt.'
    }
    $previousLaunch = Get-Content -LiteralPath (Join-Path $previousOutput 'launch.json') -Raw | ConvertFrom-Json
    $session = ([guid]$previousLaunch.session_id).ToString()
    $sessionArguments = @('--resume', $session)
}

$terminalLock = [System.IO.File]::Open($lockPath, 'OpenOrCreate', 'ReadWrite', 'None')
try {
    $check = 'import sqlite3; from pathlib import Path; p=Path("collector_agent/memory/agent.sqlite3"); db=sqlite3.connect(p.resolve().as_uri()+"?mode=ro",uri=True); active=db.execute("select id from scheduled_sessions where state=?",("active",)).fetchall(); pending=db.execute("select id from requests where status=?",("reserved",)).fetchall(); assert not active and not pending, (active,pending)'
    & $python -c $check
    if ($LASTEXITCODE -ne 0) { throw 'An existing collection session or pending request needs review.' }
    if (Test-Path -LiteralPath (Join-Path $outputDir 'launch.json')) {
        throw 'Use a new output run ID to preserve launch history.'
    }
    New-Item -ItemType Directory -Path $outputDir -Force | Out-Null

    $launch = @{
        run_id = $RunId
        session_id = $session
        resume_from = $ResumeFrom
        max_passes = $MaxPasses
        requested_model = $model
        requested_effort = 'medium'
        worker_agent = 'xian-collector'
        worker_model = $model
        worker_effort = 'low'
        launcher_pid = $PID
        started_at = [DateTimeOffset]::UtcNow.ToString('o')
        permission_mode = 'auto'
    }
    $launch | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $outputDir 'launch.json') -Encoding utf8
    $Host.UI.RawUI.WindowTitle = "Claude Code - Xi'an collection - $RunId"
    Write-Host "Claude Code | $model / medium | workers: $model / low"
    Write-Host "Run: $RunId"
    Write-Host "Output: $outputDir"

    $prompt = "本轮 run_id=$RunId，输出目录=$relativeOutput。下面是用户已授权的完整任务，请立即调用已注册的 xian-collector 子代理开工。"
    $prompt += [Environment]::NewLine + [IO.File]::ReadAllText($promptFile, $utf8)
    if ($ResumeFrom) {
        $prompt += [Environment]::NewLine + [IO.File]::ReadAllText((Join-Path $PSScriptRoot 'RESUME_XIAN.md'), $utf8)
        $prompt += [Environment]::NewLine + "前次已结束的成果目录为 results/$ResumeFrom。"
    }
    $arguments = @(
        '--print', '--verbose', '--output-format', 'stream-json', '--forward-subagent-text',
        '--model', $model, '--effort', 'medium', '--agents', $agentsFile,
        '--permission-mode', 'auto', '--name', $RunId,
        '--strict-mcp-config', '--mcp-config', '{"mcpServers":{}}'
    )
    $streamPath = Join-Path $outputDir 'claude_stream.jsonl'
    $errorPath = Join-Path $outputDir 'claude_stderr.log'
    $writer = [System.IO.StreamWriter]::new($streamPath, $false, $utf8)
    $writer.AutoFlush = $true
    try {
        $exitCode = 0
        $workState = 'checkpoint_limit'
        $previousSignature = $null
        $missingCheckpointRetryUsed = $false
        for ($pass = 1; $pass -le $MaxPasses; $pass++) {
            if (Test-Path -LiteralPath (Join-Path $outputDir 'STOP')) {
                $workState = 'user_stop_requested'
                break
            }
            $checkpointName = 'pass_{0:D2}.json' -f $pass
            $passPrompt = $prompt + [Environment]::NewLine + @"
本次启动器阶段号为 $pass。结束本阶段前写 $relativeOutput/$checkpointName。
JSON 字段为 run_id（$RunId）、pass（$pass）、state（checkpoint/completed/blocked）、ready_work（下一批可执行工单数组）、progress_artifact（本阶段产出在项目内的相对路径）、reason（证据和简短原因）。
完成一次请求或一个子任务是 checkpoint。有可执行工单就用 checkpoint 并给出具体工单。仅全目标达到才用 completed。blocked 要列出全部剩余路径的实测阻塞，且 ready_work 为空。停前等子代理结束并结算请求。
"@
            Write-Host "[pass $pass/$MaxPasses] Session $session"
            $passPrompt | & $claude @arguments @sessionArguments 2>> $errorPath | ForEach-Object {
            $writer.WriteLine($_)
            try { $event = ConvertFrom-Json -InputObject $_ -ErrorAction Stop } catch { return }
            if ($event.type -eq 'system') {
                Write-Host "[$($event.subtype)] $($event.model) $($event.description)"
            } elseif ($event.type -eq 'assistant') {
                $actor = if ($event.parent_tool_use_id) { 'worker' } else { 'main' }
                foreach ($block in $event.message.content) {
                    if ($block.type -eq 'tool_use') { Write-Host "[$actor] $($block.name) $($block.input.description)" }
                    if ($block.type -eq 'text' -and $block.text) { Write-Host "[$actor] $($block.text)" }
                }
            } elseif ($event.type -eq 'result') {
                Write-Host "[$($event.subtype)] $($event.result)"
            }
            }
            $exitCode = $LASTEXITCODE
            if ($exitCode -ne 0) {
                $workState = 'claude_runtime_error'
                break
            }
            $checkpointPath = Join-Path $outputDir $checkpointName
            $checkpoint = $null
            if (Test-Path -LiteralPath $checkpointPath -PathType Leaf) {
                try { $checkpoint = Get-Content -LiteralPath $checkpointPath -Raw | ConvertFrom-Json } catch {}
            }
            if ($checkpoint.run_id -ne $RunId -or $checkpoint.pass -ne $pass) {
                if ($missingCheckpointRetryUsed) {
                    $workState = 'checkpoint_missing_after_retry'
                    break
                }
                $missingCheckpointRetryUsed = $true
                $prompt = "用户已授权继续 $RunId。上一阶段未写可核对检查点。读取 $relativeOutput 的产物和最新账本，继续一项尚可执行的工作，再按本阶段格式写检查点。"
            } else {
                $ready = @($checkpoint.ready_work | Where-Object { $_ })
                if ($checkpoint.state -in @('completed', 'blocked') -and $ready.Count -eq 0) {
                    $workState = $checkpoint.state
                    break
                }
                $artifact = Join-Path $project ([string]$checkpoint.progress_artifact)
                if ($checkpoint.state -ne 'checkpoint' -or $ready.Count -eq 0 -or
                    -not (Test-Path -LiteralPath $artifact -PathType Leaf)) {
                    $workState = 'checkpoint_needs_review'
                    break
                }
                $signature = (Get-FileHash -LiteralPath $artifact).Hash
                if ($signature -eq $previousSignature) {
                    $workState = 'no_new_artifact'
                    break
                }
                $previousSignature = $signature
                $prompt = "继续用户已授权的 $RunId。读取 $relativeOutput/$checkpointName，完成其中 ready_work 的下一项，保留本轮来源暂停和证据要求。汇报一个子任务后仍有可做工作时继续。"
            }
            $sessionArguments = @('--resume', $session)
        }
    } finally {
        $writer.Dispose()
    }

    @{exit_code = $exitCode; work_state = $workState; finished_at = [DateTimeOffset]::UtcNow.ToString('o')} |
        ConvertTo-Json | Set-Content -LiteralPath (Join-Path $outputDir 'terminal_exit.json') -Encoding utf8
    Write-Host "Claude exited with code $exitCode. Session: $session"
    Write-Host "Work status: $workState. Start a new output run with -ResumeFrom $RunId to continue."
} catch {
    if (Test-Path -LiteralPath $outputDir -PathType Container) {
        $_ | Out-String | Set-Content -LiteralPath (Join-Path $outputDir 'launcher_error.log') -Encoding utf8
    }
    throw
} finally {
    $terminalLock.Dispose()
}
