# Script d'installation SmartHome — Windows 10/11 et Windows Server.
#
#   .\install.ps1                 Questions pas à pas (machine, profil, Ollama, modèles, démarrage automatique)
#   .\install.ps1 -Server         Serveur sans micro : passerelle réseau seule, jeton généré
#   .\install.ps1 -Service        Démarrage automatique à l'ouverture de session (tâche planifiée)
#   .\install.ps1 -Yes            Sans question : options de la ligne de commande et .env
#   Get-Help .\install.ps1        Toutes les options
#
# Si l'exécution des scripts est bloquée :
#   powershell -ExecutionPolicy Bypass -File .\install.ps1
#
# Une fois Python trouvé, l'assistant core/install_wizard.py demande ce qu'il faut installer ; les options
# servent de choix par défaut. Le script est idempotent : le relancer met à jour les dépendances sans écraser le .env.

[CmdletBinding()]
param(
    [switch]$Server,          # Passerelle seule, écoute réseau, jeton généré
    [switch]$Service,         # Tâche planifiée de démarrage automatique
    [string]$GatewayHost = "0.0.0.0",
    [string]$Python = "",     # Interpréteur Python à utiliser (≥ 3.10)
    [switch]$NoSystemDeps,    # Ne rien installer via winget (Python, Ollama)
    [switch]$NoOllama,        # Ne pas installer Ollama ni télécharger de modèle LLM
    [switch]$NoModels,        # Ne télécharger aucun modèle
    [switch]$Accounts,        # Comptes utilisateurs de la PWA (PocketBase téléchargé, AUTH_PROVIDER=pocketbase)
    [switch]$NoAccounts,      # Ne pas poser la question des comptes (le .env décide)
    [switch]$NoMenu,          # Pas de questions pas à pas
    [switch]$Yes              # Répondre oui à toutes les questions (implique -NoMenu)
)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
$VenvPy = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
$EnvFile = Join-Path $PSScriptRoot ".env"
$Mode = if ($Server) { "serveur sans micro" } else { "poste vocal" }

function Step($msg) { Write-Host "`n▶ $msg" -ForegroundColor Cyan }
function Info($msg) { Write-Host "  $msg" -ForegroundColor Yellow }
function Ok($msg)   { Write-Host "  ✔ $msg" -ForegroundColor Green }
function Warn($msg) { Write-Host "  ⚠️  $msg" -ForegroundColor Yellow }
function Die($msg)  { Write-Host "❌ $msg" -ForegroundColor Red; exit 1 }
function Have($cmd) { [bool](Get-Command $cmd -ErrorAction SilentlyContinue) }

function Confirm-Action($question) {
    if ($Yes) { return $true }
    $answer = Read-Host "  $question [o/N]"
    return $answer -match '^[oOyY]'
}

function Update-Path {
    # Recharge le PATH après une installation winget, sans rouvrir le terminal.
    $env:Path = [Environment]::GetEnvironmentVariable("Path", "Machine") + ";" +
                [Environment]::GetEnvironmentVariable("Path", "User")
}

function Invoke-Checked {
    param([string]$Exe, [string[]]$Arguments, [string]$Message)
    & $Exe @Arguments
    if ($LASTEXITCODE -ne 0) { Die $Message }
}

Write-Host "🚀 Installation de SmartHome ($Mode — Windows)" -ForegroundColor Cyan

# --- 1. Python -----------------------------------------------------------------
Step "1/8 Python"

function Test-Python($exe, [string[]]$prefix = @()) {
    try {
        & $exe @prefix -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" 2>$null
        return $LASTEXITCODE -eq 0
    } catch { return $false }
}

function Find-Python {
    if ($Python) {
        if (Test-Python $Python) { return @($Python) }
        Die "$Python n'est pas un Python ≥ 3.10."
    }
    # Le lanceur « py » choisit la version la plus récente installée.
    if ((Have "py") -and (Test-Python "py" @("-3"))) { return @("py", "-3") }
    # « python » peut être l'alias du Microsoft Store (sans Python réel) : Test-Python l'écarte.
    if ((Have "python") -and (Test-Python "python")) { return @("python") }
    return $null
}

