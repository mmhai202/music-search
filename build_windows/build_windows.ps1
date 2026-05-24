param(
  [switch]$Clean
)

$ErrorActionPreference = "Stop"

$BuildRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Resolve-Path (Join-Path $BuildRoot "..")
$Version = (Get-Content (Join-Path $ProjectRoot "VERSION") -Raw).Trim()
$Arch = $env:PROCESSOR_ARCHITECTURE
if ($Arch -eq "AMD64") {
  $Arch = "x86_64"
}
if (-not $Arch) {
  $Arch = "unknown"
}

$InternalBinary = "MusicSearch"
$ArtifactName = "MusicSearch-$Version-windows-$Arch.zip"
$Venv = Join-Path $BuildRoot ".venv"
$PyInstallerDist = Join-Path $BuildRoot "build\pyinstaller-dist"
$Dist = Join-Path $BuildRoot "dist"

Set-Location $ProjectRoot

if ($Clean) {
  Remove-Item -Recurse -Force (Join-Path $BuildRoot "build") -ErrorAction SilentlyContinue
  Remove-Item -Recurse -Force $Dist -ErrorAction SilentlyContinue
  Remove-Item -Recurse -Force $Venv -ErrorAction SilentlyContinue
}

if (-not (Test-Path $Venv)) {
  $HostPython = (Get-Command python -ErrorAction Stop).Source
  Write-Host "Creating venv with $HostPython"
  & $HostPython -m venv $Venv
}

$Python = Join-Path $Venv "Scripts\python.exe"
& $Python --version
& $Python -m pip install --upgrade pip
& $Python -m pip install -r (Join-Path $ProjectRoot "requirements-build.txt") -r (Join-Path $ProjectRoot "requirements-windows.txt")

foreach ($Binary in @("ffmpeg.exe", "vibra.exe")) {
  $LocalBinary = Join-Path $ProjectRoot "bin\$Binary"
  $PathBinary = Get-Command $Binary -ErrorAction SilentlyContinue
  if (-not (Test-Path $LocalBinary) -and -not $PathBinary) {
    throw "Missing $Binary. Put it in bin\$Binary or make it available on PATH."
  }
}

$env:MUSIC_SEARCH_ARTIFACT_NAME = $InternalBinary
& $Python -m PyInstaller (Join-Path $BuildRoot "music-search-windows.spec") `
  --clean `
  --workpath (Join-Path $BuildRoot "build") `
  --distpath $PyInstallerDist

$AppDir = Join-Path $PyInstallerDist $InternalBinary
if (-not (Test-Path $AppDir)) {
  throw "PyInstaller output not found: $AppDir"
}

New-Item -ItemType Directory -Force $Dist | Out-Null

$Release = [ordered]@{
  name = "Music Search"
  package = "music-search"
  version = $Version
  architecture = $Arch
  artifact = $ArtifactName
  executable = "$InternalBinary.exe"
}
$Release | ConvertTo-Json | Set-Content -Encoding UTF8 (Join-Path $AppDir "music-search.release.json")

$ZipPath = Join-Path $Dist $ArtifactName
Remove-Item -Force $ZipPath -ErrorAction SilentlyContinue
Compress-Archive -Path (Join-Path $AppDir "*") -DestinationPath $ZipPath -Force

Write-Host ""
Write-Host "Built: build_windows/dist/$ArtifactName"
