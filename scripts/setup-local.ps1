# Setup script for local LLM infrastructure (Windows)

Write-Host "Setting up local LLM infrastructure..." -ForegroundColor Green

# Check if Docker is installed
if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    Write-Host "Docker not found. Please install Docker Desktop:" -ForegroundColor Yellow
    Write-Host "https://www.docker.com/products/docker-desktop" -ForegroundColor Cyan
    exit 1
}

Write-Host "Docker found. Starting vLLM container..." -ForegroundColor Green

# Run vLLM with a small model
# Note: For GPU support, you need NVIDIA Docker runtime
# For CPU-only, remove --gpus all flag
docker run -d --name vllm-server -p 8000:8000 `
    vllm/vllm-openai:latest `
    --model mistralai/Mistral-7B-Instruct-v0.2 `
    --host 0.0.0.0 `
    --port 8000

Write-Host "vLLM server starting on http://localhost:8000" -ForegroundColor Green
Write-Host "Check logs with: docker logs -f vllm-server" -ForegroundColor Cyan

