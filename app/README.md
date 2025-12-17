# advandeb-modeling-assistant

**Main Platform GUI** for the AdvanDEB project - the single entry point for all users.

## Overview

The Modeling Assistant serves as the **primary user interface** for the entire AdvanDEB platform, providing:

- **Authentication**: Google OAuth integration and user management
- **Role-Based Access**: Features shown/hidden based on user roles (Administrator, Curator, Explorer)
- **Chat Interface**: AI-powered chat using MCP server for LLM inference
- **Knowledge Exploration**: Browse facts, stylized facts, and knowledge graphs
- **Document Ingestion**: Interactive UI for uploading and processing documents
- **Modeling Features**: Scenario creation and model development

## Architecture

This application is the main GUI that integrates:
- **Knowledge Builder** - Imported as a Python package/toolkit for knowledge operations
- **MCP Server** - Called for agent-powered features and LLM capabilities
- **MongoDB** - Shared database for knowledge, users, and audit logs

## Technology Stack

- **Backend**: FastAPI (Python)
- **Frontend**: Vue.js
- **Database**: MongoDB
- **Authentication**: Google OAuth 2.0 + JWT tokens
- **LLM Integration**: Via MCP server (Rust) with Ollama

## Repository Status

This repository is currently a placeholder. Active development will begin following the architecture revision documented in the `advandeb-architecture` repository.

See: https://github.com/AdvanDEB/advandeb-architecture

## Planned Structure

```
advandeb-modeling-assistant/
├── backend/              # FastAPI backend
│   ├── app/
│   │   ├── api/         # API routes
│   │   ├── auth/        # Google OAuth
│   │   ├── models/      # Pydantic models
│   │   └── services/    # Business logic
│   └── requirements.txt
├── frontend/             # Vue.js frontend
│   ├── src/
│   │   ├── components/  # UI components
│   │   ├── views/       # Main views
│   │   ├── router/      # Vue router
│   │   └── store/       # State management
│   └── package.json
└── README.md
```

## Development Roadmap

Implementation will follow the 6-phase plan outlined in the architecture documentation:

1. **Phase 1** (Weeks 1-4): Foundation - Authentication, user management, basic UI
2. **Phase 2** (Weeks 5-8): KB package integration
3. **Phase 3** (Weeks 9-12): Knowledge UIs - Document ingestion, fact browser, graph visualization
4. **Phase 4** (Weeks 13-16): MCP integration for agent features
5. **Phase 5** (Weeks 17-20): Chat interface
6. **Phase 6** (Weeks 21-24): Modeling features

For detailed implementation plan, see `ROADMAP.md` in the architecture repository.
