# AdvanDEB Modeling Assistant - API Documentation

## Base URL

```
http://localhost:8000/api
```

## Authentication

All endpoints except `/auth/*` require authentication via JWT token in the Authorization header:

```
Authorization: Bearer <access_token>
```

## Endpoints

### Authentication

#### POST /auth/google
Authenticate with Google OAuth 2.0

**Request:**
```json
{
  "code": "string",
  "redirect_uri": "string"
}
```

**Response:**
```json
{
  "access_token": "string",
  "refresh_token": "string",
  "token_type": "bearer",
  "user": {
    "id": "string",
    "email": "string",
    "full_name": "string",
    "roles": ["string"],
    "capabilities": ["string"]
  }
}
```

### Users

#### GET /users/me
Get current user profile

#### PUT /users/me
Update current user profile

#### GET /users (Admin only)
List all users

#### POST /users/{user_id}/roles (Admin only)
Assign role to user

### Documents

These are user *suggestions*, kept in the app database. A suggestion carries no
PDF; to add a paper to the KB, upload it with `POST /kb/ingestion/upload`
(curator), which saves it and queues the ingestion pipeline.

#### POST /documents
Submit a document suggestion (title, DOI/URL, metadata)

#### GET /documents
List suggestions (optional `status` filter)

#### GET /documents/{document_id}
Get a suggestion by ID

#### PATCH /documents/{document_id}/approve (Curator)
`{"action": "reject", "comment": "..."}` marks it rejected. `"approve"` is
refused with 409 and the reason; the suggestion stays open.

#### DELETE /documents/{document_id} (Curator)
Delete a suggestion

### Facts

#### POST /facts
Create fact

#### GET /facts
List facts (with optional status filter)

#### GET /facts/{fact_id}
Get fact by ID

#### POST /facts/stylized
Create stylized fact

#### GET /facts/stylized
List stylized facts

### Knowledge Graph

#### GET /graph
Get knowledge graph

#### GET /graph/query
Query knowledge graph

### Chat

#### POST /chat
Send chat message

**Request:**
```json
{
  "messages": [
    {"role": "user", "content": "string"}
  ],
  "session_id": "string"
}
```

**Response:**
```json
{
  "message": {
    "role": "assistant",
    "content": "string"
  },
  "session_id": "string"
}
```

#### GET /chat/sessions
List chat sessions

#### GET /chat/sessions/{session_id}
Get chat session by ID

### Scenarios

#### POST /scenarios
Create scenario

#### GET /scenarios
List scenarios

#### GET /scenarios/{scenario_id}
Get scenario by ID

#### PUT /scenarios/{scenario_id}
Update scenario

#### DELETE /scenarios/{scenario_id}
Delete scenario

### Models

#### POST /models
Create model

#### GET /models
List models (optionally filtered by scenario_id)

#### GET /models/{model_id}
Get model by ID

#### PUT /models/{model_id}
Update model

#### DELETE /models/{model_id}
Delete model

## Interactive API Documentation

Visit `http://localhost:8000/docs` for interactive Swagger UI documentation when the backend is running.
