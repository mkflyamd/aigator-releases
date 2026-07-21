# AI Gator - Run aider with any model from Gator's gateway config
#
# Reads ~/.gator/config.json (the same config Gator's chat/coding-agent use)
# and launches aider pointed at the correct AMD gateway endpoint with the
# right auth headers for the model you pick.
#
# Usage:
#   .\run-aider.ps1                    - pick a model interactively
#   .\run-aider.ps1 -Model gpt-4.1     - use a specific model directly
#   .\run-aider.ps1 -List              - list all available models and exit
#
# Notes:
#   - Claude-* models route through the Anthropic-format endpoint
#   - All other models (gpt-*, gemini-*, Kimi-*, DeepSeek-*, etc.) route
#     through the OpenAI-compatible Unified endpoint
#   - The subscription key is injected as a custom header via aider's
#     --extra-params, matching what Gator's own LLM calls use

param(
    [string]$Model = "",
    [switch]$List
)

$ConfigPath = Join-Path $env:USERPROFILE ".gator\config.json"
$ProjectDir = $PSScriptRoot

if (-not (Test-Path $ConfigPath)) {
    Write-Host "Gator config not found at $ConfigPath" -ForegroundColor Red
    Write-Host "Run Gator at least once to generate it, or set up a profile in Settings." -ForegroundColor Yellow
    exit 1
}

# == Load config ============================================================
$config = Get-Content $ConfigPath -Raw | ConvertFrom-Json
$profile = $config.llm_profiles[0]

if (-not $profile) {
    Write-Host "No LLM profile found in Gator config." -ForegroundColor Red
    exit 1
}

$apiKey        = $profile.api_key
$apiKeyHeader  = $profile.api_key_header
$anthropicUrl  = $profile.anthropic_url
$unifiedUrl    = $profile.base_url
$models        = $profile.models

if (-not $apiKey) {
    Write-Host "No API key found in Gator profile. Configure one in Gator's Settings first." -ForegroundColor Red
    exit 1
}

# == -List: show models and exit ==============================================
if ($List) {
    Write-Host ""
    Write-Host "Available models (from Gator config):" -ForegroundColor Cyan
    $models | ForEach-Object { Write-Host "  $_" }
    Write-Host ""
    exit 0
}

# == Pick a model ==============================================================
if (-not $Model) {
    Write-Host ""
    Write-Host "=== Available models ===" -ForegroundColor Cyan
    for ($i = 0; $i -lt $models.Count; $i++) {
        Write-Host ("  [{0}] {1}" -f $i, $models[$i])
    }
    Write-Host ""
    $selection = Read-Host "Pick a model number (or type a model name)"
    if ($selection -match '^\d+$' -and [int]$selection -lt $models.Count) {
        $Model = $models[[int]$selection]
    } else {
        $Model = $selection
    }
}

if ($models -notcontains $Model) {
    Write-Host "Warning: '$Model' is not in Gator's configured model list - trying anyway." -ForegroundColor Yellow
}

# Both litellm AND aider separately try to download a pricing/context-window
# reference file from GitHub on startup. On networks with SSL inspection
# (corporate proxies) this fails with a cryptic SSLCertVerificationError that
# is harmless (both fall back to built-in defaults) but alarming to see.
#
# Fix litellm's fetch: use its own bundled local copy, no network call.
$env:LITELLM_LOCAL_MODEL_COST_MAP = "True"
#
# Fix aider's separate fetch: aider caches this file at
# ~/.aider/caches/model_prices_and_context_window.json and only re-fetches
# if the cache is missing or older than 24h. Pre-seed it from litellm's
# bundled copy (same file, same content) so aider's cache is always fresh
# and it never attempts the network call. This does NOT touch SSL
# verification for real API calls - only skips this optional metadata fetch.
$aiderCacheDir = Join-Path $env:USERPROFILE ".aider\caches"
$aiderCacheFile = Join-Path $aiderCacheDir "model_prices_and_context_window.json"
$litellmBackup = Join-Path $ProjectDir ".venv\Lib\site-packages\litellm\model_prices_and_context_window_backup.json"
if ((Test-Path $litellmBackup) -and (-not (Test-Path $aiderCacheDir))) {
    New-Item -ItemType Directory -Path $aiderCacheDir -Force | Out-Null
}
# aider treats a cache file smaller than ~1KB as empty ("{}" from a prior
# failed fetch) and re-fetches anyway even if it's "fresh" by age. Overwrite
# whenever missing, stale, OR too small to be real pricing data.
$needsSeed = $true
if (Test-Path $aiderCacheFile) {
    $fi = Get-Item $aiderCacheFile
    $isFresh = $fi.LastWriteTime -ge (Get-Date).AddHours(-24)
    $isRealData = $fi.Length -gt 1024
    $needsSeed = -not ($isFresh -and $isRealData)
}
if ((Test-Path $litellmBackup) -and $needsSeed) {
    Copy-Item $litellmBackup $aiderCacheFile -Force
}

