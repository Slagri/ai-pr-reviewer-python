#!/usr/bin/env bash
# End-to-end test script for AI PR Reviewer
#
# Prerequisites:
#   1. .env file configured (copy from .env.example)
#   2. GitHub App created, installed on a test repo, private key downloaded
#   3. ngrok installed (brew install ngrok) and authenticated
#   4. Python venv activated with dependencies installed
#
# Usage:
#   ./scripts/e2e_test.sh

set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

info() { echo -e "${GREEN}[INFO]${NC} $1"; }
warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
fail() { echo -e "${RED}[FAIL]${NC} $1"; exit 1; }

# Check prerequisites
command -v ngrok >/dev/null 2>&1 || fail "ngrok not installed. Run: brew install ngrok"
command -v python >/dev/null 2>&1 || fail "python not found. Activate your venv first."
[ -f .env ] || fail ".env file not found. Copy from .env.example and fill in values."

info "Step 1: Validating .env configuration..."
python -c "
from reviewer.config import Settings
s = Settings()
print(f'  Endpoint: {s.azure_openai_endpoint}')
print(f'  Model: {s.review_model}')
print(f'  GitHub: {\"configured\" if s.github_enabled else \"NOT configured\"}')
assert s.github_enabled, 'GitHub provider not configured in .env'
print('  Config OK')
" || fail "Configuration validation failed"

info "Step 2: Testing Azure OpenAI connectivity..."
python -c "
import asyncio
from openai import AsyncAzureOpenAI
from reviewer.config import Settings

async def test():
    s = Settings()
    kwargs = {'azure_endpoint': s.azure_openai_endpoint, 'api_version': s.azure_openai_api_version}
    if s.azure_openai_api_key:
        kwargs['api_key'] = s.azure_openai_api_key.get_secret_value()
    client = AsyncAzureOpenAI(**kwargs)
    resp = await client.chat.completions.create(
        model=s.review_model,
        messages=[{'role': 'user', 'content': 'Say OK'}],
        max_tokens=5,
    )
    print(f'  Model response: {resp.choices[0].message.content}')
    print(f'  Tokens used: {resp.usage.total_tokens}')
    print('  Azure OpenAI OK')

asyncio.run(test())
" || fail "Azure OpenAI connectivity test failed"

info "Step 3: Starting server in background..."
LOG_LEVEL=debug uvicorn reviewer.main:create_app --factory --host 0.0.0.0 --port 8000 &
SERVER_PID=$!
sleep 3

# Verify server is running
curl -sf http://localhost:8000/healthz > /dev/null || fail "Server failed to start"
info "  Server running (PID: $SERVER_PID)"

info "Step 4: Starting ngrok tunnel..."
ngrok http 8000 --log=stdout > /dev/null &
NGROK_PID=$!
sleep 3

# Get ngrok public URL
NGROK_URL=$(curl -sf http://localhost:4040/api/tunnels | python -c "import sys,json; print(json.load(sys.stdin)['tunnels'][0]['public_url'])")
info "  Tunnel URL: $NGROK_URL"

echo ""
echo "============================================"
echo "  E2E Test Environment Ready"
echo "============================================"
echo ""
echo "  Server:  http://localhost:8000"
echo "  Tunnel:  $NGROK_URL"
echo "  Webhook: $NGROK_URL/webhook/github"
echo ""
echo "  Next steps:"
echo "  1. Update your GitHub App webhook URL to:"
echo "     $NGROK_URL/webhook/github"
echo ""
echo "  2. Open a PR on your test repo (or push to an existing one)"
echo ""
echo "  3. Watch the logs in this terminal"
echo ""
echo "  Press Ctrl+C to stop"
echo ""

# Wait for Ctrl+C
cleanup() {
    info "Shutting down..."
    kill $SERVER_PID 2>/dev/null || true
    kill $NGROK_PID 2>/dev/null || true
    info "Done"
}
trap cleanup EXIT

wait $SERVER_PID
