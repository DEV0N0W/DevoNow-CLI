param(
    [Parameter(Position=0)]
    [string]$Version = "latest"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

function Write-Step {
    param(
        [string]$Message
    )

    Write-Host "==> $Message"
}

function Normalize-Version {
    param(
        [string]$RawVersion
    )

    if ([string]::IsNullOrWhiteSpace($RawVersion) -or $RawVersion -eq "latest") {
        return "latest"
    }

    if ($RawVersion.StartsWith("rust-v")) {
        return $RawVersion.Substring(6)
    }

    if ($RawVersion.StartsWith("v")) {
        return $RawVersion.Substring(1)
    }

    return $RawVersion
}

function Get-ReleaseUrl {
    param(
        [string]$AssetName,
        [string]$ResolvedVersion
    )

    return "https://github.com/DEV0N0W/DevNow-CLI/releases/download/rust-v$ResolvedVersion/$AssetName"
}

function Path-Contains {
    param(
        [string]$PathValue,
        [string]$Entry
    )

    if ([string]::IsNullOrWhiteSpace($PathValue)) {
        return $false
    }

    $needle = $Entry.TrimEnd("\")
    foreach ($segment in $PathValue.Split(";", [System.StringSplitOptions]::RemoveEmptyEntries)) {
        if ($segment.TrimEnd("\") -ieq $needle) {
            return $true
        }
    }

    return $false
}

function Resolve-Version {
    $normalizedVersion = Normalize-Version -RawVersion $Version
    if ($normalizedVersion -ne "latest") {
        return $normalizedVersion
    }

    $release = Invoke-RestMethod -Uri "https://api.github.com/repos/DEV0N0W/DevNow-CLI/releases/latest"
    if (-not $release.tag_name) {
        Write-Error "Failed to resolve the latest DevoNow release version."
        exit 1
    }

    return (Normalize-Version -RawVersion $release.tag_name)
}

if ($env:OS -ne "Windows_NT") {
    Write-Error "install.ps1 supports Windows only. Use install.sh on macOS or Linux."
    exit 1
}

if (-not [Environment]::Is64BitOperatingSystem) {
    Write-Error "DevoNow requires a 64-bit version of Windows."
    exit 1
}

$architecture = [System.Runtime.InteropServices.RuntimeInformation]::OSArchitecture
$target = $null
$platformLabel = $null
$npmTag = $null
switch ($architecture) {
    "Arm64" {
        $target = "aarch64-pc-windows-msvc"
        $platformLabel = "Windows (ARM64)"
        $npmTag = "win32-arm64"
    }
    "X64" {
        $target = "x86_64-pc-windows-msvc"
        $platformLabel = "Windows (x64)"
        $npmTag = "win32-x64"
    }
    default {
        Write-Error "Unsupported architecture: $architecture"
        exit 1
    }
}

if (-not [string]::IsNullOrWhiteSpace($env:DEVNOW_INSTALL_DIR)) {
    $installDir = $env:DEVNOW_INSTALL_DIR
} elseif ([string]::IsNullOrWhiteSpace($env:CODEX_INSTALL_DIR)) {
    $installDir = Join-Path $env:LOCALAPPDATA "Programs\DevoNow\bin"
} else {
    $installDir = $env:CODEX_INSTALL_DIR
}

$codexPath = Join-Path $installDir "devnow.exe"
$installMode = if (Test-Path $codexPath) { "Updating" } else { "Installing" }

Write-Step "$installMode DevoNow CLI"
Write-Step "Detected platform: $platformLabel"

New-Item -ItemType Directory -Force -Path $installDir | Out-Null

$resolvedVersion = Resolve-Version
Write-Step "Resolved version: $resolvedVersion"
$packageAsset = "devnow-npm-$npmTag-$resolvedVersion.tgz"

$tempDir = Join-Path ([System.IO.Path]::GetTempPath()) ("codex-install-" + [System.Guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Force -Path $tempDir | Out-Null

try {
    $archivePath = Join-Path $tempDir $packageAsset
    $extractDir = Join-Path $tempDir "extract"
    $url = Get-ReleaseUrl -AssetName $packageAsset -ResolvedVersion $resolvedVersion

    Write-Step "Downloading DevoNow CLI"
    Invoke-WebRequest -Uri $url -OutFile $archivePath

    New-Item -ItemType Directory -Force -Path $extractDir | Out-Null
    tar -xzf $archivePath -C $extractDir

    $vendorRoot = Join-Path $extractDir "package/vendor/$target"
    Write-Step "Installing to $installDir"
    $copyMap = @{
        "codex/codex.exe" = "devnow.exe"
        "codex/codex-command-runner.exe" = "codex-command-runner.exe"
        "codex/codex-windows-sandbox-setup.exe" = "codex-windows-sandbox-setup.exe"
        "path/rg.exe" = "rg.exe"
    }

    foreach ($relativeSource in $copyMap.Keys) {
        $requiredPath = Join-Path $vendorRoot $relativeSource
        if (-not (Test-Path -PathType Leaf $requiredPath)) {
            throw "Release archive is missing required file: $relativeSource"
        }
    }
    foreach ($document in @("LICENSE", "NOTICE")) {
        if (-not (Test-Path -PathType Leaf (Join-Path $extractDir "package/$document"))) {
            throw "Release archive is missing required file: $document"
        }
    }
    foreach ($relativeSource in $copyMap.Keys) {
        $sourcePath = Join-Path $vendorRoot $relativeSource
        $destinationPath = Join-Path $installDir $copyMap[$relativeSource]
        Move-Item -Force $sourcePath $destinationPath
    }
    $licenseDir = Join-Path $installDir "devnow-licenses"
    New-Item -ItemType Directory -Force -Path $licenseDir | Out-Null
    foreach ($document in @("LICENSE", "NOTICE")) {
        Copy-Item (Join-Path $extractDir "package/$document") $licenseDir
    }
    foreach ($document in @("LICENSE-MIT", "COPYING", "UNLICENSE")) {
        $sourceDocument = Join-Path $vendorRoot "path/$document"
        if (Test-Path $sourceDocument) {
            Copy-Item $sourceDocument (Join-Path $licenseDir "ripgrep-$document")
        }
    }
} finally {
    Remove-Item -Recurse -Force $tempDir -ErrorAction SilentlyContinue
}

$userPath = [Environment]::GetEnvironmentVariable("Path", "User")
$pathNeedsNewShell = $false
if (-not (Path-Contains -PathValue $userPath -Entry $installDir)) {
    if ([string]::IsNullOrWhiteSpace($userPath)) {
        $newUserPath = $installDir
    } else {
        $newUserPath = "$installDir;$userPath"
    }

    [Environment]::SetEnvironmentVariable("Path", $newUserPath, "User")
    if (-not (Path-Contains -PathValue $env:Path -Entry $installDir)) {
        if ([string]::IsNullOrWhiteSpace($env:Path)) {
            $env:Path = $installDir
        } else {
            $env:Path = "$installDir;$env:Path"
        }
    }
    Write-Step "PATH updated for future PowerShell sessions."
    $pathNeedsNewShell = $true
} elseif (Path-Contains -PathValue $env:Path -Entry $installDir) {
    Write-Step "$installDir is already on PATH."
} else {
    Write-Step "PATH is already configured for future PowerShell sessions."
    $pathNeedsNewShell = $true
}

if ($pathNeedsNewShell) {
    Write-Step ('Run now: $env:Path = "{0};$env:Path"; devnow' -f $installDir)
    Write-Step "Or open a new PowerShell window and run: devnow"
} else {
    Write-Step "Run: devnow"
}

Write-Host "DevoNow CLI $resolvedVersion installed successfully."
