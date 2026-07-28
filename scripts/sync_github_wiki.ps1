# Sync ai/docs/wiki/*.md -> github.com/mouxangithub/ai.wiki
# Usage: .\ai\scripts\sync_github_wiki.ps1 [-WikiRepo "https://github.com/mouxangithub/ai.wiki.git"]

param(
    [string]$WikiRepo = "https://github.com/mouxangithub/ai.wiki.git",
    [string]$CommitMessage = "docs: sync OP Agent wiki from ai/docs/wiki"
)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$AiRoot = Resolve-Path (Join-Path $ScriptDir "..")
$WikiSrc = Join-Path $AiRoot "docs\wiki"
if (-not (Test-Path $WikiSrc)) {
    throw "Wiki source not found: $WikiSrc"
}

$Tmp = Join-Path $env:TEMP ("ai-wiki-sync-" + [guid]::NewGuid().ToString("n"))
New-Item -ItemType Directory -Path $Tmp | Out-Null
try {
    Write-Host "Cloning $WikiRepo -> $Tmp"
    git clone $WikiRepo $Tmp
    if ($LASTEXITCODE -ne 0) {
        throw "git clone failed (enable Wikis in repo Settings first?): $WikiRepo"
    }
    Push-Location $Tmp

    Get-ChildItem -Path $WikiSrc -Filter "*.md" | ForEach-Object {
        $dest = Join-Path $Tmp $_.Name
        Copy-Item -Force $_.FullName $dest
        Write-Host "  copied $($_.Name)"
    }

    git add -A
    $status = git status --porcelain
    if (-not $status) {
        Write-Host "Wiki already up to date."
        exit 0
    }
    git commit -m $CommitMessage
    git push
    Write-Host "Wiki pushed successfully."
}
finally {
    Pop-Location -ErrorAction SilentlyContinue
    Remove-Item -Recurse -Force $Tmp -ErrorAction SilentlyContinue
}
