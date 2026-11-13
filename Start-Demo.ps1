param(
    [switch]$Live,
    [ValidateRange(1, 65535)]
    [int]$Port = 8501
)

$ErrorActionPreference = 'Stop'
$demoPython = Join-Path $PSScriptRoot '.venv/Scripts/python.exe'
if (-not (Test-Path -LiteralPath $demoPython)) {
    throw 'Set up the project virtual environment first. See README.md.'
}

Push-Location -LiteralPath $PSScriptRoot
try {
    $env:PYTHONPATH = Join-Path $PSScriptRoot 'recognition/src'
    $env:RECYCLE_D_LOG_JSONL = Join-Path $PSScriptRoot 'runs/ui.jsonl'
    if ($Live) {
        $env:RECYCLE_D_BACKEND = 'integration:create_live_backend'
        $env:RECO_ENV_FILE = Join-Path $PSScriptRoot '.env'
        $env:RECO_LOG = Join-Path $PSScriptRoot 'runs/live_recognition.jsonl'
        & $demoPython -c 'from integration import live_recognizer; live_recognizer()'
        if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    } else {
        Remove-Item Env:RECYCLE_D_BACKEND -ErrorAction SilentlyContinue
    }
    & $demoPython -m streamlit run app.py --server.port $Port --server.headless true
    exit $LASTEXITCODE
} finally {
    Pop-Location
}
