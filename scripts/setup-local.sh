#!/bin/bash
# Setup script for local LLM infrastructure

echo "Setting up local LLM infrastructure..."

# Check if Docker is installed
if ! command -v docker &> /dev/null; then
    echo "Docker not found. Please install Docker Desktop:"
    echo "https://www.docker.com/products/docker-desktop"
    exit 1
fi

echo "Docker found. Starting vLLM container..."

# Run vLLM with a small model
docker run --gpus all -p 8000:8000 \
    --name vllm-server \
    vllm/vllm-openai:latest \
    --model mistralai/Mistral-7B-Instruct-v0.2 \
    --host 0.0.0.0 \
    --port 8000

