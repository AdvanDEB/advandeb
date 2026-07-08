"""
BYOK chat synthesis — KAG + agentic tool-calling mode, entirely in-backend.

Pipeline for every external-key session:

  1. FAN-OUT RETRIEVAL  (parallel)
       hybrid_search          — vector + keyword RRF over chunked documents
       search_stylized_facts  — direct ArangoDB curated DEB facts
  2. GRAPH AUGMENTATION
       GraphExpansionService  — expand chunk seeds through the knowledge graph
                                → more facts, stylized facts, taxa context
  3. EVIDENCE REGISTRY
       EvidenceRegistry       — stable [N], [G1], [SF1] markers for all evidence
  4. SYNTHESIS  (two sub-modes)
     a. AGENTIC TOOL-CALLING  (Claude, OpenAI, GitHub Models, Nvidia)
          Multi-step: LLM calls search tools autonomously, accumulates evidence,
          then writes a final cited answer.
     b. SINGLE-PASS KAG  (all other providers)
          LLM receives the full EvidenceRegistry observation block and produces
          a cited answer in one call.

This design gives every provider access to the same graph-enriched evidence
that the Ollama chatbot_agent pipeline uses.  The plaintext API key is fetched,
used, and discarded here — it never crosses a process boundary.

Public API (unchanged from the caller's perspective):
    answer()        — non-streaming
    answer_stream() — streaming, yields token / status / result chunks
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any, AsyncIterator, Dict, List, Optional

from bson import ObjectId

from advandeb_kb.config.settings import settings
from advandeb_kb.services.evidence_registry_service import EvidenceRegistry

from app.clients.mcp_client import MCPClient
from app.core.database import get_database
from app.services.llm_key_service import LLMKeyService
from app.services.provenance_service import ProvenanceService

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# System prompts
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = (
    "You are a scientific knowledge assistant for Dynamic Energy Budget (DEB) "
    "theory and organism bioenergetics. Answer using ONLY the numbered sources "
    "provided. Cite sources inline as [1], [G1], [SF1], etc. matching the "
    "evidence markers. If the sources do not contain the answer, say so "
    "explicitly rather than guessing."
)

_SYSTEM_PROMPT_AGENT = (
    "You are an expert scientific research assistant for AdvanDEB — a bioenergetics "
    "research platform built on Dynamic Energy Budget (DEB) theory. "
    "You have access to a rich knowledge base and several search tools.\n\n"
    "TASK: Answer the user's question thoroughly and accurately.\n\n"
    "STRATEGY:\n"
    "1. You will receive initial evidence retrieved automatically. Use it as your "
    "   starting point.\n"
    "2. If the initial evidence is insufficient, call the search tools to find more. "
    "   Search for specific sub-questions, alternative phrasings, or related concepts.\n"
    "3. When you have enough evidence, write your final answer.\n\n"
    "CITATION RULES:\n"
    "- Every factual claim MUST carry at least one citation marker.\n"
    "- Use the markers from the evidence list: [1], [2], [G1], [SF1], etc.\n"
    "- Tool results are additional evidence — cite specific items from them.\n"
    "- Never fabricate information not present in the evidence.\n\n"
    "FORMAT:\n"
    "- Write a flowing prose answer with inline citations.\n"
    "- For complex questions, structure with clear paragraphs.\n"
    "- Prefer long, comprehensive answers over brief ones when the evidence supports it.\n\n"
    "CONVERSATIONAL MESSAGES:\n"
    "- If the user's message is a greeting, acknowledgement, clarification request, or "
    "  continuation that needs no new sources (e.g., 'Hi', 'Thanks', 'OK', 'Tell me more'), "
    "  respond naturally and conversationally WITHOUT calling any tools."
)

_SYSTEM_PROMPT_CONVERSATIONAL = (
    "You are AdvanDEB's research assistant — a helpful, friendly AI specialising in "
    "Dynamic Energy Budget (DEB) theory and organism bioenergetics. "
    "Respond naturally to the user's message. "
    "If they ask a scientific question about DEB or bioenergetics, let them know you can "
    "answer in depth — they just need to ask."
)

_SYSTEM_PROMPT_DEFINITIONAL = (
    "You are an expert scientific assistant for AdvanDEB, a bioenergetics research "
    "platform built on Dynamic Energy Budget (DEB) theory.\n\n"
    "TASK: Provide a clear, accurate definition or short explanation of the queried concept.\n\n"
    "STRATEGY: The initial stylized facts and evidence should fully cover a definitional "
    "question. Do NOT call search tools unless a critical citation is completely absent.\n\n"
    "CITATION RULES: Cite every factual claim with [SF1], [1], etc. "
    "Never fabricate information.\n\n"
    "FORMAT: 2–4 focused paragraphs with inline citations. Clear and accessible."
)

_SYSTEM_PROMPT_CONCEPTUAL = (
    "You are an expert scientific assistant for AdvanDEB, a bioenergetics research "
    "platform built on Dynamic Energy Budget (DEB) theory.\n\n"
    "TASK: Explain the concept thoroughly using the evidence provided.\n\n"
    "STRATEGY:\n"
    "1. Use the initial evidence as your primary source.\n"
    "2. You may make one targeted tool call if a specific sub-aspect is missing.\n"
    "3. Prefer stylized facts [SF] for theoretical DEB claims.\n\n"
    "CITATION RULES: Every factual claim must carry at least one citation. "
    "Never fabricate.\n\n"
    "FORMAT: Well-structured explanation with inline citations. Aim for clarity."
)

_SYSTEM_PROMPT_TARGETED = (
    "You are an expert scientific research assistant for AdvanDEB — a bioenergetics "
    "research platform built on Dynamic Energy Budget (DEB) theory. "
    "You have access to a rich knowledge base and search tools.\n\n"
    "TASK: Answer the specific scientific question thoroughly and accurately.\n\n"
    "STRATEGY:\n"
    "1. Assess the initial evidence: does it address the specific organism, parameter, "
    "   or mechanism asked about?\n"
    "2. If the initial evidence is sufficient, answer directly.\n"
    "3. If key specifics are missing, make 1–2 targeted searches for the gaps.\n\n"
    "CITATION RULES: Every factual claim must carry at least one citation marker "
    "([1], [G1], [SF1]). Never fabricate.\n\n"
    "FORMAT: Flowing prose with inline citations. Include relevant quantitative values "
    "if the evidence provides them.\n\n"
    "CONVERSATIONAL MESSAGES: For greetings or acks, respond naturally without tools."
)

_SYSTEM_PROMPT_INVESTIGATIVE = (
    "You are an expert scientific research assistant for AdvanDEB — a bioenergetics "
    "research platform built on Dynamic Energy Budget (DEB) theory. "
    "You have access to a rich knowledge base and several search tools.\n\n"
    "TASK: Investigate the question by exploring the knowledge base across multiple angles.\n\n"
    "STRATEGY:\n"
    "1. Use initial evidence as a starting point — identify what's present and what's missing.\n"
    "2. Make 2–4 targeted searches covering: the primary mechanism, organism-specific data, "
    "   related concepts, and alternative perspectives.\n"
    "3. Synthesise a comprehensive answer once you have sufficient evidence.\n\n"
    "CITATION RULES: Every factual claim must carry at least one citation. "
    "Tool results are citable evidence. Never fabricate.\n\n"
    "FORMAT: Well-structured answer with clear paragraphs and inline citations. "
    "Discuss mechanisms, evidence quality, and any limitations.\n\n"
    "CONVERSATIONAL MESSAGES: For greetings or acks, respond naturally without tools."
)

_SYSTEM_PROMPT_ANALYTICAL = (
    "You are an expert scientific research assistant for AdvanDEB — a bioenergetics "
    "research platform built on Dynamic Energy Budget (DEB) theory. "
    "You have access to a rich knowledge base and several search tools.\n\n"
    "TASK: Perform a deep, comprehensive analytical investigation.\n\n"
    "STRATEGY:\n"
    "1. Analyse the initial evidence: what patterns, gaps, or leads are visible?\n"
    "2. Use search tools extensively — cover multiple sub-questions, taxa, time periods, "
    "   and evidence types.\n"
    "3. For 'most supported' / 'most cited' questions, use get_claim_consensus to "
    "   quantify support levels.\n"
    "4. Aggregate across sources: note consensus, divergence, and confidence levels.\n"
    "5. Write a thorough analytical answer once you have a broad evidence base.\n\n"
    "CITATION RULES: Every factual claim must carry at least one citation. "
    "Report evidence counts and support levels where relevant. Never fabricate.\n\n"
    "FORMAT: Comprehensive analytical answer with sections. Include counts, patterns, "
    "representative examples, and confidence assessments. Prefer depth over brevity.\n\n"
    "CONVERSATIONAL MESSAGES: For greetings or acks, respond naturally without tools."
)

# ---------------------------------------------------------------------------
# Exploration tiers — adaptive pipeline depth
# ---------------------------------------------------------------------------


class ExplorationTier(str, Enum):
    DEFINITIONAL  = "definitional"   # "What is kappa?" — named concept, no context
    CONCEPTUAL    = "conceptual"     # "How does DEB model reserves?" — broader concept
    TARGETED      = "targeted"       # "DEB parameters for Daphnia" — organism/param specific
    INVESTIGATIVE = "investigative"  # "Significance of blubber in minke whale thermo?"
    ANALYTICAL    = "analytical"     # "Most supported stylized fact?" — KB meta-analysis


@dataclass(frozen=True)
class _TierParams:
    top_k:         int    # initial chunk retrieval size
    expand_graph:  bool   # whether to run graph augmentation
    max_steps:     int    # agentic tool-call budget
    system_prompt: str
    user_guidance: str    # appended to the initial user turn to calibrate depth


_TIER_PARAMS: Dict[ExplorationTier, _TierParams] = {
    ExplorationTier.DEFINITIONAL: _TierParams(
        top_k=5, expand_graph=False, max_steps=1,
        system_prompt=_SYSTEM_PROMPT_DEFINITIONAL,
        user_guidance=(
            "This is a short definitional question. "
            "Use the initial stylized facts and evidence to give a clear, cited answer. "
            "Do NOT call any search tools unless a critical citation is absent."
        ),
    ),
    ExplorationTier.CONCEPTUAL: _TierParams(
        top_k=8, expand_graph=False, max_steps=2,
        system_prompt=_SYSTEM_PROMPT_CONCEPTUAL,
        user_guidance=(
            "This is a conceptual explanation question. "
            "The initial evidence should cover most of it. "
            "Make at most one search call if a specific aspect is missing."
        ),
    ),
    ExplorationTier.TARGETED: _TierParams(
        top_k=12, expand_graph=True, max_steps=3,
        system_prompt=_SYSTEM_PROMPT_TARGETED,
        user_guidance=(
            "Answer this specific scientific question using the evidence. "
            "If the initial evidence is sufficient, answer directly. "
            "Search for gaps — organism-specific values, parameter data, "
            "or closely related mechanisms not yet covered."
        ),
    ),
    ExplorationTier.INVESTIGATIVE: _TierParams(
        top_k=18, expand_graph=True, max_steps=5,
        system_prompt=_SYSTEM_PROMPT_INVESTIGATIVE,
        user_guidance=(
            "This is a complex, multi-faceted question. "
            "Assess the initial evidence, then make 2–4 targeted searches to build "
            "a thorough picture before writing your answer."
        ),
    ),
    ExplorationTier.ANALYTICAL: _TierParams(
        top_k=25, expand_graph=True, max_steps=8,
        system_prompt=_SYSTEM_PROMPT_ANALYTICAL,
        user_guidance=(
            "This question requires comprehensive database exploration and analysis. "
            "Use multiple search queries, aggregate across sources, "
            "and use get_claim_consensus for 'most supported' questions. "
            "Build a broad evidence base before writing your analytical answer."
        ),
    ),
}

# ---------------------------------------------------------------------------
# Intent classification — fast pre-flight check before any DB work
# ---------------------------------------------------------------------------

_CONVERSATIONAL_RE = re.compile(
    r"^("
    # Greetings
    r"hi+\s*[!.?]*|hiya\s*[!.?]*|hello+\s*[!.?]*|hey+\s*[!.?]*"
    r"|howdy\s*[!.?]*|greetings\s*[!.?]*|sup\s*[!.?]*|yo\s*[!.?]*"
    # Acknowledgements / filler
    r"|thanks?\s*(you\s*)?[!.?]*|thx\s*[!.?]*|ty\s*[!.?]*|cheers\s*[!.?]*"
    r"|great\s*[!.?]*|awesome\s*[!.?]*|perfect\s*[!.?]*|wonderful\s*[!.?]*"
    r"|good\s*[!.?]*|nice\s*[!.?]*|cool\s*[!.?]*"
    r"|ok\s*[!.?]*|okay\s*[!.?]*|got\s+it\s*[!.?]*|understood\s*[!.?]*"
    r"|noted\s*[!.?]*|alright\s*[!.?]*|sure\s*[!.?]*|right\s*[!.?]*"
    r"|thank\s+you\s*(so\s+much)?\s*[!.?]*"
    r"|thanks\s+(a\s+lot|very\s+much|so\s+much)\s*[!.?]*"
    r"|that\s+'?s?\s+(great|perfect|awesome|helpful|wonderful|amazing)\s*[!.?]*"
    # Closings
    r"|bye+\s*[!.?]*|goodbye+\s*[!.?]*|see\s+you(\s+later|\s+soon)?\s*[!.?]*|cya\s*[!.?]*"
    # Simple yes/no
    r"|yes\s*[!.?]*|no\s*[!.?]*|yeah\s*[!.?]*|nope\s*[!.?]*|yep\s*[!.?]*|nah\s*[!.?]*"
    # Meta / capability questions
    r"|what\s+can\s+you\s+do\s*[?!.]*"
    r"|what\s+are\s+your\s+capabilities\s*[?!.]*"
    r"|(who|what)\s+are\s+you\s*[?!.]*"
    r"|tell\s+me\s+about\s+yourself\s*[?!.]*"
    r"|how\s+do\s+you\s+work\s*[?!.]*"
    r"|are\s+you\s+an?\s+(ai|assistant|bot|chatbot)\s*[?!.]*"
    # Continuation
    r"|(can\s+you\s+)?(continue|go\s+on|elaborate)\s*[?!.]*"
    r"|tell\s+me\s+more(\s+about\s+that)?\s*[?!.]*"
    r"|can\s+you\s+repeat(\s+that)?\s*[?!.]*"
    r"|what\s+did\s+you\s+mean(\s+by\s+that)?\s*[?!.]*"
    # Bare punctuation / whitespace
    r"|[.!?]+"
    r")$",
    re.IGNORECASE,
)

_DOMAIN_SIGNAL_RE = re.compile(
    r"\b(deb|dynamic\s+energy|bioenerg|organism|species|taxon|taxa|"
    r"metabol|energy\s+budget|kappa|assimilation|respiration|"
    r"maturity|reproduction|aging|isomorph\w*|reserve|structure|homeostasis|"
    r"arrhenius|ingestion|feeding|starvation|somatic|gonad|embryo|"
    r"juvenile|adult|von\s+bertalanffy|biomass|foraging|population|"
    r"parameter|equation|model\s+predict|coefficient)\b",
    re.IGNORECASE,
)


def _is_conversational(query: str) -> bool:
    """Return True when the message needs no KB retrieval (greeting, ack, filler)."""
    q = query.strip()
    if not q:
        return True
    if _CONVERSATIONAL_RE.match(q):
        return True
    # Short messages (≤ 4 words) with no domain signals are treated as conversational
    if len(q.split()) <= 4 and not _DOMAIN_SIGNAL_RE.search(q):
        return True
    return False


# ---------------------------------------------------------------------------
# Exploration-tier classification
# ---------------------------------------------------------------------------

# Analytical: meta-questions about the KB or broad aggregation/comparison
_ANALYTICAL_RE = re.compile(
    r"\b("
    r"most\s+(supported|cited|common|frequent|important|significant|studied|documented)|"
    r"best\s+(supported|established|documented)|"
    r"least\s+(supported|cited|common|documented)|"
    r"(how\s+many|count\s+of|number\s+of)\s+(facts|stylized|documents|papers|studies|species|taxa)|"
    r"(compare|contrast)\s+.{3,}\s+(and|vs\.?\s|versus|across|among|between)|"
    r"(compare|contrast)\s+(deb\s+)?(parameter|model|estimate|value)s?\s+(across|among|between|for\s+different)|"
    r"(summarize|overview|survey)\s+(all|every|the\s+entire|the\s+whole)|"
    r"(list|enumerate)\s+(all|every)\s+(species|taxa|facts|papers|documents)|"
    r"meta.?analy|systematic\s+review|"
    r"in\s+(your|the|this)\s+(database|knowledge\s*base|kb)\b|"
    r"\b(across|throughout)\s+all\s+(species|taxa|documents|papers|studies)|"
    r"(which|what)\s+(species|taxon|taxa|paper|fact|stylized\s+fact)\s+(has|have|is|are)\s+the\s+(most|least|best|highest|lowest)|"
    r"trend(s)?\s+in\s+(the\s+)?(database|kb|knowledge)|"
    r"pattern(s)?\s+in\s+the\s+(database|kb|knowledge)|"
    r"statistical\s+(support|significance|evidence)|"
    r"(evidence|support)\s+for\s+.{5,}(strong|weak|consensus|conflicting)"
    r")\b",
    re.IGNORECASE,
)

# Investigative tier A: patterns that become investigative when an organism is present
# (pure DEB-theory versions of these phrases map to CONCEPTUAL)
_INVESTIGATIVE_WITH_ORG_RE = re.compile(
    r"\b("
    r"significance\s+of|"
    r"role\s+of\s+.{3,}\s+in|"
    r"(how|why)\s+do(es)?\s+.{5,}\s+(affect|influence|regulate|modulate|control|drive)|"
    r"(effect|impact)\s+of\s+.{5,}\s+on|"
    r"(mechanism|pathway|process)\s+(behind|of|for|underlying)|"
    r"(trade.?off|tradeoff)\s+between"
    r")\b",
    re.IGNORECASE,
)

# Investigative tier B: inherently investigative regardless of organism context
_INVESTIGATIVE_ALWAYS_RE = re.compile(
    r"\b("
    r"endotherm\w*\s+(vs\.?|versus|compared\s+to|and\s+ectotherm)|"
    r"ectotherm\w*\s+(vs\.?|versus|compared\s+to|and\s+endotherm)|"
    r"(thermal|temperature)\s+regulation\s+in\s+(endotherm\w*|ectotherm\w*|marine|aquatic|terrestrial)"
    r")\b",
    re.IGNORECASE,
)

# Targeted: organism/species/parameter specificity
# No broad Genus-species catch-all — it false-positives on English phrases with IGNORECASE
_TARGETED_RE = re.compile(
    r"\b("
    r"(deb\s+)?(parameter|estimate|value)(s)?\s+for|"
    r"(for|in|of)\s+(the\s+)?"
    r"(whale|shark|tuna|salmon|cod|herring|anchovy|sardine|mussel|oyster|clam|"
    r"scallop|lobster|crab|shrimp|krill|copepod|coral|jellyfish|eel|trout|bass|"
    r"carp|tilapia|seal|dolphin|sea\s+lion|walrus|mouse|rat|rabbit|bird|penguin)|"
    r"(minke|sperm\s+whale|blue\s+whale|humpback\s+whale|beluga)|"
    r"(species.specific|taxon.specific|organism.specific)|"
    r"(growth|reproduction|survival)\s+(rate|pattern|curve)\s+(in|for|of)|"
    r"(temperature|salinity|food\s+availability)\s+(effect|impact)\s+(on|in)\s+(organism|species|fish|mammal)|"
    r"(field|laboratory|experimental)\s+(data|observation|measurement)\s+(for|from|on|in)"
    r")\b",
    re.IGNORECASE,
)

# Definitional: short "what is X" for a named DEB concept
_DEFINITIONAL_RE = re.compile(
    r"^(what\s+is|what\s+are|define|explain|describe|what\s+does|what\s+do)\s+"
    r"(?:the\s+|an?\s+|a\s+)?"
    r"(deb(\s+theory|\s+model|\s+framework|\s+approach)?|"
    r"dynamic\s+energy\s+budget|"
    r"kappa(\s+rule)?|the\s+kappa\s+rule|"
    r"von\s+bertalanffy(\s+growth)?|"
    r"assimilation(\s+efficiency|\s+rate)?|"
    r"somatic\s+maintenance|maturity(\s+threshold|\s+maintenance)?|"
    r"reserve\s+dynamics?|structural\s+(volume|biomass)|"
    r"isomorph(ic(\s+growth)?)?|arrhenius(\s+temperature|\s+correction)?|"
    r"weak\s+homeostasis|strong\s+homeostasis|drastic\s+shrinking|"
    r"p(-|\s*)curve|metabolic\s+acceleration|"
    r"energy\s+(assimilation|allocation|budget|reserve)|"
    r"(maturity|reproduction|growth|aging)\s+(in\s+deb|under\s+deb|according\s+to\s+deb)|"
    r"deb\s+(aging|ageing|theory\s+of\s+aging)|"
    r"κ\s+rule|κ-rule"
    r")\b",
    re.IGNORECASE,
)

# Organism names — presence pushes away from definitional/conceptual
# Leading \b prevents false starts; no trailing \b so plurals (oysters, mammals) also match.
# Explicit list only — no broad catch-all (causes false positives with IGNORECASE).
_ORGANISM_RE = re.compile(
    r"\b(?:whale|shark|tuna|salmon|cod|herring|anchovy|sardine|mussel|oyster|"
    r"clam|scallop|lobster|crab|shrimp|krill|copepod|coral|jellyfish|eel|trout|"
    r"bass|carp|tilapia|seal|dolphin|sea\s+lion|walrus|otter|mouse|rat|rabbit|"
    r"pig|cow|mammal|bird|penguin|albatross|daphnia|mytilus|gadus|thunnus|"
    r"minke\s+whale|sperm\s+whale|blue\s+whale|humpback\s+whale|beluga|narwhal)",
    re.IGNORECASE,
)


def _classify_query(query: str) -> ExplorationTier:
    """Classify a scientific query into an exploration tier.

    Tiers (lightest → deepest):
      DEFINITIONAL  — "What is kappa?" — named DEB concept, no organism context
      CONCEPTUAL    — "How do reserves work in DEB?" — broader concept, no organism
      TARGETED      — "DEB parameters for Daphnia" — organism/parameter specific
      INVESTIGATIVE — "Role of blubber in minke whale thermoregulation?" — multi-faceted
      ANALYTICAL    — "Most supported stylized fact?" — KB meta-analysis or aggregation
    """
    q = query.strip()

    # 1. Analytical overrides everything — explicit meta/aggregation intent
    if _ANALYTICAL_RE.search(q):
        return ExplorationTier.ANALYTICAL

    has_organism = bool(_ORGANISM_RE.search(q))

    # 2. Investigative — either inherently complex, or mechanism + organism context
    if _INVESTIGATIVE_ALWAYS_RE.search(q) or (has_organism and _INVESTIGATIVE_WITH_ORG_RE.search(q)):
        return ExplorationTier.INVESTIGATIVE

    # 3. Targeted — organism present or specific parameter/data request
    if _TARGETED_RE.search(q) or has_organism:
        return ExplorationTier.TARGETED

    # 4. Definitional — short "what is X" for a known DEB concept
    if _DEFINITIONAL_RE.match(q):
        return ExplorationTier.DEFINITIONAL

    # 5. Default: conceptual — scientific but not narrowly classified
    return ExplorationTier.CONCEPTUAL

# Tool definitions exposed to the LLM in agentic mode.
_CHAT_TOOLS: List[Dict[str, Any]] = [
    {
        "name": "search_knowledge_base",
        "description": (
            "Search the AdvanDEB bioenergetics knowledge base for relevant text chunks "
            "from scientific papers. Use this to find passages about a specific topic, "
            "organism, DEB parameter, or experimental finding."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Natural-language search query",
                },
                "top_k": {
                    "type": "integer",
                    "description": "Number of chunks to return (default 15, max 30)",
                    "default": 15,
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "search_stylized_facts",
        "description": (
            "Search the curated collection of DEB stylized facts — established, "
            "consensus bioenergetics statements and quantitative relationships. "
            "Use this to confirm theoretical claims or look up DEB parameters."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Query related to a DEB concept, parameter, or organism",
                },
                "limit": {
                    "type": "integer",
                    "description": "Max facts to return (default 10)",
                    "default": 10,
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "get_claim_consensus",
        "description": (
            "For a specific scientific claim, retrieve structured evidence showing "
            "which peer-reviewed sources support or oppose it, along with retraction "
            "and citation-impact signals. Use this to assess claim confidence."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "claim": {
                    "type": "string",
                    "description": "A precise scientific claim to evaluate",
                },
            },
            "required": ["claim"],
        },
    },
]

# Analytics tools — graph introspection, available in ANALYTICAL tier.
_ANALYTICS_TOOLS: List[Dict[str, Any]] = [
    {
        "name": "graph_stats",
        "description": (
            "Get an overview of the entire knowledge graph topology: collection sizes "
            "(how many documents, facts, stylized facts, taxa), edge counts across all "
            "graph layers, and optionally the top 10 most-connected stylized fact nodes. "
            "Use for meta-questions about the scale or shape of the knowledge base."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "include_degree_dist": {
                    "type": "boolean",
                    "description": "If true, also return the top-10 stylized facts by total edge count.",
                    "default": False,
                },
            },
        },
    },
    {
        "name": "analyze_sf_support",
        "description": (
            "Rank stylized facts by the strength of their evidence support in the "
            "knowledge graph. Returns facts sorted by support count, opposition count, "
            "net support, or support ratio — with full statement text and counts. "
            "Use for 'most supported / best evidenced / strongest consensus' questions. "
            "Optionally filter by category."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "category": {
                    "type": "string",
                    "description": (
                        "Filter to a category slug, e.g. 'biological_experiments_and_data_patterns', "
                        "'deb_theory_and_mathematical_formulation', 'metabolic_scaling_laws'. "
                        "Leave empty to search all categories."
                    ),
                },
                "sort_by": {
                    "type": "string",
                    "enum": ["support_count", "oppose_count", "net_support", "support_ratio"],
                    "description": (
                        "Ranking metric. support_count = raw supporting-fact edges; "
                        "net_support = support minus opposition; support_ratio = fraction of edges "
                        "that support (0–1, higher = less contested)."
                    ),
                    "default": "support_count",
                },
                "limit": {
                    "type": "integer",
                    "description": "Number of facts to return (max 20, default 10).",
                    "default": 10,
                },
            },
        },
    },
    {
        "name": "explore_graph_node",
        "description": (
            "Search for a specific node — a stylized fact, taxon (species), or document — "
            "by name or keyword, and show its immediate graph connections: "
            "supporting/opposing facts, taxa studied, citations. "
            "Use for 'what is connected to X', 'what supports this claim', "
            "'what species is studied by this paper', or 'what does this fact relate to'."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Keyword or name to search for (taxon name, SF text excerpt, document title)",
                },
                "node_type": {
                    "type": "string",
                    "enum": ["stylized_fact", "taxon", "document", "auto"],
                    "description": "Type of node to look for. Use 'auto' to search all types.",
                    "default": "auto",
                },
                "depth": {
                    "type": "integer",
                    "description": "Neighbourhood depth: 1 = immediate connections only (default), 2 = two hops.",
                    "default": 1,
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "find_taxa_connections",
        "description": (
            "Find which taxa (species, genus, etc.) are connected to a given DEB concept "
            "or topic through the knowledge graph — via documents that study them and facts "
            "that mention the concept. Use for 'which species are studied in relation to X', "
            "'what organisms does the KB cover for topic Y', or taxon-breadth questions."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "concept": {
                    "type": "string",
                    "description": "A DEB concept, topic, or keyword to find connected taxa for",
                },
                "rank": {
                    "type": "string",
                    "enum": ["species", "genus", "family", "order", "class", "any"],
                    "description": "Taxonomic rank to filter results. Default 'species'.",
                    "default": "species",
                },
                "limit": {
                    "type": "integer",
                    "description": "Max taxa to return (default 15, max 30).",
                    "default": 15,
                },
            },
            "required": ["concept"],
        },
    },
    {
        "name": "sf_category_breakdown",
        "description": (
            "Return aggregate evidence statistics for every stylized-fact category in the KB: "
            "how many SFs each category has, total support and opposition edge counts, "
            "average support per SF, contested fraction, and the best-evidenced SF in the category. "
            "Use for questions about KB coverage, which DEB sub-domains are best evidenced, "
            "or to orient the analysis before diving into individual SFs."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "find_contested_facts",
        "description": (
            "Find the most controversial stylized facts — those where the proportion of "
            "opposing evidence is highest. Returns SFs sorted by opposition ratio, with "
            "sample opposing fact excerpts. Use for questions about contested claims, "
            "scientific disagreements, or 'what is most debated in the literature'."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "min_total": {
                    "type": "integer",
                    "description": "Minimum total evidence edges (support + oppose) to consider a SF. Default 8.",
                    "default": 8,
                },
                "min_opposition_ratio": {
                    "type": "number",
                    "description": "Minimum fraction of edges that oppose (0.0–1.0). Default 0.10 (10%).",
                    "default": 0.10,
                },
                "limit": {
                    "type": "integer",
                    "description": "Number of contested facts to return (max 20, default 10).",
                    "default": 10,
                },
            },
        },
    },
    {
        "name": "citation_influence",
        "description": (
            "Rank documents in the KB by citation in-degree — how many other KB documents cite them. "
            "Identifies the most foundational/influential papers in the knowledge base. "
            "Use for 'most important papers', 'most cited works', or 'foundational references' questions. "
            "Also returns fact extraction counts per document."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "min_citations": {
                    "type": "integer",
                    "description": "Minimum in-degree to include a document. Default 1.",
                    "default": 1,
                },
                "limit": {
                    "type": "integer",
                    "description": "Number of documents to return (max 20, default 10).",
                    "default": 10,
                },
            },
        },
    },
    {
        "name": "sf_taxon_coverage",
        "description": (
            "For a specific stylized fact (matched by text keyword), trace through its supporting "
            "facts → source documents → knowledge graph to find which taxa (species/genus/etc.) "
            "the evidence covers. Answers 'is this claim supported across multiple species or just one?' "
            "and 'what organisms provide evidence for this DEB claim?'."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Text keyword to match the stylized fact statement",
                },
                "rank": {
                    "type": "string",
                    "enum": ["species", "genus", "family", "order", "class", "any"],
                    "description": "Taxonomic rank to filter the returned taxa. Default 'any' (all ranks).",
                    "default": "any",
                },
                "limit": {
                    "type": "integer",
                    "description": "Max taxa to return (default 20).",
                    "default": 20,
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "taxon_subtree_stats",
        "description": (
            "For a taxonomic group (genus, family, order, etc.), find all KB-covered descendants "
            "at a specified rank and show how many documents study each. "
            "Use for 'what fish species are in the KB', 'which Thunnus species are covered', "
            "or 'how many gadiform species have been studied'. Best for genus- or family-level queries."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "group_name": {
                    "type": "string",
                    "description": "Scientific name of the taxonomic group to explore (e.g. 'Gadus', 'Scombridae')",
                },
                "rank": {
                    "type": "string",
                    "enum": ["species", "genus", "family", "order", "class"],
                    "description": "Descendant rank to count. Default 'species'.",
                    "default": "species",
                },
                "limit": {
                    "type": "integer",
                    "description": "Max descendants to return (default 20).",
                    "default": 20,
                },
            },
            "required": ["group_name"],
        },
    },
]

# Conversation-memory window (turns).
_MEMORY_WINDOW = 6


class ByokSynthesisError(RuntimeError):
    """Raised when BYOK synthesis cannot complete (bad key, provider error)."""


class ByokChatService:
    """In-backend KAG retrieval + synthesis using a user's own LLM key.

    Implements a 4-step pipeline for every chat turn:
      retrieve → graph augment → build registry → synthesize (single-pass or agentic)
    """

    def __init__(self) -> None:
        db = get_database()
        self.sessions = db.chat_sessions
        self.messages = db.chat_messages
        self.memory = db.agent_memory
        self.keys = LLMKeyService()

    # ------------------------------------------------------------------ public

    async def answer(
        self,
        *,
        query: str,
        session_id: str,
        user_id: str,
        provider: str,
        key_id: Optional[str] = None,
        model: Optional[str] = None,
        top_k: int = 20,
        max_tokens: Optional[int] = None,
        direct_api_key: Optional[str] = None,
        system_prompt: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Non-streaming answer — collects from answer_stream."""
        result: Dict[str, Any] = {
            "answer": "An unexpected error occurred.",
            "citations": [],
            "evidence_mode": "local",
            "session_id": session_id,
            "message_id": "",
            "suggested_questions": [],
        }
        async for chunk in self.answer_stream(
            query=query,
            session_id=session_id,
            user_id=user_id,
            provider=provider,
            key_id=key_id,
            model=model,
            top_k=top_k,
            max_tokens=max_tokens,
            direct_api_key=direct_api_key,
            system_prompt=system_prompt,
        ):
            if chunk.get("type") == "result":
                result = {k: chunk[k] for k in chunk if k != "type"}
        return result

    async def answer_stream(
        self,
        *,
        query: str,
        session_id: str,
        user_id: str,
        provider: str,
        key_id: Optional[str] = None,
        model: Optional[str] = None,
        top_k: int = 20,
        max_tokens: Optional[int] = None,
        direct_api_key: Optional[str] = None,
        system_prompt: Optional[str] = None,
    ) -> AsyncIterator[Dict[str, Any]]:
        """Stream KAG chat events.

        Yields (same shapes as before so ChatService callers need no changes):
          {"type": "status", "phase": "retrieving" | "expanding_graph" | "synthesizing"}
          {"type": "token",  "text": "<delta>"}
          {"type": "result", "answer": "...", "citations": [...], ...}
        Agent activity events are also emitted for the UI progress panel.
        """
        from advandeb_kb.services.llm_providers import get_provider
        from advandeb_kb.services.llm_providers.base import ProviderError

        if not max_tokens:
            max_tokens = settings.CHAT_ANSWER_MAX_TOKENS

        # Resolve API key
        if direct_api_key:
            api_key = direct_api_key
        else:
            api_key = await self.keys.get_credential(user_id, key_id or "")
            if not api_key:
                raise ByokSynthesisError(
                    "The selected LLM credential could not be found or decrypted."
                )

        sid = await self._ensure_session(session_id, user_id, query)
        history = await self._load_memory(sid)
        await self._store_message(sid, role="user", content=query)

        # ── Conversational short-circuit ───────────────────────────────────────
        # Skip the full KB pipeline for greetings / acks / meta questions.
        if _is_conversational(query):
            async for event in self._conversational_stream(
                query=query,
                session_id=sid,
                provider=provider,
                api_key=api_key,
                model=model,
                system_prompt=system_prompt,
                history=history,
                max_tokens=max_tokens,
            ):
                yield event
            return

        # ── Classify exploration depth ─────────────────────────────────────────
        tier = _classify_query(query)
        params = _TIER_PARAMS[tier]
        yield {
            "type": "agent_activity",
            "agent": "retrieval_agent",
            "status": "working",
            "task": f"[{tier.value}] hybrid_search + stylized_facts (top_k={params.top_k})",
        }

        # ── Phase 1: Fan-out retrieval ─────────────────────────────────────────
        yield {"type": "status", "phase": "retrieving"}
        chunks, direct_sfs = await self._retrieve_fan_out(query, params.top_k)

        yield {
            "type": "agent_activity",
            "agent": "retrieval_agent",
            "status": "completed",
            "task": f"Retrieved {len(chunks)} chunks, {len(direct_sfs)} stylized facts",
        }

        if not chunks and not direct_sfs:
            answer = (
                "I could not find any relevant sources in the knowledge base for "
                "that question."
            )
            message_id = await self._store_message(
                sid, role="assistant", content=answer, evidence_mode="local"
            )
            await self._touch_session(sid)
            yield {
                "type": "result",
                "answer": answer,
                "citations": [],
                "evidence_mode": "local",
                "session_id": sid,
                "message_id": message_id,
                "suggested_questions": [],
            }
            return

        # ── Phase 2: Graph augmentation (tier-conditional) ────────────────────
        direct_sfs_normalised = [
            {"_key": sf.get("id", ""), "statement": sf.get("statement", ""),
             "category": sf.get("category", ""), "sf_number": sf.get("sf_number")}
            for sf in direct_sfs
        ]

        if params.expand_graph:
            yield {"type": "status", "phase": "expanding_graph"}
            yield {
                "type": "agent_activity",
                "agent": "graph_explorer",
                "status": "working",
                "task": "expand_context",
            }
            graph_result = await self._graph_augment(chunks)

            # Merge direct SF results
            existing_sfs = graph_result.get("stylized_facts", [])
            existing_sf_keys = {sf.get("_key") or sf.get("id", "") for sf in existing_sfs}
            graph_result["stylized_facts"] = existing_sfs + [
                sf for sf in direct_sfs_normalised if sf["_key"] not in existing_sf_keys
            ]

            facts_count = len(graph_result.get("facts", []))
            sfs_count = len(graph_result.get("stylized_facts", []))
            yield {
                "type": "agent_activity",
                "agent": "graph_explorer",
                "status": "completed",
                "task": f"Graph: {facts_count} facts, {sfs_count} stylized facts",
            }
        else:
            # Skip graph expansion for light tiers — use SFs from retrieval only
            graph_result = {"facts": [], "stylized_facts": direct_sfs_normalised, "nodes": []}
            facts_count = 0
            sfs_count = len(direct_sfs_normalised)

        # ── Phase 3: Build evidence registry ──────────────────────────────────
        registry = EvidenceRegistry.from_retrieval(chunks, graph_result)

        # ── Phase 4: Synthesis ─────────────────────────────────────────────────
        yield {"type": "status", "phase": "synthesizing"}

        chosen_model = model or _default_model(provider)
        provider_instance = get_provider(provider, api_key=api_key)

        full_text = ""
        citations: List[Dict[str, Any]] = []
        evidence_mode = "local"

        try:
            if provider_instance.supports_tools:
                # Agentic mode: LLM calls search tools and iterates.
                yield {
                    "type": "agent_activity",
                    "agent": "chatbot",
                    "status": "working",
                    "task": f"[{tier.value}] agentic reasoning (max {params.max_steps} steps)…",
                }
                async for event in self._agentic_stream(
                    provider=provider_instance,
                    model=chosen_model,
                    query=query,
                    registry=registry,
                    history=history,
                    system_prompt=system_prompt,
                    max_tokens=max_tokens,
                    tier_params=params,
                    extra_tools=(
                        _ANALYTICS_TOOLS
                        if tier == ExplorationTier.ANALYTICAL
                        else None
                    ),
                ):
                    if event.get("type") == "token":
                        full_text += event.get("text", "")
                        yield event
                    elif event.get("type") == "agent_activity":
                        yield event
                    elif event.get("type") == "_done":
                        full_text = event.get("full_text", full_text)
                        registry = event.get("registry", registry)
            else:
                # Single-pass KAG: build rich prompt from registry and call LLM once.
                yield {
                    "type": "agent_activity",
                    "agent": "chatbot",
                    "status": "working",
                    "task": "Synthesizing answer from evidence…",
                }
                messages = self._build_messages_kag(
                    query, registry, history, system_prompt=system_prompt or params.system_prompt
                )
                call_kwargs: Dict[str, Any] = {
                    "model": chosen_model,
                    "messages": messages,
                    "temperature": 0.3,
                }
                if max_tokens:
                    call_kwargs["max_tokens"] = max_tokens

                async for chunk in provider_instance._stream(call_kwargs):
                    try:
                        delta = (
                            (chunk.get("choices") or [{}])[0]
                            .get("delta", {})
                            .get("content") or ""
                        )
                    except (IndexError, AttributeError):
                        delta = ""
                    if delta:
                        full_text += delta
                        yield {"type": "token", "text": delta}

        except ProviderError as exc:
            raise ByokSynthesisError(f"{provider} request failed: {exc.message}") from None
        except ByokSynthesisError:
            raise
        except Exception as exc:
            raise ByokSynthesisError(
                f"{provider} request failed: {type(exc).__name__}"
            ) from None
        finally:
            try:
                await provider_instance.close()
            except Exception:
                pass

        if not full_text:
            full_text = "The model returned an empty response."

        # Extract citations from the final text using the registry
        citation_refs = registry.extract_citations(full_text)
        if citation_refs:
            citations = [c.model_dump() for c in citation_refs]
        else:
            # Fallback: numeric-only extraction (for providers that use plain [N])
            citations = self._extract_citations_fallback(full_text, chunks)

        citations = await ProvenanceService().enrich_citations(citations)

        message_id = await self._store_message(
            sid, role="assistant", content=full_text,
            citations=citations, evidence_mode=evidence_mode,
        )
        await self._save_memory_turn(sid, query, full_text, citations)
        await self._touch_session(sid)

        logger.info(
            "byok_chat: session=%s user=%s provider=%s model=%s chunks=%d "
            "facts=%d sfs=%d cited=%d",
            sid, user_id, provider, chosen_model,
            len(chunks), facts_count, sfs_count, len(citations),
        )

        # Kick off follow-up suggestions in background (non-blocking)
        suggested_questions = await self._suggest_followups_fast(query, full_text)

        yield {
            "type": "agent_activity",
            "agent": "chatbot",
            "status": "completed",
            "task": f"Answer ready — {len(citations)} source(s) cited",
        }
        yield {
            "type": "result",
            "answer": full_text,
            "citations": citations,
            "evidence_mode": evidence_mode,
            "session_id": sid,
            "message_id": message_id,
            "suggested_questions": suggested_questions,
        }

    # ------------------------------------------------------- conversational path

    async def _conversational_stream(
        self,
        *,
        query: str,
        session_id: str,
        provider: str,
        api_key: str,
        model: Optional[str],
        system_prompt: Optional[str],
        history: List[Dict[str, str]],
        max_tokens: int,
    ):
        """Direct LLM call for conversational messages — no KB retrieval or graph work."""
        from advandeb_kb.services.llm_providers import get_provider
        from advandeb_kb.services.llm_providers.base import ProviderError

        yield {
            "type": "agent_activity",
            "agent": "chatbot",
            "status": "working",
            "task": "responding…",
        }

        chosen_model = model or _default_model(provider)
        provider_instance = get_provider(provider, api_key=api_key)

        effective_system = _SYSTEM_PROMPT_CONVERSATIONAL
        if system_prompt and system_prompt.strip():
            effective_system += f"\n\nAdditional instructions: {system_prompt.strip()}"

        history_messages = [{"role": t["role"], "content": t["content"]} for t in history]
        messages: List[Dict[str, Any]] = (
            [{"role": "system", "content": effective_system}]
            + history_messages
            + [{"role": "user", "content": query}]
        )
        call_kwargs: Dict[str, Any] = {
            "model": chosen_model,
            "messages": messages,
            "temperature": 0.7,
            "max_tokens": min(max_tokens, 512),
        }

        full_text = ""
        try:
            async for chunk in provider_instance._stream(call_kwargs):
                try:
                    delta = (
                        (chunk.get("choices") or [{}])[0]
                        .get("delta", {})
                        .get("content") or ""
                    )
                except (IndexError, AttributeError):
                    delta = ""
                if delta:
                    full_text += delta
                    yield {"type": "token", "text": delta}
        except ProviderError as exc:
            raise ByokSynthesisError(f"{provider} request failed: {exc.message}") from None
        except ByokSynthesisError:
            raise
        except Exception as exc:
            raise ByokSynthesisError(
                f"{provider} request failed: {type(exc).__name__}"
            ) from None
        finally:
            try:
                await provider_instance.close()
            except Exception:
                pass

        if not full_text:
            full_text = (
                "Hi! I'm AdvanDEB's research assistant, specialising in Dynamic Energy "
                "Budget theory. Ask me anything about DEB, bioenergetics, or the knowledge base."
            )

        message_id = await self._store_message(
            session_id, role="assistant", content=full_text, evidence_mode="none"
        )
        await self._save_memory_turn(session_id, query, full_text, [])
        await self._touch_session(session_id)

        yield {
            "type": "agent_activity",
            "agent": "chatbot",
            "status": "completed",
            "task": "Response ready",
        }
        yield {
            "type": "result",
            "answer": full_text,
            "citations": [],
            "evidence_mode": "none",
            "session_id": session_id,
            "message_id": message_id,
            "suggested_questions": [],
        }

    # --------------------------------------------------------------- retrieval

    async def _retrieve(self, query: str, top_k: int) -> List[Dict[str, Any]]:
        """Hybrid search via retrieval_agent MCP tool."""
        from app.core.config import settings as app_settings

        retrieval_ws = getattr(app_settings, "RETRIEVAL_AGENT_WS", "ws://localhost:8081")
        mcp = MCPClient(base_url=retrieval_ws.replace("ws://", "http://"))
        try:
            result = await mcp.call_tool(
                tool_name="hybrid_search",
                arguments={"query": query, "top_k": top_k},
            )
        except Exception as exc:
            raise ByokSynthesisError(f"Retrieval failed: {exc}") from None
        return result.get("chunks", []) or []

    async def _retrieve_fan_out(
        self, query: str, top_k: int
    ) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        """Parallel: hybrid_search + direct ArangoDB stylized-facts search."""

        async def _sf_search() -> List[Dict[str, Any]]:
            try:
                from app.core.database import get_arango_db
                from advandeb_kb.services.graph_expansion_service import (
                    GraphExpansionService,
                )
                loop = asyncio.get_running_loop()
                arango = get_arango_db()
                svc = GraphExpansionService(arango)
                return await loop.run_in_executor(
                    None, svc.search_stylized_facts, query, 10
                )
            except Exception as exc:
                logger.debug("byok: SF direct search skipped: %s", exc)
                return []

        results = await asyncio.gather(
            self._retrieve(query, top_k),
            _sf_search(),
            return_exceptions=True,
        )
        chunks = results[0] if not isinstance(results[0], Exception) else []
        sfs = results[1] if not isinstance(results[1], Exception) else []
        return chunks, sfs  # type: ignore[return-value]

    async def _graph_augment(self, chunks: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Expand seed chunks through ArangoDB knowledge graph."""
        chunk_ids = [
            c.get("chunk_id") or c.get("id") or c.get("_key")
            for c in chunks[:15]
            if c.get("chunk_id") or c.get("id") or c.get("_key")
        ]
        if not chunk_ids:
            return {}
        try:
            from app.core.database import get_arango_db
            from advandeb_kb.services.graph_expansion_service import GraphExpansionService

            loop = asyncio.get_running_loop()
            arango = get_arango_db()
            svc = GraphExpansionService(arango)
            return await loop.run_in_executor(
                None, svc.expand_from_chunks, chunk_ids, 2
            )
        except Exception as exc:
            logger.debug("byok: graph augment skipped: %s", exc)
            return {}

    # --------------------------------------------------------------- tool execution

    async def _execute_tool(
        self, tool_name: str, tool_input: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Dispatch a tool call from the LLM and return the result as a dict."""
        if tool_name == "search_knowledge_base":
            q = tool_input.get("query", "")
            k = min(int(tool_input.get("top_k", 15)), 30)
            try:
                chunks = await self._retrieve(q, k)
            except ByokSynthesisError:
                return {"chunks": [], "count": 0}
            return {
                "chunks": [
                    {
                        "text": c.get("text", "")[:500],
                        "chunk_id": c.get("chunk_id") or c.get("id", ""),
                        "document_id": (c.get("metadata") or {}).get("document_id", ""),
                    }
                    for c in chunks
                ],
                "count": len(chunks),
            }

        if tool_name == "search_stylized_facts":
            q = tool_input.get("query", "")
            lim = min(int(tool_input.get("limit", 10)), 20)
            try:
                from app.core.database import get_arango_db
                from advandeb_kb.services.graph_expansion_service import GraphExpansionService

                loop = asyncio.get_running_loop()
                arango = get_arango_db()
                svc = GraphExpansionService(arango)
                facts = await loop.run_in_executor(
                    None, svc.search_stylized_facts, q, lim
                )
                return {"facts": facts, "count": len(facts)}
            except Exception as exc:
                return {"facts": [], "count": 0, "error": str(exc)}

        if tool_name == "get_claim_consensus":
            claim = tool_input.get("claim", "")
            try:
                from app.core.database import get_arango_db
                from advandeb_kb.services.graph_expansion_service import GraphExpansionService

                loop = asyncio.get_running_loop()
                arango = get_arango_db()
                svc = GraphExpansionService(arango)
                rows = await loop.run_in_executor(
                    None, svc.claim_consensus, claim, 3, 30
                )
                return {"consensus": rows, "count": len(rows)}
            except Exception as exc:
                return {"consensus": [], "count": 0, "error": str(exc)}

        # ── Analytics tools (ANALYTICAL tier) ────────────────────────────────
        if tool_name in (
            "graph_stats", "analyze_sf_support", "explore_graph_node", "find_taxa_connections",
            "sf_category_breakdown", "find_contested_facts", "citation_influence",
            "sf_taxon_coverage", "taxon_subtree_stats",
        ):
            try:
                from app.core.database import get_arango_db
                from app.services.graph_analytics_service import GraphAnalyticsService

                loop = asyncio.get_running_loop()
                arango = get_arango_db()
                svc = GraphAnalyticsService(arango)

                if tool_name == "graph_stats":
                    include_dd = bool(tool_input.get("include_degree_dist", False))
                    result = await loop.run_in_executor(None, svc.graph_stats, include_dd)
                    return result

                if tool_name == "analyze_sf_support":
                    result = await loop.run_in_executor(
                        None,
                        svc.analyze_sf_support,
                        tool_input.get("category", ""),
                        tool_input.get("sort_by", "support_count"),
                        int(tool_input.get("limit", 10)),
                    )
                    return {"facts": result, "count": len(result)}

                if tool_name == "explore_graph_node":
                    result = await loop.run_in_executor(
                        None,
                        svc.explore_graph_node,
                        tool_input.get("query", ""),
                        tool_input.get("node_type", "auto"),
                        int(tool_input.get("depth", 1)),
                    )
                    return result

                if tool_name == "find_taxa_connections":
                    result = await loop.run_in_executor(
                        None,
                        svc.find_taxa_connections,
                        tool_input.get("concept", ""),
                        tool_input.get("rank", "species"),
                        int(tool_input.get("limit", 15)),
                    )
                    return result

                if tool_name == "sf_category_breakdown":
                    result = await loop.run_in_executor(None, svc.sf_category_breakdown)
                    return {"categories": result, "count": len(result)}

                if tool_name == "find_contested_facts":
                    result = await loop.run_in_executor(
                        None,
                        svc.find_contested_facts,
                        int(tool_input.get("min_total", 8)),
                        float(tool_input.get("min_opposition_ratio", 0.10)),
                        int(tool_input.get("limit", 10)),
                    )
                    return {"facts": result, "count": len(result)}

                if tool_name == "citation_influence":
                    result = await loop.run_in_executor(
                        None,
                        svc.citation_influence,
                        int(tool_input.get("min_citations", 1)),
                        int(tool_input.get("limit", 10)),
                    )
                    return {"documents": result, "count": len(result)}

                if tool_name == "sf_taxon_coverage":
                    result = await loop.run_in_executor(
                        None,
                        svc.sf_taxon_coverage,
                        tool_input.get("query", ""),
                        tool_input.get("rank", "any"),
                        int(tool_input.get("limit", 20)),
                    )
                    return result

                if tool_name == "taxon_subtree_stats":
                    result = await loop.run_in_executor(
                        None,
                        svc.taxon_subtree_stats,
                        tool_input.get("group_name", ""),
                        tool_input.get("rank", "species"),
                        int(tool_input.get("limit", 20)),
                    )
                    return result

            except Exception as exc:
                return {"error": f"{tool_name} failed: {exc}"}

        return {"error": f"Unknown tool: {tool_name}"}

    @staticmethod
    def _tool_result_to_text(tool_name: str, result: Dict[str, Any]) -> str:
        """Render a tool result as human-readable text for the LLM."""
        if tool_name == "search_knowledge_base":
            chunks = result.get("chunks", [])
            if not chunks:
                return "No relevant chunks found."
            lines = [f"Found {len(chunks)} chunk(s):"]
            for i, c in enumerate(chunks[:15]):
                lines.append(f"  [{i+1}] {c.get('text', '')[:400]}")
            return "\n".join(lines)

        if tool_name == "search_stylized_facts":
            facts = result.get("facts", [])
            if not facts:
                return "No matching stylized facts found."
            lines = [f"Found {len(facts)} stylized fact(s):"]
            for f in facts[:12]:
                lines.append(f"  • {f.get('statement', '')[:300]}")
            return "\n".join(lines)

        if tool_name == "get_claim_consensus":
            rows = result.get("consensus", [])
            if not rows:
                return "No consensus data found for this claim."
            lines: List[str] = []
            for row in rows[:3]:
                sf = row.get("stylized_fact", "")
                n_sup = row.get("support_count", 0)
                n_opp = row.get("oppose_count", 0)
                lines.append(
                    f"Closest stylized fact: '{sf}'\n"
                    f"  Supporting refs: {n_sup}, Opposing refs: {n_opp}"
                )
                for item in (row.get("supports") or [])[:3]:
                    doc = item.get("document") or {}
                    lines.append(
                        f"    SUPPORT: {item.get('fact', '')[:200]} "
                        f"({doc.get('title', 'unknown')} {doc.get('year', '')})"
                    )
                for item in (row.get("opposes") or [])[:2]:
                    doc = item.get("document") or {}
                    lines.append(
                        f"    OPPOSE: {item.get('fact', '')[:200]} "
                        f"({doc.get('title', 'unknown')} {doc.get('year', '')})"
                    )
            return "\n".join(lines)

        if tool_name == "graph_stats":
            nodes = result.get("nodes", {})
            edges = result.get("edges", {})
            lines = [
                "=== Knowledge Graph Statistics ===",
                f"Nodes: documents={nodes.get('documents',0):,}  facts={nodes.get('facts',0):,}  "
                f"stylized_facts={nodes.get('stylized_facts',0):,}  taxa={nodes.get('taxa',0):,}",
                f"Edges: sf_support={edges.get('sf_support',0):,}  citations={edges.get('citations',0):,}  "
                f"knowledge_graph={edges.get('knowledge_graph',0):,}  taxonomical={edges.get('taxonomical',0):,}",
            ]
            if result.get("top_10_sf_by_edge_count"):
                lines.append("Top-10 SF by edge count:")
                for item in result["top_10_sf_by_edge_count"]:
                    lines.append(f"  SF{item['sf_number']}: {item['total_edges']} edges — {item['statement_preview'][:80]}")
            return "\n".join(lines)

        if tool_name == "analyze_sf_support":
            facts = result.get("facts", [])
            if not facts:
                return "No stylized facts found matching the filter criteria."
            lines = [f"=== SF Evidence Analysis ({len(facts)} results) ==="]
            for f in facts:
                ratio_pct = round(f.get("support_ratio", 0) * 100, 1)
                lines.append(
                    f"SF{f['sf_number']} [{f.get('category','?')}]  "
                    f"support={f['support_count']}  oppose={f['oppose_count']}  "
                    f"net={f['net_support']}  ratio={ratio_pct}%"
                )
                lines.append(f"  Statement: {f['statement'][:200]}")
            return "\n".join(lines)

        if tool_name == "explore_graph_node":
            if not result.get("found"):
                return f"No graph node found matching: {result.get('query','')}"
            lines = ["=== Graph Node Exploration ==="]
            for node in result.get("nodes", []):
                ntype = node.get("node_type", "unknown")
                if ntype == "stylized_fact":
                    lines.append(f"Stylized Fact SF{node['sf_number']} [{node['category']}]")
                    lines.append(f"  Statement: {node['statement']}")
                    lines.append(f"  Support edges: {node['support_count']}  Oppose: {node['oppose_count']}  Net: {node['net_support']}")
                    for s in node.get("sample_supporting_facts", [])[:3]:
                        lines.append(f"  SUPPORT (conf={s.get('confidence','?')}): {s.get('fact_preview','')[:150]}")
                    for s in node.get("sample_opposing_facts", [])[:2]:
                        lines.append(f"  OPPOSE  (conf={s.get('confidence','?')}): {s.get('fact_preview','')[:150]}")
                elif ntype == "taxon":
                    cn = ", ".join(node.get("common_names", [])[:2]) or "—"
                    lines.append(f"Taxon: {node['name']} ({node['rank']}) common names: {cn}")
                    lines.append(f"  Documents studying this taxon: {node['document_count']}")
                    for d in node.get("sample_studying_documents", [])[:4]:
                        lines.append(f"  • {d.get('title','?')[:100]} ({d.get('year','?')})")
                elif ntype == "document":
                    lines.append(f"Document: {node['title']} ({node.get('year','?')})")
                    lines.append(f"  DOI: {node.get('doi','—')}  Facts extracted: {node.get('fact_count',0)}")
                    if node.get("taxa_studied"):
                        lines.append(f"  Taxa studied: {', '.join(t['name'] for t in node['taxa_studied'][:5])}")
                    for d in node.get("cites", [])[:3]:
                        lines.append(f"  Cites: {d.get('title','?')[:80]}")
                    for d in node.get("cited_by", [])[:3]:
                        lines.append(f"  Cited by: {d.get('title','?')[:80]}")
            return "\n".join(lines)

        if tool_name == "find_taxa_connections":
            taxa = result.get("taxa", [])
            total = result.get("total_found", 0)
            concept = result.get("concept", "")
            if not taxa:
                return f"No taxa found connected to concept: {concept}"
            lines = [f"=== Taxa connected to '{concept}' (showing {len(taxa)} of {total}) ==="]
            for t in taxa:
                cn = (t.get("common_names") or [])
                cn_str = f" ({', '.join(cn[:2])})" if cn else ""
                lines.append(f"  • {t['name']}{cn_str} [{t.get('rank','?')}]")
            return "\n".join(lines)

        if tool_name == "sf_category_breakdown":
            cats = result.get("categories", [])
            if not cats:
                return "No category data available."
            lines = [f"=== SF Category Breakdown ({len(cats)} categories) ==="]
            for c in cats:
                contested_pct = round(c.get("contested_fraction", 0) * 100, 1)
                lines.append(
                    f"{c.get('category','?')}: "
                    f"{c.get('sf_count',0)} SFs  "
                    f"support={c.get('total_support',0)}  oppose={c.get('total_oppose',0)}  "
                    f"avg={c.get('avg_support_per_sf',0)}  contested={contested_pct}%"
                )
                best = c.get("best_supported_sf")
                if best:
                    lines.append(
                        f"  Best: SF{best['sf_number']} ({best['support_count']} support) "
                        f"— {best.get('statement_preview','')[:100]}"
                    )
            return "\n".join(lines)

        if tool_name == "find_contested_facts":
            facts = result.get("facts", [])
            if not facts:
                return "No contested facts found matching the criteria."
            lines = [f"=== Most Contested Stylized Facts ({len(facts)} results) ==="]
            for f in facts:
                opp_pct = round(f.get("opposition_ratio", 0) * 100, 1)
                lines.append(
                    f"SF{f['sf_number']} [{f.get('category','?')}]  "
                    f"support={f['support_count']}  oppose={f['oppose_count']}  "
                    f"opposition={opp_pct}%"
                )
                lines.append(f"  Statement: {f['statement'][:200]}")
                for opp in (f.get("sample_opposing_facts") or [])[:2]:
                    lines.append(f"  OPPOSE (conf={opp.get('confidence','?')}): {opp.get('fact_preview','')[:130]}")
            return "\n".join(lines)

        if tool_name == "citation_influence":
            docs = result.get("documents", [])
            if not docs:
                return "No citation data found."
            lines = [f"=== Most Influential Documents by Citation In-Degree ({len(docs)} results) ==="]
            for d in docs:
                authors = d.get("authors") or []
                auth_str = ", ".join(authors[:2]) + (" et al." if len(authors) > 2 else "")
                lines.append(
                    f"[{d.get('in_degree',0)} citations in]  {d.get('title','?')[:120]}"
                )
                lines.append(
                    f"  {auth_str} ({d.get('year','?')})  DOI: {d.get('doi','—')}  "
                    f"facts extracted: {d.get('fact_count',0)}"
                )
            return "\n".join(lines)

        if tool_name == "sf_taxon_coverage":
            if not result.get("found"):
                return f"No stylized fact found matching: {result.get('query','')}"
            taxa = result.get("taxa", [])
            lines = [
                f"=== Taxon Coverage for SF{result.get('sf_number','?')} ===",
                f"Statement: {result.get('statement','')[:200]}",
                f"Supporting docs: {result.get('supporting_doc_count',0)}  "
                f"Taxa linked (all ranks): {result.get('taxa_count',0)}  "
                f"Shown (rank={result.get('filtered_rank','any')}): {len(taxa)}",
            ]
            if taxa:
                for t in taxa:
                    cn = (t.get("common_names") or [])
                    cn_str = f" ({', '.join(cn[:2])})" if cn else ""
                    lines.append(f"  • {t['name']}{cn_str} [{t.get('rank','?')}]")
            else:
                lines.append("  (No taxa linked in knowledge graph for these supporting documents.)")
            return "\n".join(lines)

        if tool_name == "taxon_subtree_stats":
            if not result.get("found"):
                return f"Taxonomic group not found: {result.get('group','')}"
            desc = result.get("descendants", [])
            with_docs = [d for d in desc if d.get("doc_count", 0) > 0]
            lines = [
                f"=== Taxonomic Subtree: {result.get('group','')} ({result.get('group_rank','?')}) ===",
                f"Target rank: {result.get('target_rank','species')}  "
                f"Total found: {len(desc)}  With KB documents: {len(with_docs)}",
            ]
            for d in desc:
                cn = (d.get("common_names") or [])
                cn_str = f" ({', '.join(cn[:2])})" if cn else ""
                kb_tag = f" [{d['doc_count']} KB doc(s)]" if d.get("doc_count", 0) > 0 else ""
                lines.append(f"  • {d['name']}{cn_str}{kb_tag}")
            if not desc:
                lines.append("  (No descendants found at this rank within the traversal cap.)")
            return "\n".join(lines)

        return json.dumps(result)[:1000]

    # --------------------------------------------------------------- agentic loop

    async def _agentic_stream(
        self,
        *,
        provider,
        model: str,
        query: str,
        registry: EvidenceRegistry,
        history: List[Dict[str, str]],
        system_prompt: Optional[str],
        max_tokens: int,
        max_steps: int = 5,
        tier_params: Optional["_TierParams"] = None,
        extra_tools: Optional[List[Dict[str, Any]]] = None,
    ) -> AsyncIterator[Dict[str, Any]]:
        """Multi-step tool-calling loop.  Yields agent_activity and token events.

        The loop ends either when the LLM returns a text answer (no tool calls)
        or after ``max_steps`` tool-call rounds.  On exit yields a single
        ``{"type": "_done", "full_text": ..., "registry": ...}`` sentinel for
        the caller to finalise citations.
        """
        from advandeb_kb.services.llm_providers.base import ProviderError

        # Use tier-specific system prompt and step budget if provided
        effective_steps = tier_params.max_steps if tier_params else max_steps
        base_system = tier_params.system_prompt if tier_params else _SYSTEM_PROMPT_AGENT
        effective_system = base_system
        if system_prompt and system_prompt.strip():
            effective_system += f"\n\nAdditional instructions: {system_prompt.strip()}"

        # Build initial evidence block
        evidence_block = registry.render_observation_block()

        # Conversation so far (last N turns for context)
        history_messages: List[Dict[str, Any]] = []
        for turn in history:
            history_messages.append({"role": turn["role"], "content": turn["content"]})

        # User turn: evidence block + tier-specific guidance
        guidance = tier_params.user_guidance if tier_params else (
            "Answer the question using the evidence above. "
            "You may call search tools to find additional evidence if needed. "
            "When ready, write your final comprehensive answer with inline citation markers."
        )
        user_content = (
            f"INITIAL EVIDENCE (automatically retrieved):\n"
            f"{evidence_block}\n\n"
            f"USER QUESTION: {query}\n\n"
            f"{guidance}"
        )

        messages: List[Dict[str, Any]] = (
            [{"role": "system", "content": effective_system}]
            + history_messages
            + [{"role": "user", "content": user_content}]
        )

        full_text = ""
        active_tools = _CHAT_TOOLS + (extra_tools or [])

        for step in range(effective_steps):
            try:
                resp = await provider.chat_with_tools(
                    model=model,
                    messages=messages,
                    tools=active_tools,
                    max_tokens=max_tokens,
                    temperature=0.3,
                )
            except ProviderError as exc:
                raise ByokSynthesisError(
                    f"Agentic tool call failed: {exc.message}"
                ) from None
            except Exception as exc:
                raise ByokSynthesisError(
                    f"Agentic tool call failed: {type(exc).__name__}"
                ) from None

            tool_calls = resp.get("tool_calls") or []

            if not tool_calls or resp.get("finish_reason") != "tool_calls":
                # LLM is done with tools — stream the final answer so the browser
                # sees text appearing progressively (like Claude.ai / ChatGPT).
                # Any partial text the LLM produced alongside the "stop" signal is
                # included in the conversation so the streaming call has full context.
                if resp.get("content"):
                    messages.append({"role": "assistant", "content": resp.get("content", "")})
                    # Append instruction so the model writes out its final answer
                    messages.append({
                        "role": "user",
                        "content": (
                            "Thank you for the analysis. Now write your final comprehensive "
                            "answer with inline citations for the user."
                        ),
                    })
                async for delta in provider.stream_final_answer(
                    model=model,
                    messages=messages,
                    max_tokens=max_tokens,
                    temperature=0.3,
                ):
                    full_text += delta
                    yield {"type": "token", "text": delta}
                break

            # Emit tool calls as agent activity
            for tc in tool_calls:
                yield {
                    "type": "agent_activity",
                    "agent": "chatbot",
                    "status": "working",
                    "task": tc["name"],
                    "args": tc.get("input", {}),
                    "step": step + 1,
                }

            # Add the assistant message with tool calls to history
            messages.append({
                "role": "assistant",
                "content": resp.get("content", ""),
                "tool_calls": tool_calls,
            })

            # Execute each tool and add results
            for tc in tool_calls:
                tool_result = await self._execute_tool(tc["name"], tc.get("input", {}))
                result_text = self._tool_result_to_text(tc["name"], tool_result)

                yield {
                    "type": "agent_activity",
                    "agent": "chatbot",
                    "status": "completed",
                    "task": tc["name"],
                    "result": result_text[:200],
                    "step": step + 1,
                }

                messages.append({
                    "role": "tool",
                    "tool_call_id": tc["id"],
                    "content": result_text,
                })
        else:
            # Exceeded max_steps — synthesize a final answer from everything gathered.
            last_content = resp.get("content", "") if resp else ""  # type: ignore[possibly-undefined]
            if last_content:
                messages.append({"role": "assistant", "content": last_content})
            messages.append({
                "role": "user",
                "content": (
                    "Please write your final comprehensive answer with inline citations "
                    "based on all the evidence gathered above."
                ),
            })
            async for delta in provider.stream_final_answer(
                model=model, messages=messages, max_tokens=max_tokens, temperature=0.3
            ):
                full_text += delta
                yield {"type": "token", "text": delta}
            if not full_text:
                full_text = (
                    "I searched the knowledge base exhaustively but could not "
                    "produce a final answer within the step limit."
                )

        if not full_text:
            full_text = "The model returned an empty response."

        yield {"type": "_done", "full_text": full_text, "registry": registry}

    # ------------------------------------------------------------ prompt build

    def _build_messages_kag(
        self,
        query: str,
        registry: EvidenceRegistry,
        history: List[Dict[str, str]],
        *,
        system_prompt: Optional[str] = None,
    ) -> List[Dict[str, str]]:
        """Build a prompt using the full EvidenceRegistry observation block."""
        evidence_block = registry.render_observation_block()
        user_content = (
            f"EVIDENCE:\n{evidence_block}\n\n"
            f"Question: {query}\n\n"
            "Answer (with inline citation markers):"
        )
        effective_system = _SYSTEM_PROMPT
        if system_prompt and system_prompt.strip():
            effective_system += f"\n\nAdditional instructions: {system_prompt.strip()}"

        messages: List[Dict[str, str]] = [{"role": "system", "content": effective_system}]
        for turn in history:
            messages.append({"role": turn["role"], "content": turn["content"]})
        messages.append({"role": "user", "content": user_content})
        return messages

    @staticmethod
    def _default_model(provider: str) -> str:
        from advandeb_kb.services.llm_providers import PROVIDERS
        cls = PROVIDERS.get(provider)
        return getattr(cls, "default_model", "") if cls else ""

    # -------------------------------------------------------- citation fallback

    def _extract_citations_fallback(
        self, answer_text: str, chunks: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """Numeric [N] citation extraction — used when registry markers weren't cited."""
        from advandeb_kb.models.chat import (
            CitationRef,
            make_citation_id,
            strip_collection_prefix,
        )
        cited = {int(m) for m in re.findall(r"\[(\d+)\]", answer_text)}
        citations: List[Dict[str, Any]] = []
        for num in sorted(cited):
            idx = num - 1
            if not (0 <= idx < len(chunks)):
                continue
            chunk = chunks[idx]
            meta = chunk.get("metadata", {}) or {}
            chunk_id = strip_collection_prefix(
                str(chunk.get("chunk_id") or chunk.get("id") or chunk.get("_key") or "")
            )
            citations.append(
                CitationRef(
                    citation_id=make_citation_id("chunk", chunk_id),
                    marker=str(num),
                    source_type="chunk",
                    document_id=meta.get("document_id") or chunk.get("document_id") or None,
                    chunk_id=chunk_id or None,
                    evidence_text=chunk.get("text", "")[:200],
                ).model_dump()
            )
        return citations

    # --------------------------------------------------------------- follow-ups

    async def _suggest_followups_fast(self, query: str, answer: str) -> List[str]:
        """Quick follow-up question generation — best-effort, 10s timeout."""
        import httpx

        prompt = (
            "Based on the question and answer below, suggest exactly 3 short, "
            "specific follow-up questions a researcher might ask next.\n"
            f"Question: {query}\nAnswer (excerpt): {answer[:400]}\n"
            "Output ONLY a numbered list:\n1. ...\n2. ...\n3. ..."
        )
        try:
            tokens: List[str] = []
            async with httpx.AsyncClient(timeout=10.0) as client:
                async with client.stream(
                    "POST",
                    f"{settings.OLLAMA_BASE_URL}/api/chat",
                    json={
                        "model": settings.CHAT_FOLLOWUP_MODEL,
                        "messages": [{"role": "user", "content": prompt}],
                        "stream": True,
                        "options": {"num_predict": 150, "temperature": 0.6,
                                    "num_ctx": settings.CHAT_FOLLOWUP_NUM_CTX},
                    },
                ) as resp:
                    resp.raise_for_status()
                    async for line in resp.aiter_lines():
                        if not line:
                            continue
                        try:
                            chunk = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        tok = chunk.get("message", {}).get("content", "")
                        if tok:
                            tokens.append(tok)
                        if chunk.get("done"):
                            break
            raw = re.sub(r"<think>.*?</think>", "", "".join(tokens), flags=re.DOTALL).strip()
            numbered = re.findall(r"^\s*\d+[.)]\s*(.+)", raw, re.MULTILINE)
            return [q.strip() for q in numbered[:3] if q.strip()]
        except Exception:
            return []

    # ----------------------------------------------------- session / messages

    async def _ensure_session(
        self, session_id: str, user_id: str, first_message: str
    ) -> str:
        if session_id and session_id not in ("", "new"):
            try:
                doc = await self.sessions.find_one(
                    {"_id": ObjectId(session_id), "user_id": user_id}
                )
                if doc:
                    return session_id
            except Exception:
                pass
        now = datetime.now(timezone.utc)
        result = await self.sessions.insert_one(
            {
                "user_id": user_id,
                "title": first_message[:80].strip(),
                "created_at": now,
                "updated_at": now,
            }
        )
        return str(result.inserted_id)

    async def _store_message(
        self,
        session_id: str,
        role: str,
        content: str,
        citations: Optional[list] = None,
        evidence_mode: Optional[str] = None,
        status: str = "done",
    ) -> str:
        now = datetime.now(timezone.utc)
        doc: Dict[str, Any] = {
            "session_id": session_id,
            "role": role,
            "content": content,
            "citations": citations or [],
            "thoughts": [],
            "status": status,
            "timestamp": now,
        }
        if evidence_mode is not None:
            doc["evidence_mode"] = evidence_mode
        result = await self.messages.insert_one(doc)
        return str(result.inserted_id)

    async def _touch_session(self, session_id: str) -> None:
        try:
            await self.sessions.update_one(
                {"_id": ObjectId(session_id)},
                {"$set": {"updated_at": datetime.now(timezone.utc)}},
            )
        except Exception as exc:
            logger.warning("byok_chat: touch_session failed: %s", exc)

    async def _load_memory(self, session_id: str) -> List[Dict[str, str]]:
        cursor = (
            self.memory.find({"session_id": session_id})
            .sort("turn_index", -1)
            .limit(_MEMORY_WINDOW)
        )
        turns = [doc async for doc in cursor]
        turns.reverse()
        history: List[Dict[str, str]] = []
        for turn in turns:
            history.append({"role": "user", "content": turn.get("user_message", "")})
            history.append({"role": "assistant", "content": turn.get("assistant_answer", "")})
        return history

    async def _save_memory_turn(
        self,
        session_id: str,
        user_message: str,
        assistant_answer: str,
        citations: list,
    ) -> None:
        count = await self.memory.count_documents({"session_id": session_id})
        await self.memory.insert_one(
            {
                "session_id": session_id,
                "turn_index": count,
                "user_message": user_message,
                "assistant_answer": assistant_answer,
                "tool_calls_made": [],
                "citations": citations,
                "created_at": datetime.now(timezone.utc),
            }
        )


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------

def _default_model(provider: str) -> str:
    from advandeb_kb.services.llm_providers import PROVIDERS
    cls = PROVIDERS.get(provider)
    return getattr(cls, "default_model", "") if cls else ""
