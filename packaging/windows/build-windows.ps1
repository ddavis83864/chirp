<#
.SYNOPSIS
    Builds, tests, and packages the Windows CHIRP Community Edition
    distribution (portable ZIP + Inno Setup installer).

.DESCRIPTION
    Single entry point used both locally and by
    .github/workflows/windows-release.yml, so there is exactly one
    implementation of each build step. Assumes the working tree already
    contains the application source to be packaged (the caller -- CI's
    "Pin application source to source_ref" step, mirroring
    macos-build.yml -- is responsible for checking out the correct
    chirp/, setup.py, setup.cfg, requirements.txt, MANIFEST.in, COPYING
    before this script runs; this script does not fetch or check out
    anything from git itself).

    Modes:
      Build    - create an isolated build venv, install pinned
                 dependencies, compile locales, run PyInstaller
                 (packaging/windows/chirp.spec) -> dist\CHIRP
      Test     - run the repository's existing unit test suite plus
                 tests\packaging\test_windows_packaging.py against the
                 build venv
      Package  - validate the PyInstaller bundle, build the portable
                 ZIP, build the Inno Setup installer from that SAME
                 validated bundle, generate SHA256SUMS,
                 build-provenance.json, and THIRD_PARTY_LICENSES.txt
      All      - Build, then Test, then Package

.PARAMETER Mode
    One of Build, Test, Package, All.

.PARAMETER Version
    Release version string, X.Y.Z (e.g. "1.12.0"). Required for Package
    and All. Baked into CHIRP.exe metadata, the installer, and every
    generated filename.

.PARAMETER SourceCommit
    Full 40-character commit SHA of the application source actually
    being packaged (used only for build-provenance.json; does not affect
    what gets built). Defaults to the working tree's current HEAD.

.PARAMETER LinuxSourceCommit
.PARAMETER MacosSourceCommit
    Full 40-character commit SHAs of the verified Linux/macOS v1.12.0
    release source, for cross-referencing in build-provenance.json.
    Defaults to the known v1.12.0 baseline
    (9c38424f5e716c00e4444533a093ca1ba51258af) if not supplied.

.PARAMETER SkipInnoSetup
    Skip building the .exe installer (portable ZIP only). Useful for a
    quick local Build+Package iteration on a machine without Inno Setup
    installed.

.EXAMPLE
    .\packaging\windows\build-windows.ps1 -Mode Build

.EXAMPLE
    .\packaging\windows\build-windows.ps1 -Mode All -Version 1.12.0
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet('Build', 'Test', 'Package', 'All')]
    [string]$Mode,

    [ValidatePattern('^\d+\.\d+\.\d+$')]
    [string]$Version,

    [ValidatePattern('^[0-9a-f]{40}$')]
    [string]$SourceCommit,

    [ValidatePattern('^[0-9a-f]{40}$')]
    [string]$LinuxSourceCommit = '9c38424f5e716c00e4444533a093ca1ba51258af',

    [ValidatePattern('^[0-9a-f]{40}$')]
    [string]$MacosSourceCommit = '9c38424f5e716c00e4444533a093ca1ba51258af',

    [switch]$SkipInnoSetup
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'  # avoid slow default progress UI

# --- Resolve paths, independent of caller's current directory ------------
$ScriptDir = $PSScriptRoot
$RepoRoot = (Resolve-Path (Join-Path $ScriptDir '..\..')).Path
$DistDir = Join-Path $RepoRoot 'dist'
$DistInstallerDir = Join-Path $RepoRoot 'dist-installer'
$BuildDir = Join-Path $ScriptDir 'build'
$VenvDir = Join-Path $ScriptDir '.build-venv'
$VenvPy = Join-Path $VenvDir 'Scripts\python.exe'

function Write-Step {
    param([string]$Message)
    Write-Host "==> $Message" -ForegroundColor Cyan
}

