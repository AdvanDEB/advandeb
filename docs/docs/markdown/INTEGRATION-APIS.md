# AdvanDEB Integration APIs (Draft)

This document describes the **high-level HTTP API contracts** between:

- `advandeb-knowledge-builder` (KB)
- `advandeb-modeling-assistant` (MA)

The goal is to allow the modeling assistant to consume knowledge and agents provided by the knowledge builder without tight coupling.

> Status: **Draft** – shapes and fields may evolve as implementation proceeds.

## 1. Knowledge Search

### 1.1 Search Knowledge

**Endpoint (KB):**

```http
GET /api/knowledge/search
```

**Query parameters (examples):**

- `q` (string, required): free-text query
- `type` (string, optional): one of `fact`, `stylized_fact`, `graph_node`
- `limit` (int, optional, default 50)

**Response (200):**

```json
{
  "results": [
    {
      "id": "string",
      "type": "fact",
      "text": "string",
      "source": "string",
      "score": 0.92,
      "tags": ["string"]
    }
  ]
}
```

MA will typically call this to retrieve relevant knowledge items for a modeling scenario.

## 2. Facts and Stylized Facts

### 2.1 Get Fact by ID

**Endpoint (KB):**

```http
GET /api/knowledge/facts/{fact_id}
```

**Response (200):**

```json
{
  "id": "string",
  "text": "string",
  "source": "string",
  "created_at": "ISO-8601",
  "tags": ["string"],
  "metadata": {"key": "value"}
}
```

### 2.2 Get Stylized Fact by ID

**Endpoint (KB):**

```http
GET /api/knowledge/stylized-facts/{stylized_fact_id}
```

**Response (200):**

```json
{
  "id": "string",
  "text": "string",
  "evidence_ids": ["fact-id-1", "fact-id-2"],
  "source": "string",
  "created_at": "ISO-8601",
  "tags": ["string"],
  "metadata": {"key": "value"}
}
```

MA can use these endpoints to fetch concrete evidence backing higher-level modeling assumptions.

## 3. Graph Exploration

### 3.1 Get Local Neighborhood

**Endpoint (KB):**

```http
GET /api/knowledge/graph/neighborhood
```

**Query parameters:**

- `node_id` (string, required)
- `depth` (int, optional, default 1)
- `max_nodes` (int, optional, default 200)

**Response (200):**

```json
{
  "nodes": [
    { "id": "string", "label": "string", "type": "entity" }
  ],
  "edges": [
    { "source": "node-id-1", "target": "node-id-2", "type": "relation" }
  ]
}
```

MA may use this to show how a proposed model element fits into the broader knowledge graph.

## 4. Agent Invocation

### 4.1 Run Knowledge Builder Agent

**Endpoint (KB):**

```http
POST /api/agents/run
Content-Type: application/json
```

**Request body (example):**

```json
{
  "agent_id": "kb-modeling-helper",
  "input": "Describe candidate model structures for host-parasite dynamics given these facts...",
  "context": {
    "fact_ids": ["f1", "f2"],
    "stylized_fact_ids": ["sf1"],
    "graph_node_ids": ["n1", "n2"]
  },
  "session_id": "optional-session-id"
}
```

**Response (200):**

```json
{
  "output": "Model suggestion text or structured JSON",
  "tool_calls": [
    {
      "tool": "knowledge_search",
      "args": {"q": "string"},
      "result_summary": "string"
    }
  ],
  "session_id": "session-id"
}
```

MA can treat this as a high-level reasoning service over the KB, while still making direct calls to lower-level endpoints when needed.

## 5. Modeling Assistant API (Outbound)

MA will expose its own APIs for frontends or external tools. These **consume** the KB APIs above.

### 5.1 Create Scenario (MA)

```http
POST /api/scenarios
Content-Type: application/json
```

**Request:**

```json
{
  "name": "Host-parasite dynamics in salmon",
  "description": "Exploratory scenario focusing on lice infestation dynamics.",
  "objectives": ["understand infestation prevalence", "explore treatment strategies"],
  "knowledge_queries": [
    { "q": "sea lice infection lifecycle", "tags": ["salmon", "parasite"] }
  ]
}
```

**Response (201):**

```json
{
  "id": "scenario-id",
  "status": "created"
}
```

### 5.2 Propose Model for Scenario (MA)

```http
POST /api/scenarios/{scenario_id}/propose-model
Content-Type: application/json
```

**Request:**

```json
{
  "strategy": "default"  
}
```

**Response (200):**

```json
{
  "model_id": "model-id",
  "structure": {
    "entities": ["host", "parasite"],
    "state_variables": ["infection_status", "age"],
    "processes": ["transmission", "recovery"],
    "parameters": [
      { "name": "beta", "description": "transmission rate" }
    ]
  },
  "justification": "Textual explanation referencing KB items.",
  "referenced_knowledge_ids": ["f1", "sf1", "n2"]
}
```

These MA endpoints are **clients** of the KB contracts defined earlier.
