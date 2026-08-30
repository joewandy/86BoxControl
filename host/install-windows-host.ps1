[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateScript({ Test-Path -LiteralPath $_ -PathType Leaf })]
    [string] $WheelPath,

    [Parameter(Mandatory = $true)]
    [ValidateScript({ Test-Path -LiteralPath $_ -PathType Container })]
    [string] $SettingsPublishDirectory,

    [string] $SupportDirectory = (Join-Path ([Environment]::GetFolderPath('LocalApplicationData')) 'RetroBridge98'),

    [string] $StartMenuDirectory = (Join-Path ([Environment]::GetFolderPath('ApplicationData')) 'Microsoft\Windows\Start Menu\Programs\RetroBridge98'),

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

$supportDirectory = [IO.Path]::GetFullPath($SupportDirectory)
$startMenuDirectory = [IO.Path]::GetFullPath($StartMenuDirectory)
foreach ($nativePath in @($supportDirectory, $startMenuDirectory)) {
    if (-not [IO.Path]::IsPathRooted($nativePath) -or $nativePath.StartsWith('\\')) {
        throw "Native installation paths must be rooted local Windows paths: $nativePath"
    }
}
$environmentDirectory = Join-Path $supportDirectory 'venv'
$packageDirectory = Join-Path $supportDirectory 'packages'
$python = Join-Path $environmentDirectory 'Scripts\python.exe'
$retrobridge = Join-Path $environmentDirectory 'Scripts\retrobridge.exe'
$assetsDirectory = Join-Path $supportDirectory 'assets'
$iconPath = Join-Path $assetsDirectory 'retrobridge98.ico'
$shortcutPath = Join-Path $startMenuDirectory 'RetroBridge98.lnk'
$settingsShortcutPath = Join-Path $startMenuDirectory 'RetroBridge98 Settings.lnk'
$settingsDirectory = Join-Path $supportDirectory 'settings-app'
$settingsExecutable = Join-Path $settingsDirectory 'RetroBridge98.Settings.exe'
$resolvedWheel = (Resolve-Path -LiteralPath $WheelPath).Path
$resolvedSettingsPublish = (Resolve-Path -LiteralPath $SettingsPublishDirectory).Path

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

$settingsStaging = Join-Path $supportDirectory ('settings-app.new-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $settingsStaging -Force | Out-Null
Copy-Item -Path (Join-Path $resolvedSettingsPublish '*') -Destination $settingsStaging -Recurse -Force
$stagedSettingsExecutable = Join-Path $settingsStaging 'RetroBridge98.Settings.exe'
if (-not (Test-Path -LiteralPath $stagedSettingsExecutable -PathType Leaf)) {
    throw "The WPF publish directory does not contain RetroBridge98.Settings.exe: $resolvedSettingsPublish"
}
$settingsBackup = $null
if (Test-Path -LiteralPath $settingsDirectory -PathType Container) {
    $settingsBackup = Join-Path $supportDirectory ('settings-app.backup-' + [guid]::NewGuid().ToString('N'))
    Move-Item -LiteralPath $settingsDirectory -Destination $settingsBackup
}
try {
    Move-Item -LiteralPath $settingsStaging -Destination $settingsDirectory
} catch {
    if ($settingsBackup -and -not (Test-Path -LiteralPath $settingsDirectory)) {
        Move-Item -LiteralPath $settingsBackup -Destination $settingsDirectory
    }
    throw
}
if ($settingsBackup -and (Test-Path -LiteralPath $settingsBackup -PathType Container)) {
    Remove-Item -LiteralPath $settingsBackup -Recurse -Force
}

New-Item -ItemType Directory -Path $assetsDirectory -Force | Out-Null
& $python -m retrobridge.windows_launcher $iconPath
if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $iconPath -PathType Leaf)) {
    throw 'RetroBridge could not generate its Windows application icon.'
}

New-Item -ItemType Directory -Path $startMenuDirectory -Force | Out-Null
$windowsShell = New-Object -ComObject WScript.Shell
$shortcut = $windowsShell.CreateShortcut($shortcutPath)
$shortcut.TargetPath = $settingsExecutable
$shortcut.Arguments = '--launch'
$shortcut.WorkingDirectory = $supportDirectory
$shortcut.IconLocation = "$iconPath,0"
$shortcut.Description = 'Run the RetroBridge98 host for the Windows 98 browser'
$shortcut.Save()

$settingsShortcut = $windowsShell.CreateShortcut($settingsShortcutPath)
$settingsShortcut.TargetPath = $settingsExecutable
$settingsShortcut.WorkingDirectory = $supportDirectory
$settingsShortcut.IconLocation = "$iconPath,0"
$settingsShortcut.Description = 'Configure RetroBridge98 browser, pairing, downloads, and startup'
$settingsShortcut.Save()

Write-Output "RetroBridge Windows host installed: $retrobridge"
Write-Output "Start Menu launcher installed: $shortcutPath"
Write-Output "Settings application installed: $settingsExecutable"
Write-Output "Settings shortcut installed: $settingsShortcutPath"
Write-Output 'RetroBridge will only run when launched; this installer does not enable autostart.'
Write-Output 'Run pairing natively in PowerShell before building guest media:'
Write-Output "  & '$retrobridge' pair"
