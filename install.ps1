# Script d'installation automatique SmartHome
Write-Host "🚀 Initialisation de l'environnement SmartHome..." -ForegroundColor Cyan

# 1. Création de l'environnement virtuel si inexistant
if (-Not (Test-Path ".venv")) {
    Write-Host "📦 Création du venv..." -ForegroundColor Yellow
    python -m venv .venv
} else {
    Write-Host "📦 Environnement .venv déjà présent." -ForegroundColor Green
}

# 2. Mise à jour de pip et installation des dépendances
Write-Host "📥 Installation des modules Python..." -ForegroundColor Yellow
& .\.venv\Scripts\python.exe -m pip install --upgrade pip
& .\.venv\Scripts\pip.exe install numpy pyaudio sounddevice openwakeword faster-whisper ollama piper-tts python-dotenv

# 3. Téléchargement des modèles openWakeWord
Write-Host "🧠 Téléchargement des modèles de base openWakeWord..." -ForegroundColor Yellow
& .\.venv\Scripts\python.exe -c "import openwakeword.utils; openwakeword.utils.download_models()"

# 4. Téléchargement de la voix française Piper (si non présente)
if (-Not (Test-Path "voices/fr_FR-siwis-medium.onnx")) {
    Write-Host "🎙️ Téléchargement du modèle de voix française (Siwis)..." -ForegroundColor Yellow
    New-Item -ItemType Directory -Force -Path "voices" | Out-Null
    Invoke-WebRequest -Uri "https://huggingface.co/rhasspy/piper-voices/resolve/main/fr/fr_FR/siwis/medium/fr_FR-siwis-medium.onnx" -OutFile "voices/fr_FR-siwis-medium.onnx"
    Invoke-WebRequest -Uri "https://huggingface.co/rhasspy/piper-voices/resolve/main/fr/fr_FR/siwis/medium/fr_FR-siwis-medium.onnx.json" -OutFile "voices/fr_FR-siwis-medium.onnx.json"
}

Write-Host "`n✅ Tout est prêt ! Tu peux lancer start.ps1 ou start.bat." -ForegroundColor Green