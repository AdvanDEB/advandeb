# Batch PDF Ingestion Setup Guide

This guide covers the new batch ingestion system for processing large numbers of PDFs from the `papers/` directory.

## Overview

The ingestion system consists of:
- **Backend API** (FastAPI) - ingestion endpoints
- **Celery Workers** - background processing of PDFs
- **Redis** - task queue broker
- **MongoDB** - storage for batches, jobs, documents, and facts
- **Frontend UI** - wizard-based ingestion workflow

## Prerequisites

Ensure you have:
- MongoDB running (local or container)
- Redis running (local or container)
- Ollama running with at least one model (e.g. `llama2`)
- Conda environment set up (see main README)
- Node.js and npm installed

## Backend Setup

### 1. Install Dependencies

From `backend/` directory with your conda env activated:

```bash
# Install Python dependencies (includes celery and redis)
pip install -r requirements.txt
```

### 2. Configure Environment

Create or update `backend/.env`:

```bash
# MongoDB Configuration
MONGODB_URL=mongodb://localhost:27017
DATABASE_NAME=advandeb_knowledge_builder_kb

# Ollama Configuration
OLLAMA_BASE_URL=http://localhost:11434

# API Configuration
API_HOST=0.0.0.0
API_PORT=8000

# File Upload Configuration
MAX_FILE_SIZE=50000000
UPLOAD_DIR=uploads

# Ingestion / Background Processing Configuration
REDIS_URL=redis://localhost:6379/0
PAPERS_ROOT=../papers
```

**Important**: Set `PAPERS_ROOT` to the absolute or relative path to your `papers/` directory.

### 3. Start Required Services

In separate terminals:

**Terminal 1: Redis**
```bash
redis-server
```

**Terminal 2: MongoDB** (if not already running as a service)
```bash
mongod --dbpath /path/to/your/data
```

**Terminal 3: Ollama** (if not already running)
```bash
ollama serve
# Pull a model if you haven't already
ollama pull llama2
```

### 4. Start Backend API

**Terminal 4: FastAPI Backend**
```bash
cd backend
conda activate advandeb-knowledge-builder-backend
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

API will be available at `http://localhost:8000`
- Swagger docs: `http://localhost:8000/docs`

### 5. Start Celery Worker

**Terminal 5: Celery Worker**
```bash
cd backend
conda activate advandeb-knowledge-builder-backend
celery -A celery_app.celery_app worker --loglevel=INFO
```

You should see output like:
```
[tasks]
  . celery_app.health_check
  . tasks.ingestion_tasks.process_pdf_job
  . tasks.ingestion_tasks.run_batch
```

**Optional**: For better monitoring, you can also run Flower (Celery monitoring tool):
```bash
pip install flower
celery -A celery_app.celery_app flower
```
Then visit `http://localhost:5555` to see real-time task status.

## Frontend Setup

### 1. Install Dependencies

From `frontend/` directory:

```bash
npm install
```

### 2. Start Development Server

```bash
npm run dev
```

Frontend will be available at `http://localhost:3000` (or the port shown in terminal).

## Using the Ingestion System

### Via the UI (Recommended)

1. Navigate to `http://localhost:3000` and click **"Batch Ingestion"** in the sidebar.

2. **Wizard Tab - Step 1: Select Folders**
   - View all folders under your `PAPERS_ROOT`
   - See PDF counts for each folder
   - Select one or more folders (or the root `.` to ingest everything)
   - Click **"Next: Scan N folder(s)"**

3. **Wizard Tab - Step 2: Review Scan**
   - See total PDFs found and which folders will be processed
   - Click **"Confirm & Run Ingestion"** to start

4. **Wizard Tab - Step 3: Running**
   - Confirmation that jobs have been queued
   - Click **"View Batch Progress"** to monitor

5. **Batches Tab**
   - List all ingestion batches
   - See status: `pending`, `running`, `completed`, `failed`, `mixed`
   - Click **"View Jobs"** to see individual file processing

6. **Jobs Tab**
   - View all ingestion jobs (individual PDFs)
   - Filter by batch ID or status
   - See progress, stage, and error messages
   - Statuses:
     - `pending` - not yet queued
     - `queued` - waiting for worker
     - `running` - currently processing
     - `completed` - successfully processed
     - `failed` - error occurred

### Via the API (Advanced)

You can also interact directly with the ingestion API:

**1. List available source folders:**
```bash
curl http://localhost:8000/api/ingestion/sources
```

