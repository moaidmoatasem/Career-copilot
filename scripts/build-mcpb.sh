#!/usr/bin/env bash
# Build the Claude Desktop bundle (career-copilot.mcpb).
#
# Needs Node, only to run the packer:  npx @anthropic-ai/mcpb
# The bundle itself carries no Node — it declares server.type "uv", so Claude
# Desktop uses uv and this project's pyproject.toml to resolve Python and the
# dependencies at install time. Nothing is vendored into the bundle.
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$root"

if ! command -v npx >/dev/null 2>&1; then
  echo "npx not found. Install Node, or build the bundle on a machine that has it." >&2
  exit 1
fi

echo "Validating manifest.json..."
npx --yes @anthropic-ai/mcpb validate manifest.json

echo "Packing..."
npx --yes @anthropic-ai/mcpb pack . career-copilot.mcpb

echo
echo "Built career-copilot.mcpb"
echo "Install it: Claude Desktop → Settings → Extensions → Advanced settings → Install Extension…"
