param(
    [switch]$KeepDownload
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

$Repo = "mkflyamd/aigator-releases"
$ApiUrl = "https://api.github.com/repos/$Repo/releases?per_page=20"
$Headers = @{
    Accept = "application/vnd.github+json"
    "X-GitHub-Api-Version" = "2022-11-28"
    "User-Agent" = "AI-Gator-Installer"
}

function Log {
    param([string]$Level, [string]$Message)
    Write-Host ("[{0}] {1,-5} {2}" -f (Get-Date -Format "HH:mm:ss"), $Level, $Message)
}

function Fail {
    param([string]$Message)
    Log "ERROR" $Message
    exit 1
}

$architecture = if ($env:PROCESSOR_ARCHITEW6432) { $env:PROCESSOR_ARCHITEW6432 } else { $env:PROCESSOR_ARCHITECTURE }
if ($architecture -notin @("AMD64", "x86_64")) {
    Fail "This installer supports Windows x64 only. Detected architecture: $architecture"
}

$tempDirectory = Join-Path $env:TEMP ("ai-gator-install-" + [Guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Path $tempDirectory | Out-Null

try {
    Log "INFO" "Requesting recent published releases from $ApiUrl"
    $releases = @(Invoke-RestMethod -Uri $ApiUrl -Headers $Headers)
    $release = $releases | Where-Object { -not $_.draft } | Select-Object -First 1
    if (-not $release) {
        throw "GitHub did not return a published release."
    }
    $channel = if ($release.prerelease) { "prerelease" } else { "stable" }
    Log "INFO" "Selected latest published release $($release.tag_name) ($channel)"

    $installers = @($release.assets | Where-Object { $_.name -match '^AI-Gator-.+-Windows-x64\.exe$' })
    if ($installers.Count -ne 1) {
        throw "Expected exactly one Windows x64 installer, found $($installers.Count)."
    }
    $checksums = @($release.assets | Where-Object { $_.name -eq "SHA256SUMS.txt" })
    if ($checksums.Count -ne 1) {
        throw "Expected SHA256SUMS.txt in the release, found $($checksums.Count)."
    }

    $installer = $installers[0]
    $installerPath = Join-Path $tempDirectory $installer.name
    $checksumPath = Join-Path $tempDirectory "SHA256SUMS.txt"

    Log "INFO" "Downloading $($installer.name) ($($installer.size) bytes)"
    Invoke-WebRequest -Uri $installer.browser_download_url -Headers $Headers -OutFile $installerPath -UseBasicParsing
    Log "INFO" "Downloading SHA256SUMS.txt"
    Invoke-WebRequest -Uri $checksums[0].browser_download_url -Headers $Headers -OutFile $checksumPath -UseBasicParsing

    $checksumLine = Get-Content $checksumPath | Where-Object { $_ -match ("^[A-Fa-f0-9]{64}\s+\*?" + [Regex]::Escape($installer.name) + "$") }
    if (@($checksumLine).Count -ne 1) {
        throw "SHA256SUMS.txt does not contain exactly one checksum for $($installer.name)."
    }
    $expectedHash = ($checksumLine -split '\s+')[0].ToUpperInvariant()
    $actualHash = (Get-FileHash -Path $installerPath -Algorithm SHA256).Hash.ToUpperInvariant()
    Log "INFO" "Expected SHA-256: $expectedHash"
    Log "INFO" "Actual SHA-256:   $actualHash"
    if ($actualHash -ne $expectedHash) {
        throw "Checksum verification failed. The installer will not run."
    }
    Log "OK" "Checksum verified"

    Log "INFO" "Starting the interactive Windows installer"
    Log "INFO" "Windows may display a SmartScreen warning while releases are unsigned"
    $process = Start-Process -FilePath $installerPath -Wait -PassThru
    if ($process.ExitCode -ne 0) {
        throw "The Windows installer exited with code $($process.ExitCode)."
    }
    Log "OK" "AI Gator installation completed"

    Log "INFO" "The installer's finish screen controls whether AI Gator launches"
}
catch {
    Log "ERROR" $_.Exception.Message
    Log "ERROR" "No unverified installer was executed"
    exit 1
}
finally {
    if ($KeepDownload) {
        Log "INFO" "Keeping downloaded files in $tempDirectory"
    }
    else {
        Remove-Item $tempDirectory -Recurse -Force -ErrorAction SilentlyContinue
        if (Test-Path $tempDirectory) {
            Log "WARN" "Could not remove all temporary files from $tempDirectory"
        }
        else {
            Log "INFO" "Removed temporary download files"
        }
    }
}
