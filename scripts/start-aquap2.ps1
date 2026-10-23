<#
.SYNOPSIS
Start the aquap2 service on this PC at http://127.0.0.1:8787.
.DESCRIPTION
Uses a dedicated runtime below this project's qa folder. The service runs in
this terminal; press Ctrl+C to stop it. It never binds to an external address.
Package installation occurs only when -Setup is explicitly supplied.
.PARAMETER Rscript
Path to Rscript.exe. If omitted, search PATH and standard Windows R folders.
.PARAMETER Python
Python executable (3.10 or later). If omitted, search PATH.
.PARAMETER RuntimePath
Dedicated runtime directory below this project's qa folder.
.PARAMETER Setup
Run the fixed-version installer before starting the service. Requires internet.
.PARAMETER CheckOnly
Check the installed R environment without starting the HTTP service.
.EXAMPLE
pwsh -File scripts/start-aquap2.ps1
.EXAMPLE
pwsh -File scripts/start-aquap2.ps1 -Setup -CheckOnly
.EXAMPLE
pwsh -File scripts/start-aquap2.ps1 -Rscript 'C:/Program Files/R/R-4.6.1/bin/Rscript.exe'
#>
[CmdletBinding()]
param(
    [string]$Rscript,
    [string]$Python,
    [string]$RuntimePath,
    [switch]$Setup,
    [switch]$CheckOnly
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$projectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$qaRoot = [IO.Path]::GetFullPath((Join-Path $projectRoot 'qa'))
if (-not $RuntimePath) { $RuntimePath = Join-Path $qaRoot 'aquap2-runtime-v1.4' }
elseif (-not [IO.Path]::IsPathRooted($RuntimePath)) { $RuntimePath = Join-Path $projectRoot $RuntimePath }
$runtimeRoot = [IO.Path]::GetFullPath($RuntimePath).TrimEnd([IO.Path]::DirectorySeparatorChar, [IO.Path]::AltDirectorySeparatorChar)
$qaPrefix = $qaRoot.TrimEnd([IO.Path]::DirectorySeparatorChar) + [IO.Path]::DirectorySeparatorChar
if (-not $runtimeRoot.StartsWith($qaPrefix, [StringComparison]::OrdinalIgnoreCase)) {
    throw 'RuntimePath must be a dedicated directory below this project''s qa folder.'
}

function Resolve-Executable([string]$Requested, [string[]]$Names) {
    if ($Requested) {
        if (Test-Path -LiteralPath $Requested -PathType Leaf) { return (Resolve-Path -LiteralPath $Requested).ProviderPath }
        $found = Get-Command -Name $Requested -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($found) { return $found.Source }
        throw "Executable was not found: $Requested"
    }
    foreach ($candidateName in $Names) {
        $found = Get-Command -Name $candidateName -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($found) { return $found.Source }
    }
    return $null
}

$rExecutable = Resolve-Executable $Rscript @('Rscript.exe', 'Rscript')
if (-not $rExecutable) {
    $rCandidates = @()
    foreach ($programFolder in @($env:ProgramFiles, ${env:ProgramFiles(x86)})) {
        if (-not $programFolder) { continue }
        $rFolder = Join-Path $programFolder 'R'
        if (-not (Test-Path -LiteralPath $rFolder -PathType Container)) { continue }
        foreach ($installedR in Get-ChildItem -LiteralPath $rFolder -Directory) {
            $rVersion = $null
            if (-not [version]::TryParse(($installedR.Name -replace '^R-', ''), [ref]$rVersion)) { continue }
            foreach ($relativeExecutable in @('bin/Rscript.exe', 'bin/x64/Rscript.exe')) {
                $candidatePath = Join-Path $installedR.FullName $relativeExecutable
                if (Test-Path -LiteralPath $candidatePath -PathType Leaf) {
                    $rCandidates += [pscustomobject]@{ Version = $rVersion; Path = $candidatePath }
                }
            }
        }
    }
    $latestR = $rCandidates | Sort-Object Version -Descending | Select-Object -First 1
    if ($latestR) { $rExecutable = $latestR.Path }
}
if (-not $rExecutable) { throw 'Rscript was not found. Install R, or specify -Rscript with its full path.' }
$pythonExecutable = Resolve-Executable $Python @('python.exe', 'python3', 'python')
if (-not $pythonExecutable) { throw 'Python 3.10+ was not found. Specify -Python with its full path.' }

$runtimeFolders = @($qaRoot, $runtimeRoot)
$relativeRuntime = $runtimeRoot.Substring($qaPrefix.Length)
$pathCursor = $qaRoot
foreach ($pathPart in $relativeRuntime.Split([IO.Path]::DirectorySeparatorChar)) {
    $pathCursor = Join-Path $pathCursor $pathPart
    $runtimeFolders += $pathCursor
}
foreach ($folderName in @('library', 'home', 'settings', 'temp')) { $runtimeFolders += Join-Path $runtimeRoot $folderName }
foreach ($runtimeFolder in $runtimeFolders | Select-Object -Unique) {
    if (Test-Path -LiteralPath $runtimeFolder) {
        $runtimeItem = Get-Item -LiteralPath $runtimeFolder -Force
        if (-not $runtimeItem.PSIsContainer -or ($runtimeItem.Attributes -band [IO.FileAttributes]::ReparsePoint)) {
            throw "Runtime folders must be ordinary directories, not links or files: $runtimeFolder"
        }
    }
}

$runtimeLibrary = Join-Path $runtimeRoot 'library'
$runtimeUser = Join-Path $runtimeRoot 'home'
$runtimeSettings = Join-Path $runtimeRoot 'settings'
$runtimeTemporary = Join-Path $runtimeRoot 'temp'
$environment = @{
    AQUAP2_RUNTIME_ROOT = $runtimeRoot
    AQUAP2_LIBRARY = $runtimeLibrary
    AQUAP2SH = $runtimeSettings
    R_USER = $runtimeUser
    R_LIBS_USER = $runtimeLibrary
    TMPDIR = $runtimeTemporary
    TEMP = $runtimeTemporary
    TMP = $runtimeTemporary
}
$rBinDirectory = Split-Path -Parent $rExecutable
if ((Split-Path -Leaf $rBinDirectory) -eq 'x64') { $rBinDirectory = Split-Path -Parent $rBinDirectory }
if ((Split-Path -Leaf $rBinDirectory) -eq 'bin') { $environment['R_HOME'] = Split-Path -Parent $rBinDirectory }
# POSIX locale values inherited from a launcher can prevent Windows R from
# resolving packages in Japanese paths. Let only these child processes use
# their native locale, and restore the caller's environment in finally.
foreach ($localeEntry in Get-ChildItem Env:) {
    if ($localeEntry.Name -eq 'LANG' -or $localeEntry.Name.StartsWith('LC_', [StringComparison]::Ordinal)) {
        $environment[$localeEntry.Name] = $null
    }
}
$previousEnvironment = @{}
foreach ($name in $environment.Keys) { $previousEnvironment[$name] = [Environment]::GetEnvironmentVariable($name, 'Process') }

try {
    foreach ($runtimeFolder in $runtimeFolders | Select-Object -Unique) { [IO.Directory]::CreateDirectory($runtimeFolder) | Out-Null }
    foreach ($name in $environment.Keys) { [Environment]::SetEnvironmentVariable($name, $environment[$name], 'Process') }
    & $pythonExecutable -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)'
    if ($LASTEXITCODE -ne 0) { throw 'Python 3.10 or later is required.' }
    if ($Setup) {
        Write-Host 'Installing the fixed aquap2 package and dependencies into the isolated runtime.'
        & $rExecutable '--vanilla' (Join-Path $PSScriptRoot 'setup_aquap2.R') $runtimeRoot
        if ($LASTEXITCODE -ne 0) { throw 'aquap2 setup failed. Keep the runtime and inspect its setup/install logs.' }
    }
    if (-not (Test-Path -LiteralPath (Join-Path $runtimeRoot 'installation.json') -PathType Leaf)) {
        throw 'No fixed-version installation receipt was found. Run this script once with -Setup -CheckOnly.'
    }
    if ($CheckOnly) {
        & $rExecutable '--vanilla' (Join-Path $PSScriptRoot 'aquap2_engine.R') '--health'
        if ($LASTEXITCODE -ne 0) { throw 'The installed aquap2 runtime check failed.' }
        return
    }
    Write-Host 'aquap2 service: http://127.0.0.1:8787 (this PC only)'
    Write-Host "Isolated runtime: $runtimeRoot"
    Write-Host 'Keep this terminal open. Press Ctrl+C to stop the service.'
    Write-Host 'In the app, select aquap2 and check the connection before running an analysis.'
    & $pythonExecutable '-u' (Join-Path $projectRoot 'bridge/serve.py') '--port' '8787' '--rscript' $rExecutable '--library' $runtimeLibrary
    if ($LASTEXITCODE -ne 0) { throw 'The local aquap2 service stopped with an error. Check the terminal output.' }
}
finally {
    foreach ($name in $environment.Keys) { [Environment]::SetEnvironmentVariable($name, $previousEnvironment[$name], 'Process') }
}
