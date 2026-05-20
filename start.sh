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

# Check tmux
if ! command -v tmux &>/dev/null; then
  echo "tmux not found. Starting in background instead."
  cd "$ROOT/backend" && uvicorn main:app --host 0.0.0.0 --port 8000 &
  cd "$ROOT/frontend" && npm run dev &
  echo "Backend: http://localhost:8000"
  echo "Frontend: http://localhost:3000"
  wait
  exit 0
fi

SESSION="agentic-exchange"
tmux kill-session -t "$SESSION" 2>/dev/null || true
tmux new-session -d -s "$SESSION" -x 220 -y 50

# Backend pane
tmux send-keys -t "$SESSION:0" "cd '$ROOT/backend' && echo '>>> Starting FastAPI backend...' && uvicorn main:app --host 0.0.0.0 --port 8000 --reload" Enter

# Frontend pane (split)
tmux split-window -h -t "$SESSION:0"
tmux send-keys -t "$SESSION:0.1" "cd '$ROOT/frontend' && echo '>>> Starting Next.js frontend...' && npm run dev" Enter

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
