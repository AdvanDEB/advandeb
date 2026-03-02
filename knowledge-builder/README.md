# AdvanDEB Knowledge Builder

AdvanDEB knowledge-base builder for agglomeration of knowledge on physiology, morphology, anatomy, and bioenergetics of organisms.

## Overview

AdvanDEB Knowledge Builder is a comprehensive knowledge management system that provides powerful tools for:

- **Knowledge Base Management**: Store and organize facts, stylized facts, and knowledge graphs
- **AI-Powered Extraction**: Leverage locally hosted Ollama LLM models for intelligent fact extraction
- **Data Processing**: Ingest PDFs, browse web content, and process raw text
- **Interactive Visualization**: Create and explore knowledge graphs with network analysis
- **Semantic Search**: Discover relationships and connections in your knowledge base

## Architecture

### Components

- **Backend**: FastAPI (Python) with MongoDB storage
- **Frontend**: Vue.js 3 with Element Plus UI components
- **AI Integration**: Ollama LLM hosting (native, in-house only)
- **Visualization**: D3.js for interactive graph rendering
- **Database**: MongoDB (native install; optional single-container just for MongoDB if you prefer)
- **Environment Management**: Conda (or venv) for Python, npm for JavaScript

## Features

### Core Functionality

- ✅ MongoDB-based knowledge storage
- ✅ Ollama LLM hosting support (localhost/remote)
- ✅ Web browsing capabilities
- ✅ PDF document ingestion
- ✅ Stylized fact extraction
- ✅ Interactive graph visualization
- ✅ Network analysis and community detection

### Data Processing

- **PDF Upload**: Extract facts from scientific documents
- **Web Browsing**: Collect content from web sources
- **Text Processing**: Extract entities and facts from raw text
- **Entity Recognition**: Identify biological terms and concepts

### Knowledge Organization

- **Facts**: Store individual pieces of information with confidence scores
- **Stylized Facts**: Enhanced facts with importance ratings and relationships
- **Knowledge Graphs**: Visual networks showing connections between concepts
- **Search & Discovery**: Find related information and explore connections

### AI Integration

- **Fact Extraction**: Automated extraction using LLM models
- **Content Stylization**: Convert raw facts to structured knowledge
- **Chat Interface**: Interactive AI assistant for knowledge exploration
- **Model Support**: Utilize any Ollama-hosted local models

## Quick Start

### Prerequisites