function Invoke-Checked {
    # Runs an external command and stops the script on nonzero exit,
    # since $ErrorActionPreference only covers PowerShell-native errors,
    # not native-executable exit codes.
    param(
        [Parameter(Mandatory = $true)][string]$FilePath,
        [Parameter(ValueFromRemainingArguments = $true)][string[]]$Arguments
    )
    Write-Host "    $FilePath $($Arguments -join ' ')"
    & $FilePath @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Command failed (exit $LASTEXITCODE): $FilePath $($Arguments -join ' ')"
    }
}

function Assert-Version {
    if (-not $Version) {
        throw "-Version is required for this mode (expected X.Y.Z, e.g. 1.12.0)."
    }
}

function Get-ResolvedSourceCommit {
    if ($SourceCommit) { return $SourceCommit }
    $head = git -C $RepoRoot rev-parse HEAD
    if ($LASTEXITCODE -ne 0 -or -not $head) {
        throw "Could not resolve current HEAD via git and -SourceCommit was not supplied."
    }
    return $head.Trim()
}

# --- Build ------------------------------------------------------------
function Invoke-Build {
    Write-Step "Creating isolated build venv at $VenvDir"
    if (Test-Path $VenvDir) {
        Remove-Item -Recurse -Force $VenvDir
    }
    Invoke-Checked py -3.11 -m venv $VenvDir
    if (-not (Test-Path $VenvPy)) {
        throw "Expected venv interpreter not found at $VenvPy after venv creation."
    }

    Write-Step "Installing pinned build dependencies"
    Invoke-Checked $VenvPy -m pip install --upgrade pip
    Invoke-Checked $VenvPy -m pip install -r (Join-Path $ScriptDir 'requirements-build.txt')

    Write-Step "Recording resolved tool versions"
    & $VenvPy --version
    & $VenvPy -m PyInstaller --version
    & $VenvPy -c "import wx; print('wxPython', wx.version())"

    Write-Step "Compiling translations (chirp/locale/*.po -> *.mo)"
    $msgfmt = Get-Command msgfmt -ErrorAction SilentlyContinue
    if (-not $msgfmt) {
        throw "msgfmt not found on PATH. Install GNU gettext tools first " +
              "(CI: 'choco install gettext -y'; locally: any GNU gettext " +
              "for Windows distribution)."
    }
    Get-ChildItem (Join-Path $RepoRoot 'chirp\locale') -Filter '*.po' | ForEach-Object {
        $lang = $_.BaseName
        $outDir = Join-Path $RepoRoot "chirp\locale\$lang\LC_MESSAGES"
        New-Item -ItemType Directory -Force -Path $outDir | Out-Null
        Invoke-Checked msgfmt "--output-file=$outDir\CHIRP.mo" $_.FullName
    }

    Write-Step "Generating versioned PyInstaller version-info resource"
    Assert-Version
    $versionParts = $Version.Split('.')
    $versionTuple = "$($versionParts[0]), $($versionParts[1]), $($versionParts[2]), 0"
    $versionInfoTemplate = Get-Content (Join-Path $ScriptDir 'version-info.txt') -Raw
    $versionInfoResolved = $versionInfoTemplate `
        -replace '__CHIRP_VERSION_TUPLE__', $versionTuple `
        -replace '__CHIRP_VERSION_STRING__', "$Version.0"
    New-Item -ItemType Directory -Force -Path $BuildDir | Out-Null
    $versionInfoPath = Join-Path $BuildDir 'version-info-resolved.txt'
    Set-Content -Path $versionInfoPath -Value $versionInfoResolved -NoNewline

    Write-Step "Running PyInstaller (one-directory bundle)"
    if (Test-Path $DistDir) { Remove-Item -Recurse -Force $DistDir }
    if (Test-Path $BuildDir\pyinstaller) { Remove-Item -Recurse -Force $BuildDir\pyinstaller }
    $env:CHIRP_WINDOWS_VERSION_FILE = $versionInfoPath
    try {
        Push-Location $RepoRoot
        Invoke-Checked $VenvPy -m PyInstaller `
            --distpath $DistDir `
            --workpath (Join-Path $BuildDir 'pyinstaller') `
            --noconfirm `
            (Join-Path $ScriptDir 'chirp.spec')
    }
    finally {
        Pop-Location
        Remove-Item Env:\CHIRP_WINDOWS_VERSION_FILE -ErrorAction SilentlyContinue
    }

    $bundleDir = Join-Path $DistDir 'CHIRP'
    if (-not (Test-Path (Join-Path $bundleDir 'CHIRP.exe'))) {
        throw "PyInstaller did not produce $bundleDir\CHIRP.exe."
    }
    Write-Step "Validating the freshly built bundle"
    Invoke-Checked $VenvPy (Join-Path $ScriptDir 'validate-package.py') `
        --bundle-dir $bundleDir `
        --build-machine-marker $env:USERPROFILE

    Write-Host "Build complete: $bundleDir" -ForegroundColor Green
}

