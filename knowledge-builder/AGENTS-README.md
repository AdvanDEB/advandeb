# AdvanDEB Multi-Agent System

## Overview

The AdvanDEB Knowledge Builder implements a **multi-agent RAG-KG hybrid system** for semantic search, knowledge graph traversal, and cited answer generation. The system consists of 5 specialized agents that communicate via the MCP (Model Context Protocol) over WebSocket.

## Architecture

```
┌─────────────────────────────────────────────────┐
│         MULTI-AGENT COORDINATION                │
│    (Agents communicate via MCP protocol)        │
│                                                  │
│  Query Planner → Retrieval → Graph Explorer     │
│                      ↓              ↓            │
│                  Synthesis ← Curator             │
└─────────────────────┬───────────────────────────┘
                      │
        ┌─────────────┴──────────────┐
        │                            │
┌───────▼────────┐         ┌─────────▼────────┐
│  HYBRID RAG    │         │  KNOWLEDGE GRAPH │
│                │         │                  │
│ • ChromaDB     │◄────────┤  • ArangoDB      │
│   (vectors)    │ refs    │    (graph DB)    │
│ • Sentence     │         │  • MongoDB       │
│   Transformers │         │    (documents)   │
│ • Reranking    │         │  • Graph edges   │
└────────────────┘         └──────────────────┘
```

## The Five Agents

### 1. Retrieval Agent (Port 8081)
**Specialization**: Semantic and hybrid document retrieval

**Tools**:
- `semantic_search` — Pure vector similarity search via ChromaDB
- `hybrid_search` — Vector + keyword + RRF fusion + optional LLM reranking
- `find_similar_chunks` — Find chunks similar to a given chunk ID
- `embed_query` — Return the embedding vector for a query string

**Dependencies**:
- ChromaDB (embedded mode, no server needed)
- sentence-transformers model (`all-MiniLM-L6-v2`)
- MongoDB (for keyword search fallback)
- Ollama (optional, for LLM reranking)

### 2. Graph Explorer Agent (Port 8082)
**Specialization**: Knowledge graph traversal and context expansion

**Tools**:
- `expand_context` — Expand context by traversing graph from seed chunks
- `get_citation_chain` — Get full citation provenance for a document
- `find_related_facts` — Find facts related to retrieved chunks
- `traverse_graph` — Custom AQL graph traversal queries
- `find_taxa_for_document` — Find taxa linked to a document

**Dependencies**:
- ArangoDB (optional; returns empty results if unavailable)
- MongoDB

### 3. Synthesis Agent (Port 8083)
**Specialization**: Multi-source answer generation with citations

**Tools**:
- `synthesize_answer` — Generate cited answer from chunks + graph context
- `attribute_citations` — Extract and map citation markers `[1]`, `[2]` to sources
- `summarize_context` — Summarize retrieved context before synthesis

**Dependencies**:
- Ollama (required for answer generation)
- MongoDB (for citation metadata)

### 4. Query Planner Agent (Port 8084)
**Specialization**: Multi-agent orchestration and workflow planning

**Tools**:
- `plan_query` — Decompose query into multi-agent workflow (LLM or template-based)
- `execute_plan` — Execute a multi-step plan with inter-agent calls
- `full_pipeline` — Hardwired 3-step pipeline: retrieve → graph_expand → synthesize

**Dependencies**:
- All other agents (calls them via MCP)
- Ollama (optional, for LLM-based planning)

### 5. Curator Agent (Port 8085)
**Specialization**: Knowledge curation and graph building

**Tools**:
- `extract_facts` — Extract structured facts from documents
- `stylize_fact` — Match facts to stylized facts and suggest relations
- `build_knowledge_graph` — Build knowledge graph from stylized facts
- `get_curation_queue` — List pending facts awaiting curator review
- `confirm_relation` — Curator action: confirm a suggested fact-SF relation
- `reject_relation` — Curator action: reject a suggested relation

**Dependencies**:
- MongoDB (for document, fact, stylized_fact collections)
- Ollama (for fact extraction)

## Quick Start

### 1. Prerequisites

Make sure the following services are running:
```bash
# MongoDB (required)
# Default: localhost:27017

# Redis (optional, for async batch jobs)
redis-server

# Ollama (required for synthesis, curator, LLM reranking)
ollama serve
```

ChromaDB runs in **embedded mode** (no server needed). It persists to `./data/chromadb`.

ArangoDB is **optional**; agents degrade gracefully if unavailable.

### 2. Install Dependencies

```bash
cd knowledge-builder
conda activate advandeb  # or your Python 3.11+ environment
pip install -e .
```

### 3. Start All Agents

```bash
python scripts/start_agents.py
```