- **Conda/Miniforge**: For Python environment management (https://github.com/conda-forge/miniforge)
- **Node.js & npm**: For frontend development (https://nodejs.org/)
- **MongoDB**: For data storage (https://docs.mongodb.com/manual/installation/)
- **Ollama**: For LLM services (https://ollama.ai)

### Native Development Setup (Recommended)

1. Clone the repository:

   ```bash
   git clone https://github.com/AdvanDEB/advandeb-knowledge-builder.git
   cd advandeb-knowledge-builder
   ```

2. Run the setup script:

   ```bash
   ./setup.sh
   ```

3. Start the services:

   ```bash
   # Terminal 1: Start backend
   conda activate advandeb-knowledge-builder-backend
   cd backend
   uvicorn main:app --host 0.0.0.0 --port 8000 --reload

   # Terminal 2: Start frontend
   cd frontend
   npm run dev

   # Terminal 3: Start Ollama (if not running)
   ollama serve
   ```

4. Access the application:
- Frontend: http://localhost:3000
- Backend API: http://localhost:8000
- API Documentation: http://localhost:8000/docs

### Manual Installation

#### Backend Setup

1. Navigate to backend directory:
```bash
cd backend
```

2. Create conda environment:
```bash
conda env create -f environment.yml
conda activate advandeb-knowledge-builder-backend
```

3. Configure environment:
```bash
cp .env.example .env
# Edit .env file with your settings
```

4. Start MongoDB (choose one):

   ```bash
   # Preferred: Install MongoDB locally (see official docs)
   # Optional (only MongoDB in container):
   docker run -d -p 27017:27017 --name mongodb mongo:7.0
   ```

5. Start Ollama:
```bash
# Install Ollama from https://ollama.ai
ollama serve
ollama pull llama2  # Pull a model
```

6. Run the backend:
```bash
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

#### Frontend Setup

1. Navigate to frontend directory:
```bash
cd frontend
```

2. Install dependencies:
```bash
npm install
```

3. Start development server:
```bash
npm run dev
```

## Usage Guide

### 1. Data Processing
- **Upload PDFs**: Go to Data Processing → PDF Upload
- **Browse Web Content**: Enter URLs to extract content
- **Process Text**: Paste text for fact extraction

### 2. Knowledge Base
- **View Facts**: Browse extracted facts with confidence scores
- **Stylized Facts**: View enhanced facts with relationships
- **Knowledge Graphs**: Explore visual representations

### 3. AI Agents
- **Chat Interface**: Interact with AI for knowledge exploration
- **Fact Extraction**: Use AI to extract facts from text
- **Fact Stylization**: Convert facts to structured format

### 4. Visualization
- **Graph Viewer**: Visualize knowledge graphs interactively
- **Network Analysis**: Analyze graph properties and statistics
- **Community Detection**: Find clusters in knowledge networks
- **Export Options**: Save graphs in various formats

## Configuration

### Environment Variables

```bash
# MongoDB Settings
MONGODB_URL=mongodb://localhost:27017
DATABASE_NAME=advandeb_knowledge_builder_kb

# Ollama Settings
OLLAMA_BASE_URL=http://localhost:11434

# API Settings
API_HOST=0.0.0.0
API_PORT=8000

# File Upload Settings
MAX_FILE_SIZE=50000000
UPLOAD_DIR=uploads
```

### AI Model Configuration

Install and run Ollama locally (no external API keys required)
   ```bash
   # Install Ollama
   curl -fsSL https://ollama.ai/install.sh | sh
   
   # Start Ollama service
   ollama serve
   
   # Pull required models
   ollama pull llama2
   ollama pull codellama
   ```

## API Documentation

The backend provides a comprehensive REST API. Access the interactive documentation at:
- Swagger UI: http://localhost:8000/docs
- ReDoc: http://localhost:8000/redoc

### Key Endpoints

- `/api/knowledge/*` - Knowledge base operations
- `/api/agents/*` - AI agent interactions (Ollama-only)
- `/api/data/*` - Data processing operations
- `/api/viz/*` - Visualization and graph operations

## Development

### Quick Development Setup

For developers who want to get started quickly:

```bash
# Clone and setup
git clone https://github.com/AdvanDEB/advandeb-knowledge-builder.git
cd advandeb-knowledge-builder
./setup.sh

# Alternative: Use Makefile commands
make setup     # Run setup script
make backend   # Start backend (in one terminal)
make frontend  # Start frontend (in another terminal)
```

For manual startup:
```bash
# Start development servers (in separate terminals)
conda activate advandeb-knowledge-builder-backend
cd backend && uvicorn main:app --reload &
cd frontend && npm run dev &

# Start external services
ollama serve &  # If not already running
```

### Development Workflow

1. **Backend Development**:
   ```bash
   conda activate advandeb-knowledge-builder-backend
   cd backend
   uvicorn main:app --reload  # Auto-reload on changes
   ```

2. **Frontend Development**:
   ```bash
   cd frontend
   npm run dev  # Hot reload enabled
   ```

3. **Environment Management**:
   ```bash
   # Update Python dependencies
   conda env update -f backend/environment.yml
   
   # Update JavaScript dependencies  
   cd frontend && npm install
   
   # Or use Makefile for convenience
   make install  # Update all dependencies
   make clean    # Clean and reset environments
   ```

4. **Development Shortcuts**:
   ```bash
   # Use Makefile for common tasks
   make help     # Show available commands
   make setup    # Initial setup
   make backend  # Start backend server
   make frontend # Start frontend server
   ```

### Project Structure

```
advandeb-knowledge-builder/
├── backend/                 # FastAPI backend
│   ├── routers/            # API route handlers
│   ├── services/           # Business logic
│   ├── models/             # Data models
│   ├── database/           # Database configuration
│   ├── config/             # Application settings
│   └── environment.yml     # Conda environment
├── frontend/               # Vue.js frontend
│   ├── src/
│   │   ├── views/          # Page components
│   │   ├── components/     # Reusable components
│   │   └── services/       # API clients
│   └── package.json        # npm dependencies
├── docs/                   # Documentation
└── setup.sh              # Native development setup
```

### Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Add tests if applicable
5. Submit a pull request

## License

This project is licensed under the MIT License - see the LICENSE file for details.

## Support

For questions and support:
- Create an issue on GitHub
- Check the documentation
- Review the API documentation

## Roadmap

- [ ] Advanced entity linking
- [ ] Real-time collaboration
- [ ] Enhanced graph algorithms
- [ ] Mobile application
- [ ] Plugin system
- [ ] Advanced search capabilities