$PyCmd = Find-Python
if (-Not $PyCmd) {
    if ($NoSystemDeps) { Die "Python ≥ 3.10 introuvable : installez-le depuis https://www.python.org" }
    if (-Not (Have "winget")) { Die "Python ≥ 3.10 introuvable et winget absent : installez Python depuis https://www.python.org" }
    Info "Installation de Python 3.12 via winget..."
    winget install -e --id Python.Python.3.12 --scope user --accept-package-agreements --accept-source-agreements
    Update-Path
    $PyCmd = Find-Python
    if (-Not $PyCmd) { Die "Python installé mais introuvable : rouvrez PowerShell puis relancez install.ps1." }
}
$PyExe = $PyCmd[0]
$PyArgs = @($PyCmd | Select-Object -Skip 1)
Ok "Interpréteur : $(& $PyExe @PyArgs --version)"

# --- Questions pas à pas -------------------------------------------------------
$OllamaChoice = if ($NoOllama) { "none" } else { "auto" }   # auto | install | use | remote | none
$OllamaRemoteHost = ""
$OllamaPull = @()
$ProfileName = ""
$WizardRan = $false
$AccountsChoice = if ($Accounts) { "true" } else { "" }   # true | false | vide (selon AUTH_PROVIDER du .env)

if (-Not $Yes -and -Not $NoMenu -and -Not [Console]::IsInputRedirected) {
    $flag = { param($b) if ($b) { "true" } else { "false" } }
    $wizardArgs = $PyArgs + @("core\install_wizard.py", "--platform", "windows",
        "--mode", $(if ($Server) { "server" } else { "desktop" }), "--host", $GatewayHost,
        "--system-deps", (& $flag (-Not $NoSystemDeps)), "--ollama", (& $flag (-Not $NoOllama)),
        "--models", (& $flag (-Not $NoModels)), "--service", (& $flag $Service),
        "--accounts", (& $flag (-Not $NoAccounts)))
    $plan = & $PyExe @wizardArgs
    switch ($LASTEXITCODE) {
        0 { }
        1 { exit 0 }      # « Annuler » dans le récapitulatif
        130 { exit 130 }
        default { Die "L'assistant d'installation a échoué (relancez avec -NoMenu pour s'en passer)." }
    }
    foreach ($line in $plan) {
        $key, $value = "$line".Split("=", 2)
        switch ($key) {
            "MODE" { $Server = [switch]($value -eq "server") }
            "OLLAMA" { $OllamaChoice = $value }
            "OLLAMA_HOST" { $OllamaRemoteHost = $value }
            "OLLAMA_PULL" { $OllamaPull = @($value.Split(",") | Where-Object { $_ }) }
            "DOWNLOAD_MODELS" { $NoModels = [switch]($value -ne "true") }
            "WITH_SERVICE" { $Service = [switch]($value -eq "true") }
            "GATEWAY_BIND" { if ($value) { $GatewayHost = $value } }
            "PROFILE" { $ProfileName = $value }
            "ACCOUNTS" { if ($value) { $AccountsChoice = $value } }
        }
    }
    $WizardRan = $true
    # Les étapes suivantes lisent la configuration du profil choisi (core/config.py applique SMARTHOME_PROFILE)
    if ($ProfileName) { $env:SMARTHOME_PROFILE = $ProfileName }
    Write-Host "🚀 Installation de SmartHome ($(if ($Server) { 'serveur sans micro' } else { 'poste vocal' }) — Windows)" -ForegroundColor Cyan
}

# --- 2. Environnement virtuel --------------------------------------------------
Step "2/8 Environnement Python"
if (-Not (Test-Path $VenvPy)) {
    Invoke-Checked $PyExe ($PyArgs + @("-m", "venv", ".venv")) "Création du venv impossible."
    Ok "Environnement .venv créé."
} else {
    Ok "Environnement .venv déjà présent."
}

# --- 3. Dépendances Python -----------------------------------------------------
Step "3/8 Dépendances Python"
Invoke-Checked $VenvPy @("-m", "pip", "install", "--upgrade", "pip", "wheel") "Mise à jour de pip impossible."
Invoke-Checked $VenvPy @("-m", "pip", "install", "-r", "requirements.txt") "Échec de pip install -r requirements.txt."
Ok "Dépendances installées."