This will:
- Start all 5 agents as background processes
- Write logs to `./logs/agents/<agent_name>.log`
- Save PIDs to `./logs/agents/pids.json`

**Start specific agents**:
```bash
python scripts/start_agents.py --agents retrieval graph_explorer
```

**Check health**:
```bash
python scripts/start_agents.py --health-check
```

**Stop all agents**:
```bash
python scripts/start_agents.py --stop
```

### 4. Verify Agents Are Running

```bash
python test_agents_basic.py
```

Expected output:
```
============================================================
AdvanDEB Knowledge Builder - Agent System Smoke Test
============================================================
🧪 Testing agent imports...
✅ All agents imported successfully

🧪 Testing MCP protocol...
✅ MCP protocol working

🧪 Testing services...
✅ All services can be instantiated

🧪 Testing RetrievalAgent initialization...
✅ RetrievalAgent initialized with 4 tools: ['semantic_search', 'hybrid_search', 'find_similar_chunks', 'embed_query']

============================================================
Test Results: 4/4 passed
============================================================
✅ All tests passed! Agent system is ready.
```

## Usage Examples

### Example 1: Direct Agent Call (Python)

```python
import asyncio
from advandeb_kb.mcp.protocol import MCPClient

async def search_knowledge_base():
    # Connect to Retrieval Agent
    client = MCPClient("ws://localhost:8081")
    
    # Call semantic_search tool
    result = await client.call_tool(
        name="semantic_search",
        arguments={
            "query": "Dynamic Energy Budget theory for fish",
            "top_k": 5
        }
    )
    
    print(f"Found {len(result['chunks'])} chunks:")
    for chunk in result['chunks']:
        print(f"  - {chunk['text'][:100]}...")

asyncio.run(search_knowledge_base())
```

### Example 2: Multi-Agent Workflow

```python
import asyncio
from advandeb_kb.mcp.protocol import MCPClient

async def full_rag_pipeline(query: str):
    # Use Query Planner for full pipeline
    planner = MCPClient("ws://localhost:8084")
    
    result = await planner.call_tool(
        name="full_pipeline",
        arguments={"query": query}
    )
    
    # Extract answer and citations
    answer = result['synthesis']['answer']
    citations = result['synthesis']['citations']
    
    print(f"Question: {query}")
    print(f"Answer: {answer}")
    print(f"\nCitations ({len(citations)}):")
    for i, cite in enumerate(citations, 1):
        print(f"  [{i}] {cite['document_title']} (chunk {cite['chunk_id']})")

asyncio.run(full_rag_pipeline("How do fish allocate energy between growth and reproduction?"))
```

### Example 3: Graph Expansion

```python
import asyncio
from advandeb_kb.mcp.protocol import MCPClient

async def explore_citations(document_id: str):
    # Connect to Graph Explorer Agent
    explorer = MCPClient("ws://localhost:8082")
    
    # Get full citation chain
    result = await explorer.call_tool(
        name="get_citation_chain",
        arguments={"document_id": document_id}
    )
    
    print(f"Citation chain for {document_id}:")
    for step in result['citation_chain']:
        print(f"  → {step['document_title']} ({step['year']})")

asyncio.run(explore_citations("some_doc_id"))
```

## Configuration

Environment variables (see `advandeb_kb/config/settings.py`):

```bash
# MongoDB
MONGODB_URL=mongodb://localhost:27017
DATABASE_NAME=advandeb_knowledge_builder_kb

# ArangoDB (optional)
ARANGO_URL=http://localhost:8529
ARANGO_DB_NAME=advandeb_kb
ARANGO_USERNAME=root
ARANGO_PASSWORD=advandeb2024

# ChromaDB (embedded mode)
CHROMA_PERSIST_DIR=./data/chromadb
CHROMA_COLLECTION=advandeb_chunks

# Embedding model
EMBEDDING_MODEL=all-MiniLM-L6-v2

# Ollama
OLLAMA_BASE_URL=http://localhost:11434

# Redis (for async batch jobs)
REDIS_URL=redis://localhost:6379/0
```

## Testing

### Unit Tests

```bash
cd knowledge-builder
pytest tests/test_agent_pipeline.py -v
```

**Test coverage**:
- MCP protocol (message handling, tool registration, error handling)
- Chunking service (recursive splitting, overlap, metadata)
- Cache service (LRU, TTL, Redis backend)
- RRF fusion (reciprocal rank fusion)
- Synthesis agent (citation extraction)
- Query planner (plan parsing, argument resolution)
- Provenance models (trace building)

**Current status**: 39/39 tests passing ✅

### Integration Tests

Integration testing with Dev 2's MCP Gateway is **pending** (Week 6 milestone).

## Agent Logs

All agents write logs to `./logs/agents/<agent_name>.log`:

