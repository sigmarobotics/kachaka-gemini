#!/bin/bash
# Build multi-architecture Docker image for AMD64 and ARM64
# Requires: docker buildx

set -e

IMAGE_NAME="${1:-kachaka-gemini-live}"
TAG="${2:-latest}"

echo "Building multi-arch image: ${IMAGE_NAME}:${TAG}"
echo "Platforms: linux/amd64, linux/arm64"
echo ""

# Create buildx builder if not exists
if ! docker buildx inspect multiarch-builder >/dev/null 2>&1; then
    echo "Creating buildx builder..."
    docker buildx create --name multiarch-builder --use
    docker buildx inspect --bootstrap
fi

# Use the builder
docker buildx use multiarch-builder

# Build and push (or load for local use)
# For push to registry:
#   docker buildx build --platform linux/amd64,linux/arm64 -t ${IMAGE_NAME}:${TAG} --push .

# For local build (one platform at a time):
echo "Building for current platform..."
docker buildx build --platform linux/amd64,linux/arm64 -t ${IMAGE_NAME}:${TAG} --load . 2>/dev/null || {
    echo ""
    echo "Note: --load only works for single platform."
    echo "Building for current platform only..."
    docker buildx build -t ${IMAGE_NAME}:${TAG} --load .
}

echo ""
echo "Done! Run with:"
echo "  docker run -p 9000:9000 -e ROBOT_IP=192.168.50.133:26400 ${IMAGE_NAME}:${TAG}"
echo ""
echo "Or use docker-compose:"
echo "  docker-compose up -d"
