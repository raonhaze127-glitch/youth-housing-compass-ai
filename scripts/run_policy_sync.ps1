$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
$python = "C:\Python314\python.exe"
$logDir = Join-Path $projectRoot "logs"
$logFile = Join-Path $logDir ("policy-sync-" + (Get-Date -Format "yyyyMMdd") + ".log")

New-Item -ItemType Directory -Force -Path $logDir | Out-Null
Set-Location $projectRoot

$envFile = Join-Path $projectRoot ".env.local"
if (Test-Path $envFile) {
    Get-Content $envFile | ForEach-Object {
        if ($_ -match '^\s*([^#][^=]+)=(.*)$') {
            $name = $matches[1].Trim()
            $value = $matches[2].Trim().Trim('"').Trim("'")
            if ($name -and -not [Environment]::GetEnvironmentVariable($name, "Process")) {
                [Environment]::SetEnvironmentVariable($name, $value, "Process")
            }
        }
    }
}

if (-not $env:NOTION_POLICY_DATABASE_ID) {
    $env:NOTION_POLICY_DATABASE_ID = "398ed42e-2d62-4bfc-ad65-b4a64d082a32"
}

"[$(Get-Date -Format o)] policy sync started" | Tee-Object -FilePath $logFile -Append

if (-not $env:NOTION_TOKEN) {
    "[$(Get-Date -Format o)] NOTION_TOKEN is missing. Set a user environment variable before syncing to Notion." |
        Tee-Object -FilePath $logFile -Append
    exit 2
}

& $python services/announcement-api/scripts/sync_policy_rss.py --days-back 2 --timeout 20 --retries 1 2>&1 |
    Tee-Object -FilePath $logFile -Append

$exitCode = $LASTEXITCODE
"[$(Get-Date -Format o)] policy sync finished with exit code $exitCode" | Tee-Object -FilePath $logFile -Append
exit $exitCode
