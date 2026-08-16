<#
Fetch and prepare non-committed Windows vendor files for a release build.

Outputs:
  vendor/vlc/        pruned VLC 3.0.21 runtime, including hrtfs/
  vendor/webview2/   WebView2 bridge DLLs from the official NuGet package
  packaging/redist/  VC++ and WebView2 runtime installers for Inno Setup

Run from the repository root on Windows:
  powershell -ExecutionPolicy Bypass -File packaging/fetch_vendor_windows.ps1
#>

$ErrorActionPreference = "Stop"

$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
$VendorDir = Join-Path $Root "vendor"
$TempDir = Join-Path $Root ".vendor-tmp"
$RedistDir = Join-Path $Root "packaging\redist"
$VlcVersion = "3.0.21"
$VlcArchive = Join-Path $TempDir "vlc-$VlcVersion-win64.7z"
$VlcUrl = "https://download.videolan.org/pub/videolan/vlc/$VlcVersion/win64/vlc-$VlcVersion-win64.7z"
$WebView2Nuget = Join-Path $TempDir "Microsoft.Web.WebView2.nupkg"
$WebView2NugetUrl = "https://www.nuget.org/api/v2/package/Microsoft.Web.WebView2"
$VcRedistUrl = "https://aka.ms/vs/17/release/vc_redist.x64.exe"
# Evergreen standalone WebView2 Runtime installer.  This is Microsoft's offline
# installer endpoint and is intentionally packaged so users do not need a manual
# runtime download for Web mode.
$WebView2RuntimeUrl = "https://go.microsoft.com/fwlink/p/?LinkId=2124703"

function Download-File($Url, $Destination) {
    Write-Host "Downloading $Url"
    New-Item -ItemType Directory -Force -Path (Split-Path $Destination) | Out-Null
    Invoke-WebRequest -Uri $Url -OutFile $Destination -UseBasicParsing
}

function Unblock-Tree($Path) {
    if (Test-Path $Path) {
        Get-ChildItem -LiteralPath $Path -Recurse -Force | ForEach-Object {
            try { Unblock-File -LiteralPath $_.FullName -ErrorAction SilentlyContinue } catch {}
        }
    }
}

function Read-Whitelist($Path) {
    Get-Content -LiteralPath $Path |
        ForEach-Object { $_.Trim() } |
        Where-Object { $_ -and -not $_.StartsWith("#") }
}

Remove-Item -LiteralPath $TempDir -Recurse -Force -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force -Path $TempDir, $VendorDir, $RedistDir | Out-Null

# ------------------------------------------------------------------------- VLC
Download-File $VlcUrl $VlcArchive
$VlcExtract = Join-Path $TempDir "vlc"
New-Item -ItemType Directory -Force -Path $VlcExtract | Out-Null
& 7z x $VlcArchive "-o$VlcExtract" -y | Out-Host
if ($LASTEXITCODE -ne 0) { throw "7z failed to extract VLC archive" }

$VlcSource = Get-ChildItem -LiteralPath $VlcExtract -Directory | Select-Object -First 1
if (-not $VlcSource) { throw "Could not find extracted VLC directory" }
$VlcTarget = Join-Path $VendorDir "vlc"
Remove-Item -LiteralPath $VlcTarget -Recurse -Force -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force -Path $VlcTarget | Out-Null

# Copy root runtime DLLs and only the helper EXE needed to generate plugins.dat.
Get-ChildItem -LiteralPath $VlcSource.FullName -File | Where-Object {
    $_.Extension -ieq ".dll" -or $_.Name -ieq "vlc-cache-gen.exe"
} | Copy-Item -Destination $VlcTarget -Force

# Keep the HRTF directory.  This is required for VLC's binaural spatial audio
# and must stay beside libvlccore.dll in vendor/vlc/hrtfs.
$HrtfSource = Join-Path $VlcSource.FullName "hrtfs"
if (Test-Path $HrtfSource) {
    Copy-Item -LiteralPath $HrtfSource -Destination (Join-Path $VlcTarget "hrtfs") -Recurse -Force
} else {
    Write-Warning "VLC archive did not contain hrtfs/; spatial audio HRTF will be missing."
}

