#!/bin/bash
# Quick start script for AdvanDEB Modeling Assistant

echo "🚀 Starting AdvanDEB Modeling Assistant..."
echo ""

# Activate conda environment
echo "📦 Activating conda environment..."
source ~/miniforge3/etc/profile.d/conda.sh
conda activate advandeb-modeling-assistant

# Check if MongoDB is running
echo "🔍 Checking MongoDB..."
if ! pgrep -x "mongod" > /dev/null; then
    echo "⚠️  MongoDB is not running. Please start MongoDB first."
    echo "   Run: sudo systemctl start mongodb"
    echo "   Or:  brew services start mongodb-community"
    exit 1
fi

# Start backend
echo "🔧 Starting backend..."
cd backend
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000 &
BACKEND_PID=$!
echo "   Backend PID: $BACKEND_PID"
cd ..

# Wait for backend to start
echo "⏳ Waiting for backend to start..."
sleep 3

# Start frontend
echo "🎨 Starting frontend..."
cd frontend
npm run dev &
FRONTEND_PID=$!
echo "   Frontend PID: $FRONTEND_PID"
cd ..

echo ""
echo "✅ Services started!"
echo ""
echo "📍 Backend:  http://localhost:8000"
echo "📍 API Docs: http://localhost:8000/docs"
echo "📍 Frontend: http://localhost:5173"
echo ""
echo "Press Ctrl+C to stop all services"
echo ""

# Wait for Ctrl+C
trap "kill $BACKEND_PID $FRONTEND_PID; exit" INT
wait
