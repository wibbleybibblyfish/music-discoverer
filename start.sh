#!/bin/bash
DIR="$(cd "$(dirname "$0")" && pwd)"
VENV="$DIR/.venv/bin/python"
PORT=8138

# Create venv if it doesn't exist
if [ ! -f "$VENV" ]; then
    echo "Setting up virtual environment..."
    python3 -m venv "$DIR/.venv"
    "$DIR/.venv/bin/pip" install -r "$DIR/requirements.txt"
fi

# Kill any existing instance
lsof -ti :$PORT | xargs kill 2>/dev/null
sleep 0.5

# Start server
cd "$DIR"
"$VENV" server.py &
SERVER_PID=$!

# Wait for server to be ready
for i in {1..10}; do
    curl -s "http://localhost:$PORT/api/stats" >/dev/null 2>&1 && break
    sleep 0.5
done

# Open browser
open "http://localhost:$PORT" 2>/dev/null || xdg-open "http://localhost:$PORT" 2>/dev/null

echo "Music Discoverer running at http://localhost:$PORT (PID $SERVER_PID)"
echo "Press Ctrl+C to stop"
wait $SERVER_PID
