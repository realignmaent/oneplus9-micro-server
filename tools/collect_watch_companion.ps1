<#
.SYNOPSIS
Read the OPPO Health installation from the user's vivo phone for offline analysis.
.DESCRIPTION
Requires an explicitly selected, authorized vivo ADB device. Reads device/app
metadata and copies installed APK files only. Does not change pairing, settings,
apps or watch firmware. Does not collect health records or Bluetooth logs.
.EXAMPLE
.\tools\collect_watch_companion.ps1 -Serial VIVO_SERIAL
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^[A-Za-z0-9._:-]+$')]
    [string]$Serial,

    [ValidatePattern('^[A-Za-z][A-Za-z0-9_]*(\.[A-Za-z][A-Za-z0-9_]*)+$')]
    [string]$PackageName = 'com.heytap.health',

    [string]$AdbPath = 'adb',
    [string]$OutputRoot = (Join-Path $PSScriptRoot '..\artifacts\watch-w301cn')
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

# This collector is for the daily vivo phone, never the OnePlus 9 server.
if (($env:OP9_ADB_SERIAL -and $Serial -eq $env:OP9_ADB_SERIAL) -or $Serial -like '192.168.31.172*') {
    throw 'Select the daily vivo phone. Server administration must use SSH.'
}
$adbCommand = Get-Command -Name $AdbPath -CommandType Application -ErrorAction Stop
$adbExecutable = $adbCommand.Source

function Invoke-SelectedAdb {
    param([string[]]$CommandArgs)
    $savedPreference = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        $result = @(& $adbExecutable -s $Serial @CommandArgs 2>&1)
        $commandExitCode = $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $savedPreference
    }
    if ($commandExitCode -ne 0) {
        throw "ADB failed ($commandExitCode): $($result -join [Environment]::NewLine)"
    }
    return ($result | ForEach-Object { $_.ToString() })
}

$deviceState = (Invoke-SelectedAdb -CommandArgs @('get-state') | Out-String).Trim()
if ($deviceState -ne 'device') {
    throw 'The selected phone is not connected and authorized.'
}
$manufacturer = (Invoke-SelectedAdb -CommandArgs @('shell', 'getprop', 'ro.product.manufacturer') | Out-String).Trim()
if ($manufacturer -ine 'vivo') {
    throw "Expected a vivo phone; detected manufacturer '$manufacturer'. No files collected."
}
$model = (Invoke-SelectedAdb -CommandArgs @('shell', 'getprop', 'ro.product.model') | Out-String).Trim()
$androidVersion = (Invoke-SelectedAdb -CommandArgs @('shell', 'getprop', 'ro.build.version.release') | Out-String).Trim()
$packagePaths = @(Invoke-SelectedAdb -CommandArgs @('shell', 'pm', 'path', $PackageName))
$apkPaths = @($packagePaths | Where-Object { $_ -match '^package:/data/app/.+\.apk$' } | ForEach-Object { $_.Substring(8).Trim() })
if ($apkPaths.Count -eq 0) {
    $candidates = @(Invoke-SelectedAdb -CommandArgs @('shell', 'pm', 'list', 'packages') | Where-Object { $_ -match '(?i)(heytap|oppo|oneplus).*?(health|wear)' })
    throw "No installed APK found for $PackageName. Matching packages: $($candidates -join ', '). Use -PackageName to select the actual companion."
}
foreach ($remotePath in $apkPaths) {
    if ($remotePath -notmatch '^/data/app/[A-Za-z0-9_./=+@~-]+\.apk$' -or $remotePath.Contains('/../')) {
        throw 'Unexpected APK path. Stopping before any files are copied.'
    }
}
$packageDetails = @(Invoke-SelectedAdb -CommandArgs @('shell', 'dumpsys', 'package', $PackageName))
$versionLines = @($packageDetails | Where-Object { $_ -match '^\s*version(Name|Code)=' } | Select-Object -First 2 | ForEach-Object { $_.Trim() })
$runName = '{0}-{1}' -f (Get-Date -Format 'yyyyMMdd-HHmmss'), ([Guid]::NewGuid().ToString('N').Substring(0, 8))
$outputDirectory = [System.IO.Path]::GetFullPath((Join-Path $OutputRoot $runName))
New-Item -ItemType Directory -Path $outputDirectory -Force | Out-Null
$manifestPath = Join-Path $outputDirectory 'manifest.json'
$manifest = [ordered]@{
    collected_at = [DateTimeOffset]::Now.ToString('o')
    complete = $false
    manufacturer = $manufacturer
    model = $model
    android_version = $androidVersion
    package = $PackageName
    package_version = $versionLines
    scope = 'Installed APKs and app/device version metadata only'
    watch_firmware_user_reported = 'W301CN_11_A.71'
    dashboard_implemented = $false
    apks = @()
}
$manifest | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $manifestPath -Encoding UTF8
for ($index = 0; $index -lt $apkPaths.Count; $index++) {
    $fileName = '{0:D2}-{1}' -f $index, [System.IO.Path]::GetFileName($apkPaths[$index])
    $localPath = Join-Path $outputDirectory $fileName
    Invoke-SelectedAdb -CommandArgs @('pull', $apkPaths[$index], $localPath) | Out-Null
    $manifest.apks += [ordered]@{
        file = $fileName
        bytes = (Get-Item -LiteralPath $localPath).Length
        sha256 = (Get-FileHash -LiteralPath $localPath -Algorithm SHA256).Hash.ToLowerInvariant()
    }
    $manifest | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $manifestPath -Encoding UTF8
}
$manifest.complete = $true
$manifest | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $manifestPath -Encoding UTF8
Write-Output "Collected $PackageName from $model (Android $androidVersion)."
Write-Output "Evidence directory: $outputDirectory"
Write-Output 'Ready for offline analysis; watch dashboard support has not yet been established.'
