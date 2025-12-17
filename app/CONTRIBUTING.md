# Contributing to AdvanDEB Modeling Assistant

## Development Setup

1. Clone the repository
2. Set up backend:
   ```bash
   cd backend
   python -m venv venv
   source venv/bin/activate
   pip install -r requirements.txt
   cp .env.example .env
   # Edit .env with your configuration
   ```

3. Set up frontend:
   ```bash
   cd frontend
   npm install
   cp .env.example .env.local
   # Edit .env.local with API URL
   ```

4. Start MongoDB locally or use cloud instance

5. Run the application:
   ```bash
   # Terminal 1 - Backend
   cd backend
   uvicorn app.main:app --reload

   # Terminal 2 - Frontend
   cd frontend
   npm run dev
   ```

## Code Style

### Backend (Python)
- Follow PEP 8
- Use type hints
- Run `black` for formatting
- Run `isort` for import sorting
- Run `mypy` for type checking

### Frontend (TypeScript/Vue)
- Use TypeScript strict mode
- Follow Vue 3 Composition API patterns
- Run `eslint` for linting
- Run `prettier` for formatting

## Git Workflow

1. Create feature branch from `master`
2. Make changes with clear commit messages
3. Run tests and linters
4. Create pull request
5. Wait for review and approval

## Testing

- Write tests for new features
- Maintain test coverage
- Run full test suite before PR

## Documentation

- Update README for major changes
- Document API endpoints
- Add inline comments for complex logic
- Update architecture docs if needed
