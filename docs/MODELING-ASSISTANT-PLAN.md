# advandeb-modeling-assistant: Development Plan

## Foundational Work

- Define scope: IBM-focused retrieval and reasoning on top of the AdvandEB knowledge base.
- Decide integration patterns with `advandeb-knowledge-builder` (HTTP APIs, shared DB, or both).
- Design initial domain model for modeling scenarios, model specs, and outputs.

## Initial Implementation

- Backend (FastAPI):
  - Service for querying knowledge relevant to modeling tasks.
  - Abstraction client for `advandeb-knowledge-builder` APIs.
  - Endpoints to assemble and describe model structures.

- Frontend (Vue or similar):
  - Scenario builder UI (organism, environment, objectives).
  - Panels for retrieved knowledge (facts, stylized facts, graphs) and proposed models.

## Medium-Term Goals

- Integrate with simulation backends (if applicable).
- Provide explanation and provenance views for model assumptions.
- Add saving/sharing of modeling scenarios.
