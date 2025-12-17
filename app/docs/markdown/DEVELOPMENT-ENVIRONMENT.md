# AdvanDEB Modeling Assistant - Development Environment

## Prerequisites

- Python 3.11+
- Node.js 18+
- MongoDB 6.0+
- Google Cloud Project with OAuth 2.0 credentials
- (Optional) Ollama for local LLM
- (Optional) advandeb-MCP server running

## Backend Setup

### 1. Create Virtual Environment

```bash
cd backend
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

### 2. Install Dependencies

```bash
pip install -r requirements.txt
```

### 3. Configure Environment

```bash
cp .env.example .env
```

Edit `.env` and configure:

- **JWT_SECRET_KEY**: Generate with `openssl rand -hex 32`
- **GOOGLE_CLIENT_ID**: From Google Cloud Console
- **GOOGLE_CLIENT_SECRET**: From Google Cloud Console
- **MONGODB_URI**: Your MongoDB connection string
- **MCP_SERVER_URL**: URL of MCP server (if available)

### 4. Run Backend

```bash
uvicorn app.main:app --reload
```

API will be available at `http://localhost:8000`
API docs at `http://localhost:8000/docs`

## Frontend Setup

### 1. Install Dependencies

```bash
cd frontend
npm install
```

### 2. Configure Environment

```bash
cp .env.example .env.local
```

Edit `.env.local` and configure:

- **VITE_API_BASE_URL**: Backend API URL (default: http://localhost:8000)
- **VITE_GOOGLE_CLIENT_ID**: Same as backend Google Client ID

### 3. Run Frontend

```bash
npm run dev
```

Frontend will be available at `http://localhost:5173`

## MongoDB Setup

### Local MongoDB

```bash
# macOS with Homebrew
brew install mongodb-community
brew services start mongodb-community

# Ubuntu/Debian
sudo apt-get install mongodb
sudo systemctl start mongodb

# Or use Docker
docker run -d -p 27017:27017 --name mongodb mongo:latest
```

### MongoDB Atlas (Cloud)

1. Create free cluster at https://www.mongodb.com/cloud/atlas
2. Get connection string
3. Add to `.env` as `MONGODB_URI`

## Google OAuth Setup

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create new project or select existing
3. Enable Google+ API
4. Create OAuth 2.0 credentials:
   - Application type: Web application
   - Authorized redirect URIs:
     - `http://localhost:8000/api/auth/callback` (backend)
     - `http://localhost:5173/login` (frontend)
5. Copy Client ID and Client Secret to `.env` files

## Optional: MCP Server Setup

If you want to use the chat/agent features:

1. Clone and build advandeb-MCP repository
2. Configure MCP server
3. Start MCP server
4. Update `MCP_SERVER_URL` in backend `.env`

## Optional: Ollama Setup

For local LLM inference:

1. Install Ollama: https://ollama.ai/
2. Pull a model: `ollama pull llama2`
3. Ollama runs on `http://localhost:11434` by default

## Development Tools

### Backend Linting and Formatting

```bash
cd backend
black app/
isort app/
mypy app/
flake8 app/
```

### Frontend Linting and Formatting

```bash
cd frontend
npm run lint
npm run format
```

### Running Tests

```bash
# Backend
cd backend
pytest

# Frontend
cd frontend
npm run test
```

## Troubleshooting

### Port Already in Use

```bash
# Kill process on port 8000
lsof -ti:8000 | xargs kill -9

# Kill process on port 5173
lsof -ti:5173 | xargs kill -9
```

### MongoDB Connection Issues

- Check MongoDB is running: `mongosh`
- Verify connection string in `.env`
- Check firewall settings

### Google OAuth Errors

- Verify redirect URIs match exactly
- Check Client ID and Secret are correct
- Ensure Google+ API is enabled

## Next Steps

1. Create first admin user manually in MongoDB
2. Test authentication flow
3. Upload a test document
4. Explore the API documentation at `/docs`
5. Start implementing features according to DEVELOPMENT-PLAN.md
