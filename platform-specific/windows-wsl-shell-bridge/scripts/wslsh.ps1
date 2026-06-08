param(
    [Parameter(ValueFromPipeline = $true)]
    [AllowEmptyString()]
    [string] $PipelineInput,

    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]] $CommandText,

    [string] $Distro = "",
    [string] $Shell = "bash",
    [switch] $Login
)

$ErrorActionPreference = "Stop"

function ConvertTo-WslPath {
    param([Parameter(Mandatory = $true)][string] $Path)

    $fullPath = [System.IO.Path]::GetFullPath($Path)
    if ($fullPath -match '^([A-Za-z]):\\(.*)$') {
        $drive = $matches[1].ToLowerInvariant()
        $rest = $matches[2] -replace '\\', '/'
        return "/mnt/$drive/$rest"
    }

    throw "Cannot convert path to WSL path: $Path"
}

$skillRoot = Split-Path -Parent $PSScriptRoot
$tempDir = Join-Path $skillRoot ".tmp"
New-Item -ItemType Directory -Force -Path $tempDir | Out-Null

$pipelineText = ""
if ($null -ne $PipelineInput) {
    $pipelineText = $PipelineInput
} else {
    $pipelineText = [string]::Join("`n", @($input))
}

$script = ""
if ($CommandText.Count -gt 0) {
    $script = [string]::Join(" ", $CommandText)
} elseif (-not [string]::IsNullOrWhiteSpace($pipelineText)) {
    $script = $pipelineText
} else {
    $script = [Console]::In.ReadToEnd()
}

if ([string]::IsNullOrWhiteSpace($script)) {
    throw "No WSL script was provided on stdin or as arguments."
}

$script = $script -replace "`r`n", "`n" -replace "`r", "`n"
$id = [Guid]::NewGuid().ToString("N")
$tempScript = Join-Path $tempDir "$id.sh"
$utf8NoBom = [System.Text.UTF8Encoding]::new($false)
[System.IO.File]::WriteAllText($tempScript, $script, $utf8NoBom)

try {
    $linuxScript = ConvertTo-WslPath $tempScript
    $linuxCwd = ConvertTo-WslPath (Get-Location).Path

    $wslArgs = @()
    if ($Distro) {
        $wslArgs += @("-d", $Distro)
    }
    $wslArgs += @("--cd", $linuxCwd)

    $shellArgs = @()
    if ($Login) {
        $shellArgs += "-l"
    }
    $shellArgs += $linuxScript

    & wsl.exe @wslArgs $Shell @shellArgs
    exit $LASTEXITCODE
}
finally {
    Remove-Item -LiteralPath $tempScript -Force -ErrorAction SilentlyContinue
}