# == Route to the correct endpoint + wire format ==============================
# Claude models use the Anthropic-shaped endpoint; everything else uses the
# OpenAI-compatible Unified endpoint. Same routing logic as llm/anthropic_provider.py
# and llm/openai_provider.py in Gator's own code.
$isClaude = $Model -match "claude"

if ($isClaude) {
    $litellmModel = "anthropic/$Model"
    $baseUrl = $anthropicUrl
    $env:ANTHROPIC_API_KEY = $apiKey
    $env:ANTHROPIC_API_BASE = $baseUrl
    Remove-Item Env:\OPENAI_API_KEY -ErrorAction SilentlyContinue
    Remove-Item Env:\OPENAI_API_BASE -ErrorAction SilentlyContinue
} else {
    $litellmModel = "openai/$Model"
    # The OpenAI SDK appends /chat/completions itself, so the base must end
    # at the version segment - matches normalize_openai_base_url() in
    # web/llm/gateway.py (Gator's own code hits the same requirement).
    $trimmedUnified = $unifiedUrl.TrimEnd('/')
    if ($trimmedUnified -notmatch '/v1$') {
        $trimmedUnified = "$trimmedUnified/v1"
    }
    $baseUrl = $trimmedUnified
    $env:OPENAI_API_KEY = $apiKey
    $env:OPENAI_API_BASE = $baseUrl
    Remove-Item Env:\ANTHROPIC_API_KEY -ErrorAction SilentlyContinue
    Remove-Item Env:\ANTHROPIC_API_BASE -ErrorAction SilentlyContinue
}

# == Write a model-settings file for the custom subscription-key header =====
# aider has no CLI flag for extra_headers directly - the documented mechanism
# is a --model-settings-file (YAML) with extra_params.extra_headers, which is
# the CLI-accessible equivalent of the Model.extra_params Gator's own code
# uses internally. Written to a temp file per run.
$settingsPath = Join-Path $env:TEMP "gator-aider-model-settings.yml"
$settingsYaml = @"
- name: $litellmModel
  extra_params:
    extra_headers:
      ${apiKeyHeader}: $apiKey
"@
# -Encoding UTF8 adds a BOM which breaks the YAML parser ("mapping values are
# not allowed here") - write with .NET's UTF8Encoding(false) instead (no BOM)
[System.IO.File]::WriteAllText($settingsPath, $settingsYaml, [System.Text.UTF8Encoding]::new($false))

Write-Host ""
Write-Host "=== Launching aider ===" -ForegroundColor Cyan
Write-Host "  Model    : $litellmModel" -ForegroundColor Green
Write-Host "  Endpoint : $baseUrl" -ForegroundColor DarkGray
Write-Host "  Auth     : $apiKeyHeader header (from Gator config)" -ForegroundColor DarkGray
Write-Host "  Repo     : $ProjectDir" -ForegroundColor DarkGray
Write-Host "  Tokens   : aider prints 'Tokens: N sent, N received' + cost after every message" -ForegroundColor DarkGray
Write-Host ""

$venvPython = Join-Path $ProjectDir ".venv\Scripts\python.exe"
if (-not (Test-Path $venvPython)) {
    Write-Host "No .venv found - run WakeGator.ps1 first." -ForegroundColor Red
    exit 1
}

Set-Location $ProjectDir
# --no-show-model-warnings: suppresses the "unknown context window" prompt for
#   models not in aider's built-in metadata (e.g. Kimi, DeepSeek, Gemini) - it
#   only affects aider's own cost/context-limit estimates, not functionality.
# --no-check-update: skips the PyPI version check that fails on this network
#   (corporate proxy / cert issue, unrelated to the AMD gateway).
& $venvPython -m aider --model $litellmModel --model-settings-file $settingsPath `
    --no-show-model-warnings --no-check-update
