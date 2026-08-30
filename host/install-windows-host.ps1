[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateScript({ Test-Path -LiteralPath $_ -PathType Leaf })]
    [string] $WheelPath,

    [switch] $Force
)

$ErrorActionPreference = 'Stop'

$uv = Get-Command uv.exe -ErrorAction SilentlyContinue
if ($uv) {
    $uvPath = $uv.Source
} else {
    $uvPath = Get-ChildItem -LiteralPath "$env:LOCALAPPDATA\Microsoft\WinGet\Packages" `
        -Filter 'uv.exe' -Recurse -ErrorAction SilentlyContinue |
        Select-Object -First 1 -ExpandProperty FullName
    if (-not $uvPath) {
        throw 'uv.exe is required. Install the official Astral uv package, then rerun this script.'
    }
}

$supportDirectory = Join-Path $env:LOCALAPPDATA 'RetroBridge98'
$environmentDirectory = Join-Path $supportDirectory 'venv'
$packageDirectory = Join-Path $supportDirectory 'packages'
$python = Join-Path $environmentDirectory 'Scripts\python.exe'
$retrobridge = Join-Path $environmentDirectory 'Scripts\retrobridge.exe'
$assetsDirectory = Join-Path $supportDirectory 'assets'
$iconPath = Join-Path $assetsDirectory 'retrobridge98.ico'
$startMenuDirectory = Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs\RetroBridge98'
$shortcutPath = Join-Path $startMenuDirectory 'RetroBridge98.lnk'
$resolvedWheel = (Resolve-Path -LiteralPath $WheelPath).Path

if ((Test-Path -LiteralPath $environmentDirectory) -and -not $Force) {
    throw "The Windows environment already exists at $environmentDirectory. Pass -Force to update it."
}

New-Item -ItemType Directory -Path $packageDirectory -Force | Out-Null
$stagedWheel = Join-Path $packageDirectory (Split-Path -Leaf $resolvedWheel)
Copy-Item -LiteralPath $resolvedWheel -Destination $stagedWheel -Force

& $uvPath python find 3.12 | Out-Null
if ($LASTEXITCODE -ne 0) {
    & $uvPath python install 3.12
    & $uvPath python find 3.12 | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw 'uv could not install or find native Windows Python 3.12.'
    }
}
if (-not (Test-Path -LiteralPath $python)) {
    & $uvPath venv --python 3.12 $environmentDirectory
    if ($LASTEXITCODE -ne 0) {
        throw 'uv could not create the native Windows virtual environment.'
    }
}

$installedPackage = Join-Path $environmentDirectory 'Lib\site-packages\retrobridge'
$packageBackup = $null
if ($Force -and (Test-Path -LiteralPath $installedPackage -PathType Container)) {
    $updateBackupDirectory = Join-Path $supportDirectory 'update-backup'
    New-Item -ItemType Directory -Path $updateBackupDirectory -Force | Out-Null
    $packageBackup = Join-Path $updateBackupDirectory (
        'retrobridge-' + [guid]::NewGuid().ToString('N')
    )
    Move-Item -LiteralPath $installedPackage -Destination $packageBackup
}

& $uvPath pip install --python $python --reinstall-package retrobridge98 $stagedWheel
if ($LASTEXITCODE -ne 0) {
    if ($packageBackup -and
        (Test-Path -LiteralPath $packageBackup -PathType Container) -and
        -not (Test-Path -LiteralPath $installedPackage)) {
        Move-Item -LiteralPath $packageBackup -Destination $installedPackage
    }
    throw 'uv could not install the RetroBridge wheel.'
}
if ($packageBackup -and (Test-Path -LiteralPath $packageBackup -PathType Container)) {
    try {
        Remove-Item -LiteralPath $packageBackup -Recurse -Force
    } catch {
        Write-Warning "The previous generated package backup could not be removed: $packageBackup"
    }
}
& $python -m playwright install chromium
if ($LASTEXITCODE -ne 0) {
    throw 'Playwright could not install its native Windows Chromium runtime.'
}

if (-not (Test-Path -LiteralPath $retrobridge -PathType Leaf)) {
    throw "RetroBridge installation did not create $retrobridge"
}

New-Item -ItemType Directory -Path $assetsDirectory -Force | Out-Null
& $python -m retrobridge.windows_launcher $iconPath
if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $iconPath -PathType Leaf)) {
    throw 'RetroBridge could not generate its Windows application icon.'
}

New-Item -ItemType Directory -Path $startMenuDirectory -Force | Out-Null
$windowsShell = New-Object -ComObject WScript.Shell
$shortcut = $windowsShell.CreateShortcut($shortcutPath)
$shortcut.TargetPath = $env:ComSpec
$shortcut.Arguments = '/d /k ""' + $retrobridge + '" console"'
$shortcut.WorkingDirectory = $supportDirectory
$shortcut.IconLocation = "$iconPath,0"
$shortcut.Description = 'Run the RetroBridge98 host for the Windows 98 browser'
$shortcut.Save()

Write-Output "RetroBridge Windows host installed: $retrobridge"
Write-Output "Start Menu launcher installed: $shortcutPath"
Write-Output 'RetroBridge will only run when launched; this installer does not enable autostart.'
Write-Output 'Run pairing natively in PowerShell before building guest media:'
Write-Output "  & '$retrobridge' pair"
