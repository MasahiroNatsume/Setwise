# Robust installation script for StepWise Backend on Windows

Write-Host "Starting robust dependency installation..."

# 1. Install Torch first (CPU version default for stability, or auto-detect)
# We use the standard index. If you need CUDA, visit https://pytorch.org/get-started/locally/
Write-Host "Installing PyTorch..."
pip install torch torchvision torchaudio

# 2. Install Spacy and Thinc using binary wheels to avoid MSVC build errors
Write-Host "Installing Spacy/Thinc binaries..."
pip install "spacy>=3.0.0" "thinc>=8.0.0" "blis>=0.7.0" --only-binary :all:

# 3. Install remaining requirements
Write-Host "Installing remaining dependencies..."
pip install -r requirements.txt

Write-Host "Installation complete! Try running 'uvicorn main:app --reload' now."