# --- 4. Configuration (.env) ---------------------------------------------------
Step "4/8 Configuration"

function Get-Setting($name) {
    # Valeur validée par core/config.py (variables d'environnement > .env > défauts).
    $value = & $VenvPy -c "from core.config import get_settings; print(getattr(get_settings(), '$name'))"
    if ($LASTEXITCODE -ne 0) { Die "Le fichier .env contient une valeur invalide." }
    return "$value".Trim()
}

function Set-EnvValue($key, $value) {
    # Remplace (ou ajoute) KEY=VALUE dans .env en conservant les commentaires.
    $lines = [System.Collections.Generic.List[string]](Get-Content $EnvFile -Encoding UTF8)
    $index = -1
    for ($i = 0; $i -lt $lines.Count; $i++) {
        if ($lines[$i] -match "^\s*$([regex]::Escape($key))\s*=") { $index = $i; break }
    }
    if ($index -ge 0) { $lines[$index] = "$key=$value" } else { $lines.Add("$key=$value") }
    # UTF-8 sans BOM, lu tel quel par python-dotenv.
    [System.IO.File]::WriteAllLines($EnvFile, $lines, (New-Object System.Text.UTF8Encoding $false))
}

if (-Not (Test-Path $EnvFile)) {
    Copy-Item ".env.example" $EnvFile
    Ok ".env créé depuis .env.example."
} else {
    Ok ".env existant conservé."
}

if ($ProfileName) {
    # Même fichier que le menu de démarrage : le profil y sera présélectionné
    [System.IO.File]::WriteAllText((Join-Path $PSScriptRoot "profiles\.last"), "$ProfileName`n")
    Ok "Profil « $ProfileName » retenu."
}
if ($OllamaRemoteHost) {
    Set-EnvValue "OLLAMA_HOST" $OllamaRemoteHost
    Ok "Ollama distant : $OllamaRemoteHost."
}

if ($Server) {
    Set-EnvValue "GATEWAY_HOST" $GatewayHost
    if (-Not (Get-Setting "GATEWAY_AUTH_TOKEN")) {
        $token = & $VenvPy -c "import secrets; print(secrets.token_hex(32))"
        Set-EnvValue "GATEWAY_AUTH_TOKEN" "$token".Trim()
        Ok "Jeton de passerelle généré (GATEWAY_AUTH_TOKEN dans .env)."
    }
    Ok "Passerelle : écoute sur ${GatewayHost}:$(Get-Setting 'GATEWAY_PORT')."
}
$null = Get-Setting "LLM_PROVIDER"
Ok "Configuration valide."

# --- 5. Modèles locaux ---------------------------------------------------------
Step "5/8 Modèles locaux"
if ($NoModels) {
    Info "Ignoré (-NoModels)."
} else {
    if (-Not $Server) {
        & $VenvPy -c "import os, sys, openwakeword, openwakeword.utils as u; getattr(u, 'download_models', lambda: None)(); d = os.path.join(os.path.dirname(openwakeword.__file__), 'resources', 'models'); sys.exit(0 if all(os.path.isfile(os.path.join(d, f)) for f in ('melspectrogram.onnx', 'embedding_model.onnx', 'silero_vad.onnx')) else 1)"
        if ($LASTEXITCODE -eq 0) { Ok "Modèles openWakeWord (analyse audio + VAD Silero)." }
        else { Warn "Téléchargement des modèles openWakeWord impossible (relancez plus tard)." }
    }
    if ((Get-Setting "STT_PROVIDER") -eq "whisper" -or (Get-Setting "STT_FALLBACK_PROVIDER") -eq "whisper") {
        $whisper = Get-Setting "WHISPER_MODEL"
        & $VenvPy -c "from core.config import get_settings as g; s=g(); from faster_whisper import WhisperModel; WhisperModel(s.WHISPER_MODEL, device=s.WHISPER_DEVICE, compute_type=s.WHISPER_COMPUTE_TYPE)"
        if ($LASTEXITCODE -eq 0) { Ok "Modèle Whisper « $whisper »." }
        else { Warn "Téléchargement du modèle Whisper impossible (il le sera au premier lancement)." }
    }
}
if ((Get-Setting "TTS_PROVIDER") -eq "piper") {
    & $VenvPy -c "import sys; from pathlib import Path; from core.config import TTS_MODEL_PATH as p; sys.exit(0 if Path(p).is_file() else 1)"
    if ($LASTEXITCODE -eq 0) { Ok "Voix Piper présente." }
    else { Warn "Voix Piper introuvable (TTS_VOICE / TTS_MODEL_PATH dans .env)." }
}