**2. Scan selected folders and create batch:**
```bash
curl -X POST http://localhost:8000/api/ingestion/scan \
  -H "Content-Type: application/json" \
  -d '["2393", "2475"]'
```

Response includes `batch_id` and `num_files`.

**3. Run the batch:**
```bash
curl -X POST http://localhost:8000/api/ingestion/run \
  -H "Content-Type: application/json" \
  -d '{"batch_id": "<batch_id_from_step_2>"}'
```

**4. Monitor progress:**
```bash
# List batches
curl http://localhost:8000/api/ingestion/batches

# List jobs for a batch
curl "http://localhost:8000/api/ingestion/jobs?batch_id=<batch_id>"

# Get specific job details
curl http://localhost:8000/api/ingestion/jobs/<job_id>
```

## Processing Pipeline

Each ingestion job follows this pipeline:

1. **Text Extraction** (`stage: text_extraction`)
   - PDF is read using PyPDF2
   - Text extracted from all pages
   - Document created in MongoDB

2. **Fact Extraction** (`stage: fact_extraction`)
   - Text sent to Ollama LLM via AgentService
   - Facts extracted and stored in MongoDB
   - Linked to parent Document

3. **Completed** (`stage: completed`, `status: completed`)
   - Document and facts are ready
   - Accessible via `/api/data/documents` and `/api/knowledge/facts`

If any stage fails, the job is marked `status: failed` with an `error_message`.

## Monitoring and Troubleshooting

### Check Celery Worker Logs

In the Celery worker terminal, you'll see:
- Tasks being picked up
- Progress through stages
- Any errors

### Check Job Status in MongoDB

```bash
mongosh
use advandeb_knowledge_builder_kb
db.ingestion_jobs.find({ status: "failed" })
db.ingestion_jobs.find({ batch_id: ObjectId("...") })
```

### Common Issues

**1. "File not found" errors**
- Verify `PAPERS_ROOT` in `.env` is correct (absolute or relative to `backend/`)
- Check file permissions

**2. Celery tasks not running**
- Ensure Redis is running: `redis-cli ping` should return `PONG`
- Check Celery worker is connected to same Redis URL
- Verify worker logs show task registration

**3. Fact extraction fails**
- Ensure Ollama is running: `curl http://localhost:11434/api/tags`
- Check you have the required model: `ollama list`
- Look for timeout errors (PDFs with huge text may need longer timeouts)

**4. Out of memory**
- For very large batches (10,000+ PDFs), consider:
  - Running multiple smaller batches
  - Increasing worker concurrency carefully
  - Adding swap space or more RAM

### Performance Tuning

**Celery Concurrency**

By default, Celery uses the number of CPU cores. To process more PDFs in parallel:

```bash
celery -A celery_app.celery_app worker --loglevel=INFO --concurrency=8
```

Be mindful of:
- CPU and memory usage
- Ollama/LLM capacity (if using GPU, limit concurrency to avoid VRAM exhaustion)

**Rate Limiting (Optional)**

If you want to throttle fact extraction to avoid overloading Ollama:

Edit `backend/celery_app.py` and add:

```python
celery_app.conf.task_annotations = {
    'tasks.ingestion_tasks.process_pdf_job': {'rate_limit': '10/m'}  # 10 per minute
}
```

## Next Steps After Ingestion

Once PDFs are ingested:

1. **View Documents**: Navigate to "Data Processing" → Documents tab
2. **Browse Facts**: Navigate to "Knowledge Base" → Facts tab
3. **Create Stylized Facts**: Use agents to summarize and structure facts
4. **Build Knowledge Graphs**: Create graphs from facts and explore relationships
5. **Use for Modeling**: Query the knowledge base via the Modeling Agent

## Architecture Notes

- **Batches** are logical groupings of ingestion jobs
- **Jobs** are individual PDF processing tasks (one job = one PDF)
- **Documents** are the extracted text + metadata from each PDF
- **Facts** are LLM-extracted knowledge statements linked to documents

All of these are stored in MongoDB collections:
- `ingestion_batches`
- `ingestion_jobs`
- `documents`
- `facts`
- `stylized_facts`
- `knowledge_graphs`

## Future Enhancements

Planned improvements:
- Graph update stage (automatic node/edge creation from facts)
- Pause/resume batch processing
- Retry individual failed jobs from UI
- Duplicate detection (skip already-processed PDFs)
- Chunking for very large PDFs
- Progress webhooks for real-time UI updates
