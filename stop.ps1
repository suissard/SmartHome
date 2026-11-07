# Script d'arrêt de SmartHome sous Windows (service ou processus en cours).
#   .\stop.ps1             Arrête la tâche planifiée et/ou les processus actifs
#   .\stop.ps1 -Disable    Arrête et désactive la tâche planifiée de démarrage automatique
#   .\stop.ps1 -Status     Affiche l'état d'exécution sans rien modifier
#   .\stop.ps1 -Restart    Arrête puis relance SmartHome

[CmdletBinding()]
param(
    [switch]$Disable,
    [switch]$Status,
    [switch]$Restart
)

$TaskName = "SmartHome"
$StoppedAnything = $false

if ($Status) {
    Write-Host "🔍 État de SmartHome :" -ForegroundColor Cyan
    $active = $false
    try {
        $task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
        if ($task) {
            $state = $task.State
            Write-Host "  • Tâche planifiée '$TaskName' : $state"
            if ($state -eq "Running") { $active = $true }
        }
    } catch {}

    $procs = Get-Process python, pythonw -ErrorAction SilentlyContinue | Where-Object {
        $_.Path -like "$PSScriptRoot\.venv\*" -or $_.CommandLine -like "*main.py*" -or $_.CommandLine -like "*gateway*"
    }
    if ($procs) {
        $pids = ($procs | ForEach-Object { $_.Id }) -join ", "
        Write-Host "  • Processus python local : ACTIF (PID: $pids)" -ForegroundColor Green
        $active = $true
    }
    if (-not $active) {
        Write-Host "`nSmartHome n'est pas en cours d'exécution." -ForegroundColor Yellow
    }
    exit 0
}

Write-Host "🛑 Arrêt de SmartHome..." -ForegroundColor Cyan

# 1. Tâche planifiée Windows
try {
    $task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    if ($task) {
        if ($task.State -eq "Running") {
            Write-Host "  • Arrêt de la tâche planifiée '$TaskName'..."
            Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
            $StoppedAnything = $true
        }
        if ($Disable) {
            Disable-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
            Write-Host "  • Démarrage automatique Windows désactivé."
            $StoppedAnything = $true
        }
    }
} catch {}

# 2. Processus locaux
$procs = Get-Process python, pythonw -ErrorAction SilentlyContinue | Where-Object {
    $_.Path -like "$PSScriptRoot\.venv\*"
}
if ($procs) {
    $pids = ($procs | ForEach-Object { $_.Id }) -join ", "
    Write-Host "  • Arrêt des processus locaux (PID: $pids)..."
    $procs | Stop-Process -Force -ErrorAction SilentlyContinue
    $StoppedAnything = $true
}

if ($StoppedAnything) {
    Write-Host "`n✅ SmartHome a été arrêté avec succès." -ForegroundColor Green
} else {
    Write-Host "`nℹ️ SmartHome n'était pas en cours d'exécution." -ForegroundColor Yellow
}

if ($Restart) {
    Write-Host "`n🚀 Redémarrage de SmartHome..." -ForegroundColor Cyan
    & "$PSScriptRoot\start.ps1"
    exit 0
}

Write-Host "`nPour relancer SmartHome :"
Write-Host "  • En direct : .\start.ps1"
