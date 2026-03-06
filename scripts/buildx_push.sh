#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 1 || $# -gt 2 ]]; then
  echo "Usage: $0 <ECR_URI> [TAG]"
  echo "Example: $0 162187491349.dkr.ecr.us-east-1.amazonaws.com/financial-agent-repo v6"
  exit 1
fi

ECR_URI="$1"
TAG="${2:-latest}"
REGION="${AWS_REGION:-us-east-1}"
PLATFORM="${DOCKER_PLATFORM:-linux/arm64}"
BUILDER_NAME="${BUILDER_NAME:-financial-agent-builder}"

echo "Ensuring buildx builder '${BUILDER_NAME}' exists..."
if ! docker buildx inspect "${BUILDER_NAME}" >/dev/null 2>&1; then
  docker buildx create --name "${BUILDER_NAME}" --driver docker-container --use
else
  docker buildx use "${BUILDER_NAME}"
fi
docker buildx inspect --bootstrap >/dev/null

echo "Logging in to ECR ${REGION}..."
aws ecr get-login-password --region "${REGION}" | \
  docker login --username AWS --password-stdin "${ECR_URI%%/*}"

echo "Building and pushing ${ECR_URI}:${TAG} (${PLATFORM})..."
docker buildx build \
  --platform "${PLATFORM}" \
  -f docker/Dockerfile \
  -t "${ECR_URI}:${TAG}" \
  --push \
  .

echo "Done: ${ECR_URI}:${TAG}"
