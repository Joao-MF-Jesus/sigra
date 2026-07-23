param(
    [string]$OutputPath = "SIGRA-entrega-limpa.zip"
)

$root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$destination = if ([System.IO.Path]::IsPathRooted($OutputPath)) {
    $OutputPath
} else {
    Join-Path $root $OutputPath
}

$skipDirectories = @(
    ".git",
    ".agents",
    ".codex",
    ".venv",
    "venv",
    "node_modules",
    "dist",
    "work",
    "outputs",
    "__pycache__",
    ".pytest_cache"
)

$skipExtensions = @(".db", ".sqlite", ".sqlite3", ".log", ".zip")

if (Test-Path -LiteralPath $destination) {
    Remove-Item -LiteralPath $destination -Force
}

Add-Type -AssemblyName System.IO.Compression
Add-Type -AssemblyName System.IO.Compression.FileSystem

$zip = [System.IO.Compression.ZipFile]::Open($destination, [System.IO.Compression.ZipArchiveMode]::Create)
try {
    Get-ChildItem -LiteralPath $root -Recurse -File -Force |
        Where-Object {
            $relative = $_.FullName.Substring($root.Length + 1)
            $parts = $relative -split '[\\/]'
            $isSkippedDirectory = $false
            foreach ($part in $parts) {
                if ($skipDirectories -contains $part) {
                    $isSkippedDirectory = $true
                    break
                }
            }
            -not $isSkippedDirectory -and -not ($skipExtensions -contains $_.Extension.ToLowerInvariant())
        } |
        ForEach-Object {
            $relative = $_.FullName.Substring($root.Length + 1)
            [System.IO.Compression.ZipFileExtensions]::CreateEntryFromFile($zip, $_.FullName, $relative) | Out-Null
        }
} finally {
    $zip.Dispose()
}

$item = Get-Item -LiteralPath $destination
[PSCustomObject]@{
    Package = $item.FullName
    SizeMB = [math]::Round($item.Length / 1MB, 2)
}
