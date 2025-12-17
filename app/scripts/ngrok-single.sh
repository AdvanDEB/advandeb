#!/bin/bash
# Start individual ngrok tunnel

if [ "$#" -ne 2 ]; then
    echo "Usage: $0 <service> <port>"
    echo "Example: $0 frontend 5173"
    exit 1
fi

SERVICE=$1
PORT=$2

echo "🚇 Starting ngrok tunnel for $SERVICE on port $PORT..."
ngrok http $PORT --log=stdout

# The tunnel URL will be displayed in the output
# Look for lines like: url=https://xxxx-xxx-xxx.ngrok-free.app