$PluginSource = Join-Path $VlcSource.FullName "plugins"
$PluginTarget = Join-Path $VlcTarget "plugins"
New-Item -ItemType Directory -Force -Path $PluginTarget | Out-Null
$Whitelist = Read-Whitelist (Join-Path $Root "packaging\vlc-plugin-whitelist.txt")
foreach ($Name in $Whitelist) {
    $SourceDir = Join-Path $PluginSource $Name
    if (Test-Path $SourceDir) {
        Copy-Item -LiteralPath $SourceDir -Destination (Join-Path $PluginTarget $Name) -Recurse -Force
    } else {
        Write-Host "VLC plugin category not present in this VLC build: $Name"
    }
}
Remove-Item -LiteralPath (Join-Path $PluginTarget "plugins.dat") -Force -ErrorAction SilentlyContinue

$CacheGen = Join-Path $VlcTarget "vlc-cache-gen.exe"
if (Test-Path $CacheGen) {
    Push-Location $VlcTarget
    try {
        & $CacheGen "plugins" | Out-Host
        if ($LASTEXITCODE -ne 0) { throw "vlc-cache-gen.exe failed" }
    } finally {
        Pop-Location
    }
    # Runtime does not need the cache generator once plugins.dat exists.
    Remove-Item -LiteralPath $CacheGen -Force -ErrorAction SilentlyContinue
} else {
    Write-Warning "vlc-cache-gen.exe not found; VLC may scan plugins on first startup."
}
Unblock-Tree $VlcTarget

# -------------------------------------------------------------- WebView2 DLLs
Download-File $WebView2NugetUrl $WebView2Nuget
$WebView2Zip = Join-Path $TempDir "Microsoft.Web.WebView2.zip"
Copy-Item -LiteralPath $WebView2Nuget -Destination $WebView2Zip -Force
$WebView2Extract = Join-Path $TempDir "webview2"
New-Item -ItemType Directory -Force -Path $WebView2Extract | Out-Null
Expand-Archive -LiteralPath $WebView2Zip -DestinationPath $WebView2Extract -Force

$WebView2Target = Join-Path $VendorDir "webview2"
Remove-Item -LiteralPath $WebView2Target -Recurse -Force -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force -Path $WebView2Target | Out-Null

$CoreDll = $null
foreach ($Relative in @(
    "lib\net462\Microsoft.Web.WebView2.Core.dll",
    "lib\netcoreapp3.0\Microsoft.Web.WebView2.Core.dll",
    "lib\netstandard2.0\Microsoft.Web.WebView2.Core.dll"
)) {
    $Candidate = Join-Path $WebView2Extract $Relative
    if (Test-Path $Candidate) {
        $CoreDll = Get-Item -LiteralPath $Candidate
        break
    }
}
$LoaderDll = Get-ChildItem -LiteralPath $WebView2Extract -Recurse -Filter "WebView2Loader.dll" |
    Where-Object { $_.FullName -match "win-x64" } |
    Sort-Object FullName | Select-Object -First 1
if (-not $CoreDll) { throw "Microsoft.Web.WebView2.Core.dll not found in NuGet package" }
if (-not $LoaderDll) { throw "win-x64 WebView2Loader.dll not found in NuGet package" }
Copy-Item -LiteralPath $CoreDll.FullName -Destination (Join-Path $WebView2Target "Microsoft.Web.WebView2.Core.dll") -Force
Copy-Item -LiteralPath $LoaderDll.FullName -Destination (Join-Path $WebView2Target "WebView2Loader.dll") -Force
Unblock-Tree $WebView2Target

# ------------------------------------------------------------------- Redists
Download-File $VcRedistUrl (Join-Path $RedistDir "vc_redist.x64.exe")
Download-File $WebView2RuntimeUrl (Join-Path $RedistDir "MicrosoftEdgeWebView2RuntimeInstallerX64.exe")
Unblock-Tree $RedistDir

Write-Host "Vendor preparation complete."
Write-Host "  VLC:      $VlcTarget"
Write-Host "  WebView2: $WebView2Target"
Write-Host "  Redists:  $RedistDir"
