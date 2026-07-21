# AI Gator - Run OpenCode with any model from Gator's gateway config
#
# Reads ~/.gator/config.json (the same config Gator's chat/coding-agent use)
# and launches OpenCode pointed at the correct AMD gateway endpoint with the
# right auth headers for the model you pick.
#
# OpenCode is an open-source, provider-agnostic coding agent (MIT licensed,
# github.com/anomalyco/opencode) - similar goal to aider but with native
# custom-gateway/header config and LSP-aware code intelligence.
#
# Usage:
#   .\run-opencode.ps1                    - launch interactive TUI, pick model there
#   .\run-opencode.ps1 -Model gpt-4.1     - launch TUI pre-set to a specific model
#   .\run-opencode.ps1 -Run "fix the bug" - one-shot non-interactive prompt
#   .\run-opencode.ps1 -List              - list all available models and exit
#
# Notes:
#   - Requires: npm install -g opencode-ai  (Node-based, avoids the Bun runtime
#     crash we hit with other tools on this Windows version)
#   - Config is written to a project-local opencode.json (gitignored) so the
#     gateway/model choice doesn't leak into the repo

param(
    [string]$Model = "",
    [string]$Run = "",
    [switch]$List
)

$ConfigPath = Join-Path $env:USERPROFILE ".gator\config.json"
$ProjectDir = $PSScriptRoot

if (-not (Test-Path $ConfigPath)) {
    Write-Host "Gator config not found at $ConfigPath" -ForegroundColor Red
    Write-Host "Run Gator at least once to generate it, or set up a profile in Settings." -ForegroundColor Yellow
    exit 1
}

# == Load config =============================================================
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

# == Prefer the LIVE model list from a running Gator server ===================
# ~/.gator/config.json's "models" field is a static snapshot written whenever
# the profile was last saved. Gator's own server refreshes its model list
# from the gateway every 24h, but ONLY in memory (llm/registry.py's
# load_profile() never writes back to disk) - so the file can silently drift
# behind what Gator's own chat UI is actually showing. Querying the live
# server's /api/config/model/status is the same call Gator's chat UI makes,
# so this guarantees the two always show identical model lists.
# Falls back to the static file (with a warning) if no server is reachable -
# e.g. running this script without Gator open at all.
$liveModels = $null
foreach ($p in 8000..8010) {
    try {
        $ping = Invoke-RestMethod -Uri "http://127.0.0.1:$p/status" -TimeoutSec 1 -ErrorAction Stop
        if ($ping.running) {
            $status = Invoke-RestMethod -Uri "http://127.0.0.1:$p/api/config/model/status" -TimeoutSec 3 -ErrorAction Stop
            if ($status.available -and $status.available.Count -gt 0) {
                $liveModels = $status.available
                Write-Host "Using live model list from running Gator server (port $p, $($liveModels.Count) models)" -ForegroundColor DarkGray
            }
            break
        }
    } catch { continue }
}
if ($liveModels) {
    $models = $liveModels
} else {
    Write-Host "No running Gator server found - using cached list from config.json ($($models.Count) models, may be stale)" -ForegroundColor Yellow
}

