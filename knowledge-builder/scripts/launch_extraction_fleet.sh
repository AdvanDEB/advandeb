#!/usr/bin/env bash
# Launch a 4-GPU extraction fleet for reproduction fact extraction.
#
# Starts one user-level Ollama server pinned to each of the 4 GPUs (ports
# 11435-11438, OLLAMA_NUM_PARALLEL=8) and one sharded extraction worker per GPU.
# The systemd Ollama on :11434 is left alone for the app/chat. The embedding job
# (CPU) is left running.
#
# Usage:  bash knowledge-builder/scripts/launch_extraction_fleet.sh [CONCURRENCY]
set -u
REPO=/home/adeb/dev/advandeb
CONC="${1:-8}"
NSHARDS=4

cd "$REPO"
set -a; . app/backend/.env; set +a

# Model blobs live in the systemd ollama's store (user=ollama), readable by us.
OLLAMA_MODELS_DIR=/usr/share/ollama/.ollama/models

echo ">> stopping any existing extraction workers + my ollama instances"
pkill -f "scripts/run_reproduction_pipeline.py" 2>/dev/null || true
pkill -u "$(id -un)" -x ollama 2>/dev/null || true   # adeb-owned ollama only; leaves systemd (user=ollama)
sleep 3

echo ">> starting 4 GPU-pinned Ollama servers (models: $OLLAMA_MODELS_DIR)"
for i in 0 1 2 3; do
  port=$((21434 + i))
  CUDA_VISIBLE_DEVICES=$i OLLAMA_HOST=127.0.0.1:$port OLLAMA_MODELS="$OLLAMA_MODELS_DIR" \
    OLLAMA_NUM_PARALLEL=$CONC OLLAMA_MAX_LOADED_MODELS=1 OLLAMA_KEEP_ALIVE=-1 \
    nohup ollama serve > /tmp/ollama_gpu$i.log 2>&1 &
  echo "   gpu$i -> http://127.0.0.1:$port (pid $!)"
done
sleep 3

echo ">> waiting for Ollama servers to bind + warming gemma2:2b on each GPU"
for i in 0 1 2 3; do
  port=$((21434 + i))
  for _ in $(seq 1 30); do
    curl -s -m2 "http://127.0.0.1:$port/api/tags" >/dev/null 2>&1 && break
    sleep 1
  done
  # Warm load (blocks until model is resident on this GPU)
  curl -s -m120 "http://127.0.0.1:$port/api/chat" \
    -d '{"model":"gemma2:2b","messages":[{"role":"user","content":"ok"}],"stream":false,"keep_alive":-1}' \
    >/dev/null 2>&1 && echo "   gpu$i warmed" || echo "   gpu$i WARN: warm failed (worker will retry)"
done

echo ">> starting 4 sharded extraction workers (concurrency=$CONC each)"
for i in 0 1 2 3; do
  port=$((21434 + i))
  OLLAMA_MODEL=gemma2:2b nohup conda run -n advandeb python \
    knowledge-builder/scripts/run_reproduction_pipeline.py \
    --ollama-url "http://127.0.0.1:$port" --shard $i --num-shards $NSHARDS \
    --concurrency "$CONC" \
    > /tmp/repro_facts_shard$i.log 2>&1 &
  echo "   shard $i/$NSHARDS -> gpu$i (pid $!)"
done

echo ">> fleet launched. logs: /tmp/ollama_gpu{0..3}.log  /tmp/repro_facts_shard{0..3}.log"
