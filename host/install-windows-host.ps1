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
& $uvPath pip install --python $python --reinstall $stagedWheel
if ($LASTEXITCODE -ne 0) {
    throw 'uv could not install the RetroBridge wheel.'
}
& $python -m playwright install chromium
if ($LASTEXITCODE -ne 0) {
    throw 'Playwright could not install its native Windows Chromium runtime.'
}

if (-not (Test-Path -LiteralPath $retrobridge -PathType Leaf)) {
    throw "RetroBridge installation did not create $retrobridge"
}

Write-Output "RetroBridge Windows host installed: $retrobridge"
Write-Output 'Run pairing natively in PowerShell before building guest media:'
Write-Output "  & '$retrobridge' pair"
