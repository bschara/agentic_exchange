#!/bin/bash
# Agentic Exchange — One-command start script
set -e

ROOT="$(cd "$(dirname "$0")" && pwd)"

echo ""
echo "╔══════════════════════════════════════════╗"
echo "║         AGENTIC EXCHANGE STARTUP         ║"
echo "║   Autonomous AI Trading on Somnia        ║"
echo "╚══════════════════════════════════════════╝"
echo ""

# ── Local Hardhat prerequisite check ─────────────────────────────────────────
# Only check if .env points to localhost — skip for testnet deployments.
if grep -q 'SOMNIA_RPC_URL=http://127.0.0.1' "$ROOT/backend/.env" 2>/dev/null; then
  if ! curl -sf --max-time 2 http://127.0.0.1:8545 -X POST \
      -H 'Content-Type: application/json' \
      -d '{"jsonrpc":"2.0","method":"eth_blockNumber","params":[],"id":1}' >/dev/null 2>&1; then
    echo "ERROR: Local Hardhat node is not running."
    echo ""
    echo "  Start it first (in a separate terminal):"
    echo "    cd contracts && npx hardhat node"
    echo ""
    echo "  Then deploy contracts (once per fresh node):"
    echo "    cd contracts && npx hardhat run scripts/deploy-local.js --network localhost"
    echo ""
    exit 1
  fi
  echo "✓ Hardhat node is running"
fi

# ── No tmux fallback ──────────────────────────────────────────────────────────
if ! command -v tmux &>/dev/null; then
  echo "tmux not found. Starting in background instead."
  echo "NOTE: platform-daemon.js must be started manually:"
  echo "  cd '$ROOT/contracts' && node scripts/platform-daemon.js"
  echo ""
  cd "$ROOT/backend" && uvicorn main:app --host 0.0.0.0 --port 8000 &
  cd "$ROOT/frontend" && npm run dev &
  echo "Backend: http://localhost:8000"
  echo "Frontend: http://localhost:3000"
  wait
  exit 0
fi

SESSION="agentic-exchange"
tmux kill-session -t "$SESSION" 2>/dev/null || true
tmux new-session -d -s "$SESSION" -x 240 -y 60

# Pane 0: Backend
tmux send-keys -t "$SESSION:0" \
  "cd '$ROOT/backend' && echo '>>> Starting FastAPI backend...' && uvicorn main:app --host 0.0.0.0 --port 8000 --reload" Enter

# Pane 1: Frontend (horizontal split)
tmux split-window -h -t "$SESSION:0"
tmux send-keys -t "$SESSION:0.1" \
  "cd '$ROOT/frontend' && echo '>>> Starting Next.js frontend...' && npm run dev" Enter

# Pane 2: Platform daemon (vertical split below backend) — only needed for local Hardhat
if grep -q 'SOMNIA_RPC_URL=http://127.0.0.1' "$ROOT/backend/.env" 2>/dev/null; then
  tmux split-window -v -t "$SESSION:0.0"
  tmux send-keys -t "$SESSION:0.2" \
    "cd '$ROOT/contracts' && echo '>>> Starting platform daemon...' && node scripts/platform-daemon.js" Enter
fi

echo "✓ Started in tmux session '$SESSION'"
echo ""
echo "  Frontend:  http://localhost:3000"
echo "  Backend:   http://localhost:8000"
echo "  Health:    http://localhost:8000/health"
echo ""
echo "  tmux attach -t $SESSION   (to view live logs)"
echo "  tmux kill-session -t $SESSION   (to stop)"
echo ""
tmux attach -t "$SESSION"
