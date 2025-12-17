#!/bin/bash
# Script to start ngrok tunnels for AdvanDEB Modeling Assistant

echo "🚇 Starting ngrok tunnels..."
echo ""

# Check if ngrok is installed
if ! command -v ngrok &> /dev/null; then
    echo "❌ ngrok is not installed"
    echo "Install from: https://ngrok.com/download"
    exit 1
fi

# Check if ngrok auth token is configured
if ! ngrok config check &> /dev/null; then
    echo "⚠️  ngrok auth token not configured"
    echo ""
    echo "To set up ngrok:"
    echo "1. Sign up at https://dashboard.ngrok.com/signup"
    echo "2. Get your auth token from https://dashboard.ngrok.com/get-started/your-authtoken"
    echo "3. Run: ngrok config add-authtoken YOUR_TOKEN"
    echo ""
    exit 1
fi

# Start ngrok with config file
echo "Starting tunnels for:"
echo "  - Backend (port 8000)"
echo "  - Frontend (port 5173)"
echo ""

cd "$(dirname "$0")/.."

# Start ngrok with both tunnels
ngrok start --all --config ngrok.yml

# Note: This will keep running. Press Ctrl+C to stop