# == Check opencode is installed =============================================
$opencodeCmd = Get-Command opencode -ErrorAction SilentlyContinue
if (-not $opencodeCmd) {
    Write-Host "opencode not found on PATH." -ForegroundColor Red
    Write-Host "Install with: npm install -g opencode-ai" -ForegroundColor Yellow
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

# == Pick a model =============================================================
if (-not $Model) {
    Write-Host ""
    Write-Host "=== Available models ===" -ForegroundColor Cyan
    for ($i = 0; $i -lt $models.Count; $i++) {
        Write-Host ("  [{0}] {1}" -f $i, $models[$i])
    }
    Write-Host ""
    $selection = Read-Host "Pick a model number (or type a model name, or Enter to let OpenCode choose)"
    if ($selection -match '^\d+$' -and [int]$selection -lt $models.Count) {
        $Model = $models[[int]$selection]
    } elseif ($selection) {
        $Model = $selection
    }
}

# == Build ONE complete config declaring every model from Gator's profile ====
# Every model from Gator's config is bucketed into whichever provider it
# needs (Anthropic-shaped vs OpenAI-compatible) up front, so the generated
# config is always the SAME complete shape regardless of which -Model you
# pass - there's exactly one config file, one schema, always fully declared.
# This matters beyond convenience: a persistent process (opencode serve)
# needs a static config it can hold open across many requests/models, not
# one that gets reshaped depending on the last model that was launched.
#
# Claude models use the Anthropic-shaped endpoint; everything else uses the
# OpenAI-compatible Unified endpoint. Same split as llm/anthropic_provider.py
# and llm/openai_provider.py in Gator's own code.

# The Anthropic SDK expects the base to end at the version segment (verified
# directly: POST .../Anthropic/v1/messages succeeds, .../Anthropic alone
# returns "Resource Not Found").
$trimmedAnthropic = $anthropicUrl.TrimEnd('/')
if ($trimmedAnthropic -notmatch '/v1$') { $trimmedAnthropic = "$trimmedAnthropic/v1" }

# The OpenAI-compatible SDK appends /chat/completions itself, so the base
# must end at the version segment - matches normalize_openai_base_url() in
# web/llm/gateway.py (Gator's own code hits the same requirement).
$trimmedUnified = $unifiedUrl.TrimEnd('/')
if ($trimmedUnified -notmatch '/v1$') { $trimmedUnified = "$trimmedUnified/v1" }

# Bucket every known model (plus whatever -Model the user typed, in case it's
# not in the list) so both provider blocks are always fully populated.
$allModelNames = @($models) + @($Model) | Select-Object -Unique | Where-Object { $_ }
$claudeModels = @($allModelNames | Where-Object { $_ -match "claude" })
$otherModels  = @($allModelNames | Where-Object { $_ -notmatch "claude" })

$anthropicModelsBlock = @{}
foreach ($m in $claudeModels) { $anthropicModelsBlock[$m] = @{ name = $m } }
$gatewayModelsBlock = @{}
foreach ($m in $otherModels) { $gatewayModelsBlock[$m] = @{ name = $m } }

# OpenCode validates model names against its own built-in catalog (models.dev)
# before sending the request, and rejects anything it doesn't recognize - even
# though the actual gateway would accept it fine. Gator/AMD's model names
# (e.g. "Claude-Sonnet-4.6", mixed case with dots) don't match OpenCode's own
# naming ("claude-sonnet-4-6"). Explicitly declaring every model under the
# provider's "models" block bypasses that catalog check entirely - unlike
# aider, which never validates and just passes the string straight through.
#
# Both provider entries use CUSTOM ids (not the built-in "anthropic"/"openai"
# ones). Reusing a built-in id merges OpenCode's own known-model catalog
# into the /model picker alongside ours - confirmed via GET /config/providers:
# the built-in "anthropic" id showed 25 models (our 10 + 15 of OpenCode's own
# catalog entries like "claude-opus-4-5"), while a custom id showed only the
# models we declared, no bleed-through. A custom id + explicit npm adapter
# (@ai-sdk/anthropic / @ai-sdk/openai-compatible - both officially documented
# per opencode.ai/docs/providers/) bypasses the catalog merge entirely.
$providerConfig = @{
    "gator-anthropic" = @{
        npm     = "@ai-sdk/anthropic"
        name    = "Gator AMD Anthropic Gateway"
        options = @{
            baseURL = $trimmedAnthropic
            apiKey  = '{env:GATOR_OPENCODE_KEY}'
            headers = @{ $apiKeyHeader = '{env:GATOR_OPENCODE_KEY}' }
        }
        models = $anthropicModelsBlock
    }
    "gator-gateway" = @{
        npm     = "@ai-sdk/openai-compatible"
        name    = "Gator AMD Gateway"
        options = @{
            baseURL = $trimmedUnified
            apiKey  = '{env:GATOR_OPENCODE_KEY}'
            headers = @{ $apiKeyHeader = '{env:GATOR_OPENCODE_KEY}' }
        }
        models = $gatewayModelsBlock
    }
}

# Resolve which provider the requested -Model actually lives under.
$isClaude = $Model -match "claude"
$providerId = if ($isClaude) { "gator-anthropic" } else { "gator-gateway" }
$baseUrl = if ($isClaude) { $trimmedAnthropic } else { $trimmedUnified }

# == Write the single, complete opencode.json =================================
# OpenCode supports {env:VAR} substitution in config, so the real key never
# needs to be written to disk in plaintext - only an env var reference.
$env:GATOR_OPENCODE_KEY = $apiKey

# Allowlist, not a denylist. OpenCode's models.dev catalog has 166+ known
# provider ids (github-copilot, google, bedrock, mistral, groq, ...), and
# ANY of them can silently auto-activate if you happen to have ambient
# credentials lying around for that service (an API key env var, a `gh auth
# login` session, a cloud CLI profile, etc.) - confirmed this happening with
# "anthropic" (from Claude Code CLI's own env vars) and OpenCode's own
# "opencode" free-tier provider (enabled by default, no credentials needed).
# Denylisting each one as it's discovered is unbounded and reactive.
# enabled_providers flips this around: ONLY these two ids are ever active,
# full stop, regardless of what credentials exist on the machine now or
# what new provider ids get added to the catalog later.
$configJson = @{
    '$schema' = "https://opencode.ai/config.json"
    enabled_providers = @("gator-anthropic", "gator-gateway")
    model     = "$providerId/$Model"
    provider  = $providerConfig
} | ConvertTo-Json -Depth 10

$opencodeConfigPath = Join-Path $ProjectDir "opencode.json"
[System.IO.File]::WriteAllText($opencodeConfigPath, $configJson, [System.Text.UTF8Encoding]::new($false))

Write-Host ""
Write-Host "=== Launching OpenCode ===" -ForegroundColor Cyan
Write-Host "  Model    : $providerId/$Model" -ForegroundColor Green
Write-Host "  Endpoint : $baseUrl" -ForegroundColor DarkGray
Write-Host "  Auth     : $apiKeyHeader header (from Gator config)" -ForegroundColor DarkGray
Write-Host "  Repo     : $ProjectDir" -ForegroundColor DarkGray
Write-Host "  Config   : $opencodeConfigPath (gitignored, regenerated each run)" -ForegroundColor DarkGray
Write-Host ""

Set-Location $ProjectDir

if ($Run) {
    & opencode run $Run --model "$providerId/$Model"
} else {
    & opencode --model "$providerId/$Model"
}
