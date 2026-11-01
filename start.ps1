# Lancement de SmartHome sous Windows (après install.ps1).
#   .\start.ps1               Assistant vocal (micro + haut-parleur)
#   .\start.ps1 -Server       Passerelle seule, sans micro (python -m gateway)
param([switch]$Server)

Set-Location $PSScriptRoot
$Py = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-Not (Test-Path $Py)) {
    Write-Host "❌ Environnement absent : lancez d'abord install.ps1" -ForegroundColor Red
    exit 1
}

if ($Server) {
    Write-Host "🟢 Démarrage de la passerelle SmartHome..." -ForegroundColor Cyan
    & $Py -m gateway @args
} else {
    Write-Host "🎙️ Démarrage de l'assistant SmartHome..." -ForegroundColor Cyan
    & $Py main.py @args
}
exit $LASTEXITCODE
