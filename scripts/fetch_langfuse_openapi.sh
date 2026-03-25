#!/usr/bin/env bash
set -euo pipefail
mkdir -p docs/langfuse
curl -fsSL https://cloud.langfuse.com/generated/api/openapi.yml -o docs/langfuse/openapi.yml
echo "Saved docs/langfuse/openapi.yml"