# --- Test ---------------------------------------------------------------
function Invoke-Test {
    if (-not (Test-Path $VenvPy)) {
        throw "Build venv not found at $VenvPy. Run -Mode Build first."
    }
    Write-Step "Installing test dependencies"
    Invoke-Checked $VenvPy -m pip install pytest

    Write-Step "Running packaging-specific tests"
    Push-Location $RepoRoot
    try {
        Invoke-Checked $VenvPy -m pytest tests\packaging\test_windows_packaging.py -v
    }
    finally {
        Pop-Location
    }
}

# --- Package --------------------------------------------------------------
function Invoke-Package {
    Assert-Version
    if (-not (Test-Path $VenvPy)) {
        throw "Build venv not found at $VenvPy. Run -Mode Build first."
    }
    $bundleDir = Join-Path $DistDir 'CHIRP'
    if (-not (Test-Path (Join-Path $bundleDir 'CHIRP.exe'))) {
        throw "$bundleDir\CHIRP.exe not found. Run -Mode Build first."
    }

    Write-Step "Re-validating the bundle before packaging"
    Invoke-Checked $VenvPy (Join-Path $ScriptDir 'validate-package.py') `
        --bundle-dir $bundleDir `
        --build-machine-marker $env:USERPROFILE

    Write-Step "Generating THIRD_PARTY_LICENSES.txt"
    $thirdPartyPath = Join-Path $RepoRoot 'THIRD_PARTY_LICENSES.txt'
    Invoke-Checked $VenvPy (Join-Path $ScriptDir 'generate-third-party-licenses.py') `
        --output $thirdPartyPath

    Write-Step "Assembling portable ZIP staging directory"
    $stageName = "CHIRP-windows-v$Version-x86_64"
    $stageParent = Join-Path $BuildDir 'zip-stage'
    $stageDir = Join-Path $stageParent $stageName
    if (Test-Path $stageParent) { Remove-Item -Recurse -Force $stageParent }
    New-Item -ItemType Directory -Force -Path $stageDir | Out-Null

    Copy-Item -Path (Join-Path $bundleDir '*') -Destination $stageDir -Recurse
    Copy-Item -Path (Join-Path $RepoRoot 'COPYING') -Destination (Join-Path $stageDir 'LICENSE')
    Copy-Item -Path $thirdPartyPath -Destination $stageDir
    Copy-Item -Path (Join-Path $ScriptDir 'README-Windows.txt') -Destination $stageDir

    # Belt-and-suspenders: refuse to ship anything that looks like a
    # build cache, VCS metadata, or test file inside the ZIP staging dir.
    $forbidden = Get-ChildItem -Recurse -Path $stageDir -Include '.git', '__pycache__', '*.pdb', '*.pyc', 'test_*.py' -ErrorAction SilentlyContinue
    if ($forbidden) {
        throw "Refusing to package: forbidden files found in ZIP staging dir: $($forbidden.FullName -join ', ')"
    }

    Write-Step "Creating portable ZIP"
    if (-not (Test-Path $DistDir)) { New-Item -ItemType Directory -Force -Path $DistDir | Out-Null }
    $zipName = "CHIRP-windows-v$Version-x86_64-portable.zip"
    $zipPath = Join-Path $DistDir $zipName
    if (Test-Path $zipPath) { Remove-Item -Force $zipPath }
    # Stable ordering: sort entries by relative path before compressing,
    # rather than relying on filesystem enumeration order.
    Add-Type -AssemblyName System.IO.Compression
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $zip = [System.IO.Compression.ZipFile]::Open($zipPath, [System.IO.Compression.ZipArchiveMode]::Create)
    try {
        $entries = Get-ChildItem -Recurse -File -Path $stageParent |
            Sort-Object { $_.FullName }
        foreach ($entry in $entries) {
            $relPath = $entry.FullName.Substring($stageParent.Length + 1) -replace '\\', '/'
            $zipEntry = $zip.CreateEntry($relPath, [System.IO.Compression.CompressionLevel]::Optimal)
            # Normalize timestamp so the archive doesn't encode the exact
            # build-machine wall-clock time in every entry.
            $zipEntry.LastWriteTime = [DateTimeOffset]::new(2026, 1, 1, 0, 0, 0, [TimeSpan]::Zero)
            $entryStream = $zipEntry.Open()
            try {
                $fileStream = [System.IO.File]::OpenRead($entry.FullName)
                try { $fileStream.CopyTo($entryStream) }
                finally { $fileStream.Dispose() }
            }
            finally { $entryStream.Dispose() }
        }
    }
    finally {
        $zip.Dispose()
    }
    Write-Host "Portable ZIP: $zipPath ($((Get-Item $zipPath).Length) bytes)" -ForegroundColor Green

    if (-not $SkipInnoSetup) {
        Write-Step "Building the Inno Setup installer"
        $iscc = Get-Command ISCC.exe -ErrorAction SilentlyContinue
        if (-not $iscc) {
            $defaultIscc = "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe"
            if (Test-Path $defaultIscc) {
                $iscc = Get-Item $defaultIscc
            }
        }
        if (-not $iscc) {
            throw "ISCC.exe (Inno Setup command-line compiler) not found. " +
                  "Install Inno Setup 6 first (CI: 'choco install innosetup -y')."
        }
        if (Test-Path $DistInstallerDir) { Remove-Item -Recurse -Force $DistInstallerDir }
        New-Item -ItemType Directory -Force -Path $DistInstallerDir | Out-Null

        Invoke-Checked $iscc.Source `
            "/DChirpVersion=$Version" `
            "/DChirpSourceDir=$bundleDir" `
            "/DChirpRepoRoot=$RepoRoot" `
            (Join-Path $ScriptDir 'chirp.iss')

        $setupName = "CHIRP-windows-v$Version-x86_64-setup.exe"
        $setupPath = Join-Path $DistInstallerDir $setupName
        if (-not (Test-Path $setupPath)) {
            throw "Inno Setup did not produce the expected $setupPath."
        }
        Copy-Item -Path $setupPath -Destination (Join-Path $DistDir $setupName) -Force
        Write-Host "Setup executable: $DistDir\$setupName ($((Get-Item $setupPath).Length) bytes)" -ForegroundColor Green
    }
    else {
        Write-Host "Skipping Inno Setup installer build (-SkipInnoSetup)." -ForegroundColor Yellow
    }

    Write-Step "Generating build-provenance.json"
    $resolvedSourceCommit = Get-ResolvedSourceCommit
    $buildTimestamp = (Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ')
    $pyInstallerVersion = (& $VenvPy -m PyInstaller --version) | Select-Object -Last 1
    $pythonVersion = ((& $VenvPy --version) -replace 'Python ', '').Trim()

    $provenanceArgs = @(
        '--output', (Join-Path $RepoRoot 'build-provenance.json'),
        '--application-version', "v$Version",
        '--source-commit', $resolvedSourceCommit,
        '--source-ref', ($env:GITHUB_REF_NAME ? $env:GITHUB_REF_NAME : (git -C $RepoRoot rev-parse --abbrev-ref HEAD)),
        '--linux-source-commit', $LinuxSourceCommit,
        '--macos-source-commit', $MacosSourceCommit,
        '--source-equivalence-verified', $(if ($resolvedSourceCommit -eq $LinuxSourceCommit -and $resolvedSourceCommit -eq $MacosSourceCommit) { 'true' } else { 'false' }),
        '--build-timestamp-utc', $buildTimestamp,
        '--runner-image', ($env:ImageOS ? $env:ImageOS : 'local-dev'),
        '--python-version', $pythonVersion,
        '--pyinstaller-version', $pyInstallerVersion,
        '--installer-tool-version', $(if (-not $SkipInnoSetup -and $iscc) { (& $iscc.Source '/?' 2>&1 | Select-Object -First 1) } else { 'not-built' }),
        '--workflow-name', ($env:GITHUB_WORKFLOW ? $env:GITHUB_WORKFLOW : 'local-dev'),
        '--workflow-run-id', ($env:GITHUB_RUN_ID ? $env:GITHUB_RUN_ID : '0'),
        '--workflow-run-attempt', ($env:GITHUB_RUN_ATTEMPT ? $env:GITHUB_RUN_ATTEMPT : '0')
    )
    foreach ($f in @("CHIRP-windows-v$Version-x86_64-portable.zip", "CHIRP-windows-v$Version-x86_64-setup.exe")) {
        $fp = Join-Path $DistDir $f
        if (Test-Path $fp) {
            $hash = (Get-FileHash -Path $fp -Algorithm SHA256).Hash.ToLower()
            $provenanceArgs += '--artifact'
            $provenanceArgs += "$f=$hash"
        }
    }
    Invoke-Checked $VenvPy (Join-Path $ScriptDir 'generate-provenance.py') @provenanceArgs

    Write-Step "Generating SHA256SUMS"
    $sumsPath = Join-Path $RepoRoot 'SHA256SUMS'
    $sumLines = @()
    foreach ($f in @(
            "CHIRP-windows-v$Version-x86_64-portable.zip",
            "CHIRP-windows-v$Version-x86_64-setup.exe"
        )) {
        $fp = Join-Path $DistDir $f
        if (Test-Path $fp) {
            $hash = (Get-FileHash -Path $fp -Algorithm SHA256).Hash.ToLower()
            $sumLines += "$hash  $f"
        }
    }
    foreach ($f in @('build-provenance.json', 'THIRD_PARTY_LICENSES.txt')) {
        $fp = Join-Path $RepoRoot $f
        if (Test-Path $fp) {
            $hash = (Get-FileHash -Path $fp -Algorithm SHA256).Hash.ToLower()
            $sumLines += "$hash  $f"
        }
    }
    Set-Content -Path $sumsPath -Value ($sumLines -join "`n") -NoNewline
    Write-Host (Get-Content $sumsPath -Raw)

    Write-Step "Re-validating every checksum in SHA256SUMS"
    foreach ($line in $sumLines) {
        $parts = $line -split '\s\s', 2
        $expected = $parts[0]
        $file = $parts[1]
        $searchPaths = @((Join-Path $DistDir $file), (Join-Path $RepoRoot $file))
        $found = $searchPaths | Where-Object { Test-Path $_ } | Select-Object -First 1
        if (-not $found) {
            throw "SHA256SUMS references $file but it was not found in $DistDir or $RepoRoot."
        }
        $actual = (Get-FileHash -Path $found -Algorithm SHA256).Hash.ToLower()
        if ($actual -ne $expected) {
            throw "Checksum mismatch for $file`: expected $expected, got $actual"
        }
        Write-Host "  verified $file"
    }

    Write-Host "Package complete." -ForegroundColor Green
}

# --- Dispatch -------------------------------------------------------------
switch ($Mode) {
    'Build' { Invoke-Build }
    'Test' { Invoke-Test }
    'Package' { Invoke-Package }
    'All' {
        Invoke-Build
        Invoke-Test
        Invoke-Package
    }
}

exit 0