```bash
# Tail all logs
tail -f logs/agents/*.log

# Tail specific agent
tail -f logs/agents/retrieval.log
```

## Troubleshooting

### Agent won't start

1. **Check logs**: `tail -f logs/agents/<agent_name>.log`
2. **Verify dependencies**:
   ```bash
   # Test imports
   python -c "from advandeb_kb.agents.retrieval_agent import RetrievalAgent"
   
   # Test services
   python test_agents_basic.py
   ```
3. **Check ports**: Make sure ports 8081-8085 are not already in use
   ```bash
   netstat -tulpn | grep 808
   ```

### ChromaDB initialization fails

- Check `CHROMA_PERSIST_DIR` is writable
- Default location: `./data/chromadb`
- No server needed (embedded mode)

### Embedding model download fails

If you see SSL errors or slow downloads:
```bash
# Set HuggingFace token (optional, for higher rate limits)
export HF_TOKEN=your_token_here

# Or use local cache if model already downloaded
export TRANSFORMERS_CACHE=/path/to/.cache/huggingface
```

### Ollama connection fails

```bash
# Verify Ollama is running
curl http://localhost:11434/api/tags

# Start Ollama
ollama serve
```

### Agent health check fails

```bash
# Check agent processes
ps aux | grep "advandeb_kb.agents"

# Check WebSocket connectivity
python scripts/start_agents.py --health-check
```

## Development

### Adding a New Agent

1. Create `advandeb_kb/agents/my_agent.py`:
   ```python
   from advandeb_kb.agents.base_agent import BaseAgent
   
   class MyAgent(BaseAgent):
       def __init__(self):
           super().__init__(name="my_agent", port=8086, host="localhost")
       
       async def initialize(self):
           # Initialize resources (DB connections, models, etc.)
           pass
       
       def register_tools(self):
           self.server.register_tool(
               name="my_tool",
               handler=self._my_tool,
               description="Tool description",
               input_schema={
                   "type": "object",
                   "properties": {
                       "param": {"type": "string"}
                   },
                   "required": ["param"]
               }
           )
       
       async def _my_tool(self, param: str) -> dict:
           return {"result": param}
   
   if __name__ == "__main__":
       import asyncio
       agent = MyAgent()
       asyncio.run(agent.start())
   ```

2. Add to `scripts/start_agents.py` AGENTS registry
3. Export in `advandeb_kb/agents/__init__.py`
4. Add tests in `tests/test_agent_pipeline.py`

### Adding a New Tool to Existing Agent

```python
# In your agent class
def register_tools(self):
    # ... existing tools ...
    
    self.server.register_tool(
        name="new_tool",
        handler=self._new_tool,
        description="New tool description",
        input_schema={
            "type": "object",
            "properties": {
                "input": {"type": "string"}
            },
            "required": ["input"]
        }
    )

async def _new_tool(self, input: str) -> dict:
    # Tool implementation
    return {"output": input}
```

## Performance Metrics

Current performance targets (Week 11-12 goals):

| Metric | Target | Status |
|--------|--------|--------|
| Simple query latency (p95) | <500ms | ⚪ Not measured |
| Multi-agent query latency | <2s | ⚪ Not measured |
| Semantic search precision@10 | >0.7 | ⚪ Not measured |
| Provenance coverage | >95% | ⚪ Not measured |
| Zero hallucinations | 100% | ⚪ Not validated |

## Roadmap

### Week 6: MCP Gateway Integration (🔴 CRITICAL — BLOCKED)
- **Status**: Not started
- **Blocker**: Depends on Dev 2's MCP Gateway
- **Tasks**:
  - [ ] Connect agents to MCP Gateway
  - [ ] End-to-end test: App → Gateway → Agents
  - [ ] Performance testing (<500ms target)

### Future Enhancements
- [ ] Agent load balancing (multiple instances per agent type)
- [ ] Agent health monitoring dashboard
- [ ] Distributed tracing for multi-agent workflows
- [ ] Caching layer for frequent queries
- [ ] GPU acceleration for embeddings
- [ ] Streaming responses for long-running synthesis

## Related Documentation

- [DEV1-KNOWLEDGE-BUILDER-PLAN.md](../docs/DEV1-KNOWLEDGE-BUILDER-PLAN.md) — 12-week implementation plan
- [KNOWLEDGE-BUILDER-MULTI-AGENT-PLAN.md](../docs/KNOWLEDGE-BUILDER-MULTI-AGENT-PLAN.md) — Multi-agent architecture
- [DEV1-LOG.md](../DEV1-LOG.md) — Development log and progress tracking
- [CLAUDE.md](CLAUDE.md) — Development guidelines for this component

## License

See main project LICENSE file.
