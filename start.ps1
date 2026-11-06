# Script de lancement de SmartHome sous Windows (après install.ps1).
#   .\start.ps1                 Assistant vocal (micro + haut-parleur)
#   .\start.ps1 -Server         Passerelle seule, sans micro (python -m gateway)
#   .\start.ps1 -Profile cloud  Profil de configuration (profiles/*.env)
#   .\start.ps1 -NoMenu         Pas de menu : reprend le dernier profil choisi
#   .\start.ps1 -Setup          Configuration pas à pas (crée le profil perso)

[CmdletBinding()]
param(
    [switch]$Server,          # Passerelle seule, sans micro (python -m gateway)
    [string]$Profile = "",    # Profil de configuration (profiles/*.env)
    [switch]$NoMenu,          # Pas de menu interactif
    [switch]$Setup,           # Configuration pas à pas (crée le profil perso)
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$RemainingArgs
)

Set-Location $PSScriptRoot
$env:PYTHONIOENCODING = "utf-8"
$env:PYTHONUTF8 = "1"
$Py = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-Not (Test-Path $Py)) {
    Write-Host "❌ Environnement absent : lancez d'abord install.ps1" -ForegroundColor Red
    exit 1
}

if ($Profile) {
    $env:SMARTHOME_PROFILE = $Profile
} elseif ($Setup -or (-Not $NoMenu -and -Not $env:SMARTHOME_PROFILE -and -Not [Console]::IsInputRedirected)) {
    $setupFlag = if ($Setup) { "True" } else { "False" }
    $chosen = & $Py -c "from core.profiles import choose_profile; print(choose_profile(setup=$setupFlag))"
    if ($LASTEXITCODE -eq 0 -and $chosen) {
        $env:SMARTHOME_PROFILE = "$chosen".Trim()
    }
}

if ($Server) {
    Write-Host "🟢 Démarrage de la passerelle SmartHome..." -ForegroundColor Cyan
    & $Py -m gateway @RemainingArgs
} else {
    Write-Host "🎙️ Démarrage de l'assistant SmartHome..." -ForegroundColor Cyan
    & $Py main.py @RemainingArgs
}
exit $LASTEXITCODE