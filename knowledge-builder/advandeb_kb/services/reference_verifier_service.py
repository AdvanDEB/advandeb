"""
ReferenceVerifierService — verify that every factual claim in an answer is
backed by evidence in the registry, and decide whether an external-fallback
lookup is needed.

Uses CHAT_VERIFY_MODEL (default: deepseek-r1:latest) which is good at careful
reasoning over evidence vs. claim alignment.

Verification outputs
--------------------
VerificationResult.verdict  one of:
  "pass"          — all claims have registry support; answer ready to emit
  "warn"          — minor gaps but acceptable; answer emitted with a note
  "need_external" — thin evidence; ChatPipelineService should trigger external
                    fallback before constructing the final answer
  "reject"        — hard failure (hallucinated citations, uncited claims);
                    pipeline should regenerate or fall back to general knowledge

VerificationResult.uncited_claims   list[str]  — sentence-level claims with no marker
VerificationResult.invalid_markers  list[str]  — [N] markers not in registry
VerificationResult.suggestion       str        — short human-readable note to prepend
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Literal, Optional

import httpx

from advandeb_kb.config.settings import settings
from advandeb_kb.services.evidence_registry_service import EvidenceRegistry

logger = logging.getLogger(__name__)

Verdict = Literal["pass", "warn", "need_external", "reject"]

# ---------------------------------------------------------------------------
# Lightweight rule-based pre-check (no LLM needed)
# ---------------------------------------------------------------------------

# Factual sentence patterns that SHOULD carry a citation marker
_FACTUAL_PATTERNS = re.compile(
    r"\b("
    r"studies? (show|found|indicate|demonstrate|report|suggest)|"
    r"research (shows?|indicates?|demonstrates?)|"
    r"according to|"
    r"was (found|shown|demonstrated|reported)|"
    r"data (show|indicate|suggest)|"
    r"rate of|coefficient of|fraction of|value of|"
    r"equals?|is approximately|is estimated|ranges? from|"
    r"in [A-Z][a-z]+ et al\.|"
    r"\d+(\.\d+)?\s*(mg|g|kg|kJ|°C|mol|L|mL|μm|mm|cm|%)"
    r")",
    re.IGNORECASE,
)

_CITATION_MARKER_RE = re.compile(r"\[((?:SF|G)?\d+)\]")

# Minimum fraction of factual sentences that must carry a citation for "pass"
_MIN_CITATION_COVERAGE = 0.5


@dataclass
class VerificationResult:
    verdict: Verdict
    uncited_claims: list[str] = field(default_factory=list)
    invalid_markers: list[str] = field(default_factory=list)
    suggestion: str = ""
    evidence_mode: str = "local"


class ReferenceVerifierService:
    """
    Two-stage verifier:

    Stage 1 (fast, rule-based): check that markers in the answer all appear
    in the registry, and that factual sentences mostly carry a marker.

    Stage 2 (LLM-based, only when Stage 1 flags issues): ask the verify model
    to identify specific uncited claims and decide if external fallback is
    warranted.  Stage 2 is skipped when Stage 1 passes cleanly to keep
    latency low.
    """

    def __init__(self) -> None:
        self._ollama_url = settings.OLLAMA_BASE_URL
        self._model = settings.CHAT_VERIFY_MODEL
        self._num_ctx = settings.CHAT_VERIFY_NUM_CTX
        self._enable_external = settings.CHAT_ENABLE_EXTERNAL_FALLBACK

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def verify(
        self,
        query: str,
        answer: str,
        registry: EvidenceRegistry,
    ) -> VerificationResult:
        """
        Verify the answer against the registry.

        Returns a VerificationResult that the ChatPipelineService uses to
        decide next actions.
        """
        # ------ Stage 1: Rule-based checks ------
        stage1 = self._rule_check(answer, registry)

        if stage1.verdict == "pass":
            return stage1

        # ------ Stage 2: LLM-based check ------
        # Only invoke if Stage 1 found problems AND the registry is non-empty.
        # If registry is empty we already know it's a no-evidence situation.
        if not registry:
            return VerificationResult(
                verdict="need_external" if self._enable_external else "warn",
                suggestion=(
                    "Note: The local knowledge base returned no relevant sources. "
                    "The following is based on general bioenergetics knowledge."
                    if not self._enable_external
                    else ""
                ),
                evidence_mode=(
                    "local" if not self._enable_external else "external_fallback_labeled"
                ),
            )

        llm_result = await self._llm_check(query, answer, registry, stage1)
        return llm_result

    # ------------------------------------------------------------------
    # Stage 1: rule-based
    # ------------------------------------------------------------------

    def _rule_check(self, answer: str, registry: EvidenceRegistry) -> VerificationResult:
        """
        Fast structural check.  Never calls the LLM.
        """
        # 1. Find all markers used in the answer
        used_markers = set(_CITATION_MARKER_RE.findall(answer))

        # 2. Identify invalid markers (appear in answer but not in registry)
        valid_markers = {e.marker for e in registry.entries()}
        invalid = [m for m in used_markers if m not in valid_markers]

        if invalid:
            return VerificationResult(
                verdict="reject",
                invalid_markers=invalid,
                suggestion=(
                    "Answer contains citation markers that do not correspond to "
                    "retrieved evidence. Please regenerate."
                ),
            )

        # 3. Conversational / short answers — skip factual coverage check
        if len(answer) < 200:
            return VerificationResult(verdict="pass")

        # 4. Check factual sentence coverage
        sentences = _split_sentences(answer)
        factual = [s for s in sentences if _FACTUAL_PATTERNS.search(s)]
        cited = [s for s in factual if _CITATION_MARKER_RE.search(s)]

        if not factual:
            # No obviously-factual claims → pass
            return VerificationResult(verdict="pass")

        coverage = len(cited) / len(factual)
        uncited = [s for s in factual if not _CITATION_MARKER_RE.search(s)]

        if coverage >= _MIN_CITATION_COVERAGE:
            return VerificationResult(verdict="pass")

        # Coverage below threshold — flag for LLM check
        if not registry:
            verdict = "need_external" if self._enable_external else "warn"
        elif coverage < 0.2:
            verdict = "warn"
        else:
            verdict = "warn"

        return VerificationResult(
            verdict=verdict,
            uncited_claims=uncited[:5],
        )

    # ------------------------------------------------------------------
    # Stage 2: LLM-based
    # ------------------------------------------------------------------

    async def _llm_check(
        self,
        query: str,
        answer: str,
        registry: EvidenceRegistry,
        stage1: VerificationResult,
    ) -> VerificationResult:
        """
        Ask the verify model to evaluate citation coverage.
        """
        # Build a compact evidence summary for the prompt
        evidence_lines = []
        for e in registry.entries()[:20]:
            evidence_lines.append(f"  [{e.marker}] {e.evidence_text[:120]}")
        evidence_block = "\n".join(evidence_lines) or "(empty)"

        prompt = (
            "You are a scientific fact-checker for a bioenergetics research assistant.\n\n"
            f"QUESTION: {query}\n\n"
            "AVAILABLE EVIDENCE (with citation markers):\n"
            f"{evidence_block}\n\n"
            f"DRAFT ANSWER:\n{answer[:1500]}\n\n"
            "TASK: Evaluate the draft answer. Respond with a JSON object only — "
            "no prose, no markdown fences.\n\n"
            "Schema:\n"
            "{\n"
            '  "verdict": "pass" | "warn" | "need_external" | "reject",\n'
            '  "uncited_claims": ["<sentence>", ...],\n'
            '  "invalid_markers": ["<marker>", ...],\n'
            '  "suggestion": "<short note to prepend to the answer, or empty string>"\n'
            "}\n\n"
            "Verdict rules:\n"
            '- "pass":          all or nearly all factual claims have a matching [N]/[GN]/[SFN] marker\n'
            '- "warn":          minor gaps but core claims are cited; answer is acceptable\n'
            '- "need_external": significant factual gaps; external literature should be searched\n'
            '- "reject":        uncited hallucinated facts, or citation markers that are not in the evidence list\n\n'
            "Important: if the answer is a general-knowledge fallback clearly labelled as such, "
            'return "pass" regardless of citation gaps.'
        )

        try:
            raw = await self._ollama_generate(prompt)
            # Strip DeepSeek <think> block
            raw = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL).strip()
            # Extract JSON
            json_match = re.search(r"\{.*\}", raw, re.DOTALL)
            if not json_match:
                raise ValueError("No JSON in LLM response")
            data = json.loads(json_match.group(0))
            verdict = data.get("verdict", "warn")
            if verdict not in ("pass", "warn", "need_external", "reject"):
                verdict = "warn"
            return VerificationResult(
                verdict=verdict,
                uncited_claims=data.get("uncited_claims", [])[:5],
                invalid_markers=data.get("invalid_markers", [])[:5],
                suggestion=data.get("suggestion", ""),
                evidence_mode="local",
            )
        except Exception as exc:
            logger.warning("ReferenceVerifierService LLM check failed: %s", exc)
            # Degrade gracefully: use Stage 1 result with a bump to "warn"
            return VerificationResult(
                verdict="warn",
                uncited_claims=stage1.uncited_claims,
                suggestion="",
                evidence_mode="local",
            )

    # ------------------------------------------------------------------
    # Ollama helper
    # ------------------------------------------------------------------

    async def _ollama_generate(self, prompt: str) -> str:
        tokens: list[str] = []
        try:
            async with httpx.AsyncClient(timeout=None) as client:
                async with client.stream(
                    "POST",
                    f"{self._ollama_url}/api/chat",
                    json={
                        "model": self._model,
                        "messages": [{"role": "user", "content": prompt}],
                        "stream": True,
                        "options": {
                            "num_predict": 400,
                            "temperature": 0.1,
                            "num_ctx": self._num_ctx,
                        },
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
                        token = chunk.get("message", {}).get("content", "")
                        if token:
                            tokens.append(token)
                        if chunk.get("done"):
                            break
        except Exception as exc:
            logger.error("ReferenceVerifierService Ollama call failed: %s", exc)
        return "".join(tokens).strip()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _split_sentences(text: str) -> list[str]:
    """Very simple sentence splitter — good enough for coverage checks."""
    # Split on .!? followed by whitespace or end-of-string
    raw = re.split(r"(?<=[.!?])\s+", text.strip())
    return [s.strip() for s in raw if len(s.strip()) > 20]