# --- 6. Ollama -----------------------------------------------------------------
Step "6/8 Ollama (LLM local)"

function Test-Ollama($url) {
    try { Invoke-RestMethod -Uri "$url/api/tags" -TimeoutSec 3 | Out-Null; return $true } catch { return $false }
}

$llm = Get-Setting "LLM_PROVIDER"; $stt = Get-Setting "STT_PROVIDER"; $tts = Get-Setting "TTS_PROVIDER"
$fallback = Get-Setting "STT_FALLBACK_PROVIDER"
if ($WizardRan) {
    # Modèles choisis dans l'assistant (ceux du profil, ou la suggestion si le profil viendra plus tard)
    $models = $OllamaPull
} else {
    $models = @()
    if ($llm -eq "ollama") { $models += Get-Setting "OLLAMA_MODEL" }
    if ($stt -eq "ollama" -or ($stt -in @("direct", "none", "bypass") -and $fallback -eq "ollama")) { $models += Get-Setting "OLLAMA_STT_MODEL" }
    if ($tts -eq "ollama") { $models += Get-Setting "OLLAMA_TTS_MODEL" }
}
if ($OllamaChoice -eq "none") {
    Info "Ignoré."
} elseif (-Not $WizardRan -and $models.Count -eq 0) {
    Info "Aucun fournisseur Ollama configuré (LLM_PROVIDER=$llm) : rien à faire."
} else {
    $ollamaHost = Get-Setting "OLLAMA_HOST"
    if ($OllamaChoice -ne "remote" -and -Not (Have "ollama") -and -Not (Test-Ollama $ollamaHost)) {
        # « install » a déjà été validé dans l'assistant ; « auto » (sans assistant) demande confirmation
        if (-Not $NoSystemDeps -and (Have "winget") -and ($OllamaChoice -eq "install" -or (Confirm-Action "Ollama n'est pas installé. L'installer maintenant (winget) ?"))) {
            winget install -e --id Ollama.Ollama --accept-package-agreements --accept-source-agreements
            Update-Path
        } else {
            Warn "Ollama absent : installez-le depuis https://ollama.com puis relancez install.ps1."
        }
    }
    if ($OllamaChoice -ne "remote" -and (Have "ollama") -and -Not (Test-Ollama $ollamaHost)) {
        Info "Démarrage d'Ollama..."
        Start-Process "ollama" -ArgumentList "serve" -WindowStyle Hidden
        for ($i = 0; $i -lt 15 -and -Not (Test-Ollama $ollamaHost); $i++) { Start-Sleep -Seconds 1 }
    }
    if (-Not (Test-Ollama $ollamaHost)) {
        Warn "Ollama ne répond pas sur $ollamaHost : modèles non téléchargés."
    } else {
        Ok "Ollama joignable sur $ollamaHost."
        if (-Not $NoModels) {
            $env:OLLAMA_HOST = $ollamaHost
            foreach ($model in ($models | Select-Object -Unique)) {
                Info "Téléchargement du modèle $model (peut être long)..."
                if (Have "ollama") { ollama pull $model }
                else { & $VenvPy -c "import sys, ollama; ollama.Client(host=sys.argv[1]).pull(sys.argv[2])" $ollamaHost $model }
                if ($LASTEXITCODE -eq 0) { Ok "Modèle $model prêt." } else { Warn "Échec du téléchargement de $model." }
            }
        }
    }
}

