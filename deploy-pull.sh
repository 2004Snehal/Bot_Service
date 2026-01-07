#!/bin/bash
# Auto-deploy script to run on EC2 instance
# This script pulls latest code and restarts services

set -e

# Configuration
REPO_DIR="/home/ubuntu/bot_service"
DOCKER_IMAGE="ghcr.io/hicappyai/voice:bot"
CONTAINER_NAME="voice-bot"

echo "=== Starting Auto-Deploy $(date) ==="

# Navigate to repository
cd "$REPO_DIR" || { echo "Error: Repository directory not found"; exit 1; }

# Pull latest code
echo "Pulling latest code..."
git fetch origin main
git reset --hard origin/main

# Pull latest Docker image
echo "Pulling latest Docker image..."
docker pull "$DOCKER_IMAGE" || echo "Warning: Failed to pull Docker image"

# Restart Docker container
echo "Restarting Docker container..."
docker stop "$CONTAINER_NAME" 2>/dev/null || true
docker rm "$CONTAINER_NAME" 2>/dev/null || true

docker run -d \
  --name "$CONTAINER_NAME" \
  --restart unless-stopped \
  -v "$(pwd)/.env:/app/.env:ro" \
  -p 8080:8080 \
  "$DOCKER_IMAGE"

echo "=== Deploy Complete $(date) ==="