# --- 7. Comptes utilisateurs (PocketBase) ------------------------------------------
Step "7/8 Comptes utilisateurs (PocketBase)"
if ($AccountsChoice -eq "true") {
    Set-EnvValue "AUTH_PROVIDER" "pocketbase"
} elseif ($AccountsChoice -eq "false" -and (Get-Setting "AUTH_PROVIDER") -eq "pocketbase") {
    Set-EnvValue "AUTH_PROVIDER" "none"
}
if ((Get-Setting "AUTH_PROVIDER") -ne "pocketbase") {
    Ok "Désactivés : le jeton de la passerelle donne l'accès (AUTH_PROVIDER=none)."
} else {
    # Les comptes servent à la PWA : passerelle active, jeton maître (accès administrateur) obligatoire hors loopback
    if (-Not $Server -and (Get-Setting "GATEWAY_ENABLED") -ne "True") {
        Set-EnvValue "GATEWAY_ENABLED" "true"
        Ok "Passerelle activée (GATEWAY_ENABLED=true)."
    }
    if (-Not (Get-Setting "GATEWAY_AUTH_TOKEN")) {
        $token = & $VenvPy -c "import secrets; print(secrets.token_hex(32))"
        Set-EnvValue "GATEWAY_AUTH_TOKEN" "$token".Trim()
        Ok "Jeton administrateur généré (GATEWAY_AUTH_TOKEN dans .env)."
    }
    & $VenvPy -m core.pocketbase install
    if ($LASTEXITCODE -ne 0) {
        Warn "PocketBase non installé : relancez install.ps1 ou .venv\Scripts\python -m core.pocketbase install."
    } else {
        $pbData = Join-Path $PSScriptRoot "pocketbase\pb_data"
        if (-Not (Test-Path $pbData) -and -Not $Yes -and -Not [Console]::IsInputRedirected -and (Confirm-Action "Créer maintenant le compte administrateur de PocketBase ?")) {
            & $VenvPy -m core.pocketbase admin
            if ($LASTEXITCODE -ne 0) { Warn "Compte non créé : .venv\Scripts\python -m core.pocketbase admin" }
        } elseif (-Not (Test-Path $pbData)) {
            Info "Compte administrateur à créer : .venv\Scripts\python -m core.pocketbase admin"
        }
        Ok "SmartHome lance PocketBase lui-même. Comptes du foyer : $(Get-Setting 'POCKETBASE_URL')/_/ (collection users, champ role)."
    }
}

# --- 8. Démarrage automatique --------------------------------------------------
Step "8/8 Lancement"
if (-Not $Service) {
    Info "Pas de démarrage automatique (option -Service pour l'ajouter)."
} else {
    $taskName = "SmartHome"
    $startArgs = "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$PSScriptRoot\start.ps1`""
    if ($Server) { $startArgs += " -Server" }
    $action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument $startArgs -WorkingDirectory $PSScriptRoot
    # À l'ouverture de session : l'assistant a besoin du micro et du son de l'utilisateur.
    $trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
    $settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
        -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)
    Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Settings $settings -Force | Out-Null
    Ok "Tâche planifiée « $taskName » créée (démarre à l'ouverture de session)."
}

Write-Host "`n✅ SmartHome est installé." -ForegroundColor Green
if ($Server) {
    Write-Host "  • Lancer la passerelle : .\start.ps1 -Server"
    Write-Host "  • Arrêter             : .\stop.ps1"
    Write-Host "  • Jeton des clients    : GATEWAY_AUTH_TOKEN dans .env"
    Write-Host "  • Pare-feu : autorisez le port $(Get-Setting 'GATEWAY_PORT') (ou utilisez Tailscale, voir docs\MISE_EN_SERVICE.md)"
} else {
    Write-Host "  • Lancer l'assistant : .\start.ps1"
    Write-Host "  • Arrêter            : .\stop.ps1"
    Write-Host "  • Choisir le micro   : AUDIO_INPUT_DEVICE_INDEX dans .env"
}
Warn "Les actions système (volume, verrouillage, applications...) sont des scripts bash prévus pour Linux : sous Windows, elles échoueront tant qu'elles ne sont pas portées."
