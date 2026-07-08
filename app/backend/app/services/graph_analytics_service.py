"""
Graph analytics tools for the ANALYTICAL chat tier.

Provides deep graph introspection: topology stats, SF evidence ranking,
node neighbourhood exploration, and taxa-concept connections.

All methods are synchronous (run in executor by callers).
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class GraphAnalyticsService:
    """Synchronous ArangoDB graph analytics — call from async code via run_in_executor."""

    def __init__(self, arango_db) -> None:
        self.db = arango_db  # advandeb_kb ArangoDatabase wrapper

    # ------------------------------------------------------------------ 1. topology

    def graph_stats(self, include_degree_dist: bool = False) -> Dict[str, Any]:
        """Return collection sizes, edge counts, and optionally top-degree SF nodes."""
        counts_aql = """
        RETURN {
            documents:      LENGTH(documents),
            facts:          LENGTH(facts),
            stylized_facts: LENGTH(stylized_facts),
            taxa:           LENGTH(taxa),
            chunks:         LENGTH(chunks)
        }
        """
        edge_aql = """
        RETURN {
            sf_support:      LENGTH(sf_support),
            citations:       LENGTH(citations),
            knowledge_graph: LENGTH(knowledge_graph),
            taxonomical:     LENGTH(taxonomical),
            chunk_belongs_to: LENGTH(chunk_belongs_to)
        }
        """
        counts = self.db.aql(counts_aql, {})[0]
        edges = self.db.aql(edge_aql, {})[0]

        result: Dict[str, Any] = {
            "nodes": counts,
            "edges": edges,
            "graphs": [
                "citation_graph (documents → documents)",
                "support_graph (facts → stylized_facts, supports/opposes)",
                "knowledge_graph (documents/facts → stylized_facts/taxa)",
                "taxonomy_graph (taxa → taxa)",
                "chunk_graph (chunks → documents)",
            ],
        }

        if include_degree_dist:
            top_sf_aql = """
            FOR sf IN stylized_facts
              LET total = LENGTH(FOR e IN sf_support FILTER e._to == sf._id RETURN 1)
              FILTER total > 0
              SORT total DESC
              LIMIT 10
              RETURN {
                sf_number: sf.sf_number,
                statement_preview: LEFT(sf.statement, 100),
                total_edges: total
              }
            """
            result["top_10_sf_by_edge_count"] = self.db.aql(top_sf_aql, {})

        return result

    # ------------------------------------------------------------------ 2. sf evidence ranking

    def analyze_sf_support(
        self,
        category: str = "",
        sort_by: str = "support_count",
        limit: int = 10,
    ) -> List[Dict[str, Any]]:
        """Rank stylized facts by evidence support, optionally filtered by category."""
        limit = min(limit, 20)

        # Build category filter
        cat_filter = "FILTER sf.category == @cat" if category else ""
        bind: Dict[str, Any] = {"limit": limit}
        if category:
            bind["cat"] = category

        # Sort expression
        sort_expr_map = {
            "support_count": "support_count DESC",
            "oppose_count":  "oppose_count DESC",
            "net_support":   "net_support DESC",
            "support_ratio": "support_ratio DESC",
        }
        sort_expr = sort_expr_map.get(sort_by, "support_count DESC")

        aql = f"""
        FOR sf IN stylized_facts
          {cat_filter}
          LET support_count = LENGTH(
            FOR e IN sf_support FILTER e._to == sf._id AND e.relation_type == "supports" RETURN 1
          )
          LET oppose_count = LENGTH(
            FOR e IN sf_support FILTER e._to == sf._id AND e.relation_type == "opposes" RETURN 1
          )
          LET net_support  = support_count - oppose_count
          LET support_ratio = (support_count + oppose_count) > 0
                              ? support_count / (support_count + oppose_count + 0.0)
                              : 0.0
          FILTER (support_count + oppose_count) > 0
          SORT {sort_expr}
          LIMIT @limit
          RETURN {{
            sf_number:      sf.sf_number,
            category:       sf.category,
            statement:      sf.statement,
            support_count:  support_count,
            oppose_count:   oppose_count,
            net_support:    net_support,
            support_ratio:  ROUND(support_ratio * 1000) / 1000
          }}
        """
        return self.db.aql(aql, bind)

    # ------------------------------------------------------------------ 3. node exploration

    def explore_graph_node(
        self,
        query: str,
        node_type: str = "auto",
        depth: int = 1,
    ) -> Dict[str, Any]:
        """Find a node by keyword and return its immediate graph neighbourhood."""
        depth = min(max(depth, 1), 2)
        results: List[Dict[str, Any]] = []

        if node_type in ("stylized_fact", "auto"):
            r = self._explore_sf(query, depth)
            if r:
                results.append(r)

        if node_type in ("taxon", "auto"):
            r = self._explore_taxon(query, depth)
            if r:
                results.append(r)

        if node_type in ("document", "auto"):
            r = self._explore_document(query, depth)
            if r:
                results.append(r)

        if not results:
            return {"found": False, "query": query}
        return {"found": True, "nodes": results}

    def _explore_sf(self, query: str, depth: int) -> Optional[Dict[str, Any]]:
        aql = """
        FOR sf IN stylized_facts
          FILTER CONTAINS(LOWER(sf.statement), LOWER(@q))
          LIMIT 1
          LET support_count = LENGTH(
            FOR e IN sf_support FILTER e._to == sf._id AND e.relation_type == "supports" RETURN 1
          )
          LET oppose_count = LENGTH(
            FOR e IN sf_support FILTER e._to == sf._id AND e.relation_type == "opposes" RETURN 1
          )
          LET sample_support = (
            FOR e IN sf_support
              FILTER e._to == sf._id AND e.relation_type == "supports"
              SORT e.confidence DESC
              LIMIT 4
              LET f = DOCUMENT(e._from)
              RETURN {fact_preview: LEFT(f.content, 160), confidence: e.confidence,
                      doc_id: f.document_id, page: f.page_number}
          )
          LET sample_oppose = (
            FOR e IN sf_support
              FILTER e._to == sf._id AND e.relation_type == "opposes"
              SORT e.confidence DESC
              LIMIT 3
              LET f = DOCUMENT(e._from)
              RETURN {fact_preview: LEFT(f.content, 160), confidence: e.confidence,
                      doc_id: f.document_id}
          )
          RETURN {
            node_type: "stylized_fact",
            sf_number: sf.sf_number,
            category:  sf.category,
            statement: sf.statement,
            support_count: support_count,
            oppose_count:  oppose_count,
            net_support:   support_count - oppose_count,
            sample_supporting_facts: sample_support,
            sample_opposing_facts:   sample_oppose
          }
        """
        rows = self.db.aql(aql, {"q": query})
        return rows[0] if rows else None

    def _explore_taxon(self, query: str, depth: int) -> Optional[Dict[str, Any]]:
        aql = """
        FOR t IN taxa
          FILTER CONTAINS(LOWER(t.name), LOWER(@q))
            OR @q IN (t.common_names[* RETURN LOWER(CURRENT)])
            OR @q IN (t.synonyms[*  RETURN LOWER(CURRENT)])
          SORT LENGTH(t.name) ASC
          LIMIT 1
          LET studying_docs = (
            FOR e IN knowledge_graph
              FILTER e._to == t._id
              LIMIT 8
              LET d = DOCUMENT(e._from)
              RETURN {title: LEFT(d.title, 120), doi: d.doi, year: d.year,
                      relation: e.relation_type, confidence: e.confidence}
          )
          LET doc_count = LENGTH(
            FOR e IN knowledge_graph FILTER e._to == t._id RETURN 1
          )
          RETURN {
            node_type:     "taxon",
            name:          t.name,
            rank:          t.rank,
            tax_id:        t.tax_id,
            common_names:  t.common_names,
            document_count: doc_count,
            sample_studying_documents: studying_docs
          }
        """
        rows = self.db.aql(aql, {"q": query.lower()})
        return rows[0] if rows else None

    def _explore_document(self, query: str, depth: int) -> Optional[Dict[str, Any]]:
        aql = """
        FOR d IN document_meta
          FILTER CONTAINS(LOWER(d.title), LOWER(@q))
            OR CONTAINS(LOWER(d.doi), LOWER(@q))
          LIMIT 1
          LET cites = (
            FOR e IN citations FILTER e._from == d._id LIMIT 6
            LET t = DOCUMENT(e._to)
            RETURN {title: LEFT(t.title, 100), doi: t.doi, year: t.year}
          )
          LET cited_by = (
            FOR e IN citations FILTER e._to == d._id LIMIT 6
            LET s = DOCUMENT(e._from)
            RETURN {title: LEFT(s.title, 100), doi: s.doi, year: s.year}
          )
          LET taxa_studied = (
            FOR e IN knowledge_graph
              FILTER e._from == d._id AND e.relation_type == "studies"
              LIMIT 8
              LET t = DOCUMENT(e._to)
              RETURN {name: t.name, rank: t.rank, common_names: t.common_names}
          )
          LET fact_count = LENGTH(
            FOR f IN facts FILTER f.document_id == d._key RETURN 1
          )
          RETURN {
            node_type:     "document",
            title:         d.title,
            doi:           d.doi,
            year:          d.year,
            authors:       d.authors,
            processing_status: d.processing_status,
            fact_count:    fact_count,
            cites:         cites,
            cited_by:      cited_by,
            taxa_studied:  taxa_studied
          }
        """
        rows = self.db.aql(aql, {"q": query})
        return rows[0] if rows else None

    # ------------------------------------------------------------------ 5. sf category breakdown

    def sf_category_breakdown(self) -> List[Dict[str, Any]]:
        """Per-category aggregate stats: SF count, evidence volume, contested fraction, best SF."""
        aql = """
        FOR sf IN stylized_facts
          COLLECT category = sf.category INTO sfs KEEP sf
          LET sf_list = sfs[*].sf
          LET support_total = SUM(
            FOR s IN sf_list
              RETURN LENGTH(FOR e IN sf_support FILTER e._to == s._id AND e.relation_type == "supports" RETURN 1)
          )
          LET oppose_total = SUM(
            FOR s IN sf_list
              RETURN LENGTH(FOR e IN sf_support FILTER e._to == s._id AND e.relation_type == "opposes" RETURN 1)
          )
          LET sf_count = LENGTH(sf_list)
          LET best = (
            FOR s IN sf_list
              LET sc = LENGTH(FOR e IN sf_support FILTER e._to == s._id AND e.relation_type == "supports" RETURN 1)
              SORT sc DESC
              LIMIT 1
              RETURN {sf_number: s.sf_number, support_count: sc, statement_preview: LEFT(s.statement, 120)}
          )[0]
          SORT support_total DESC
          RETURN {
            category:          category,
            sf_count:          sf_count,
            total_support:     support_total,
            total_oppose:      oppose_total,
            avg_support_per_sf: sf_count > 0 ? ROUND(support_total / sf_count * 10) / 10 : 0,
            contested_fraction: (support_total + oppose_total) > 0
                                 ? ROUND(oppose_total / (support_total + oppose_total + 0.0) * 1000) / 1000
                                 : 0.0,
            best_supported_sf: best
          }
        """
        return self.db.aql(aql, {})

    # ------------------------------------------------------------------ 6. contested facts

    def find_contested_facts(
        self,
        min_total: int = 8,
        min_opposition_ratio: float = 0.10,
        limit: int = 10,
    ) -> List[Dict[str, Any]]:
        """Return SFs where opposition is strongest (most controversial claims)."""
        limit = min(limit, 20)
        bind: Dict[str, Any] = {
            "min_total": max(min_total, 2),
            "min_ratio": min_opposition_ratio,
            "limit": limit,
        }
        aql = """
        FOR sf IN stylized_facts
          LET support_count = LENGTH(
            FOR e IN sf_support FILTER e._to == sf._id AND e.relation_type == "supports" RETURN 1
          )
          LET oppose_count = LENGTH(
            FOR e IN sf_support FILTER e._to == sf._id AND e.relation_type == "opposes" RETURN 1
          )
          LET total = support_count + oppose_count
          FILTER total >= @min_total
          LET opp_ratio = total > 0 ? oppose_count / (total + 0.0) : 0.0
          FILTER opp_ratio >= @min_ratio
          LET sample_oppose = (
            FOR e IN sf_support
              FILTER e._to == sf._id AND e.relation_type == "opposes"
              SORT e.confidence DESC LIMIT 2
              LET f = DOCUMENT(e._from)
              RETURN {fact_preview: LEFT(f.content, 140), confidence: e.confidence, doc_id: f.document_id}
          )
          SORT opp_ratio DESC, total DESC
          LIMIT @limit
          RETURN {
            sf_number:        sf.sf_number,
            category:         sf.category,
            statement:        sf.statement,
            support_count:    support_count,
            oppose_count:     oppose_count,
            total_edges:      total,
            opposition_ratio: ROUND(opp_ratio * 1000) / 1000,
            sample_opposing_facts: sample_oppose
          }
        """
        return self.db.aql(aql, bind)

    # ------------------------------------------------------------------ 7. citation influence

    def citation_influence(
        self,
        min_citations: int = 1,
        limit: int = 10,
    ) -> List[Dict[str, Any]]:
        """Rank documents by in-degree (how many KB documents cite them)."""
        limit = min(limit, 20)
        bind: Dict[str, Any] = {"min_cit": max(min_citations, 1), "limit": limit}
        # citations edge uses documents/ IDs; join metadata from documents collection
        aql = """
        FOR e IN citations
          COLLECT to_id = e._to WITH COUNT INTO in_degree
          FILTER in_degree >= @min_cit
          SORT in_degree DESC
          LIMIT @limit
          LET d = DOCUMENT(to_id)
          FILTER d != null
          LET out_degree = LENGTH(FOR e2 IN citations FILTER e2._from == to_id RETURN 1)
          LET fact_count = LENGTH(FOR f IN facts FILTER f.document_id == d._key RETURN 1)
          RETURN {
            title:         d.title,
            doi:           d.doi,
            year:          d.year,
            authors:       d.authors[* LIMIT 3],
            in_degree:     in_degree,
            out_degree:    out_degree,
            fact_count:    fact_count,
            cited_by_openalex: d.cited_by_count
          }
        """
        return self.db.aql(aql, bind)

    # ------------------------------------------------------------------ 8. sf → taxon coverage

    def sf_taxon_coverage(
        self,
        query: str,
        rank: str = "any",
        limit: int = 20,
    ) -> Dict[str, Any]:
        """For a stylized fact (matched by text), find which taxa its evidence covers."""
        limit = min(limit, 40)
        bind: Dict[str, Any] = {"query": query, "rank": rank, "limit": limit}
        aql = """
        LET target_sf = (
          FOR sf IN stylized_facts
            FILTER CONTAINS(LOWER(sf.statement), LOWER(@query))
            SORT LENGTH(sf.statement) ASC
            LIMIT 1
            RETURN sf
        )[0]
        FILTER target_sf != null
        LET support_doc_keys = (
          FOR e IN sf_support
            FILTER e._to == target_sf._id AND e.relation_type == "supports"
            LET f = DOCUMENT(e._from)
            FILTER f != null AND f.document_id != null
            RETURN DISTINCT f.document_id
        )
        LET all_taxa = (
          FOR doc_key IN support_doc_keys
            FOR kg_e IN knowledge_graph
              FILTER kg_e._from == CONCAT("documents/", doc_key)
              FILTER STARTS_WITH(kg_e._to, "taxa/")
              LET t = DOCUMENT(kg_e._to)
              FILTER t != null
              RETURN DISTINCT {
                name:         t.name,
                rank:         t.rank,
                tax_id:       t.tax_id,
                common_names: t.common_names[* LIMIT 2]
              }
        )
        LET filtered_taxa = (
          FOR t IN all_taxa
            FILTER @rank == "any" OR t.rank == @rank
            LIMIT @limit
            RETURN t
        )
        RETURN {
          sf_number:             target_sf.sf_number,
          category:              target_sf.category,
          statement:             target_sf.statement,
          supporting_doc_count:  LENGTH(support_doc_keys),
          taxa_count:            LENGTH(all_taxa),
          filtered_rank:         @rank,
          taxa:                  filtered_taxa
        }
        """
        rows = self.db.aql(aql, bind)
        if not rows:
            return {"found": False, "query": query}
        result = rows[0]
        result["found"] = bool(result.get("sf_number") is not None)
        return result

    # ------------------------------------------------------------------ 9. taxon subtree stats

    def taxon_subtree_stats(
        self,
        group_name: str,
        rank: str = "species",
        limit: int = 20,
    ) -> Dict[str, Any]:
        """For a taxonomic group, list KB-covered descendants at a given rank."""
        limit = min(limit, 40)

        # Locate the root taxon
        root_aql = """
        FOR t IN taxa
          FILTER LOWER(t.name) == LOWER(@name)
            OR LOWER(t.name) LIKE CONCAT('%', LOWER(@name), '%')
          SORT LENGTH(t.name) ASC
          LIMIT 1
          RETURN t
        """
        roots = self.db.aql(root_aql, {"name": group_name})
        if not roots:
            return {"found": False, "group": group_name}
        root = roots[0]

        # Traverse INBOUND (NCBI-style: edges go child → parent, so INBOUND = children)
        # Cap at 1000 vertices to avoid full-tree scans for broad groups.
        # INBOUND = children (NCBI-style: edges go child → parent)
        # doc_count counts knowledge_graph edges (sparse — 35 total); most will be 0
        desc_aql = """
        FOR v IN 1..8 INBOUND @root_id GRAPH "taxonomy_graph"
          LIMIT 1000
          FILTER v.rank == @rank
          LET doc_count = LENGTH(FOR e IN knowledge_graph FILTER e._to == v._id RETURN 1)
          SORT doc_count DESC, v.name ASC
          LIMIT @limit
          RETURN {
            name:         v.name,
            rank:         v.rank,
            tax_id:       v.tax_id,
            common_names: v.common_names[* LIMIT 2],
            doc_count:    doc_count
          }
        """
        descendants = self.db.aql(desc_aql, {
            "root_id": root["_id"],
            "rank": rank,
            "limit": limit,
        })

        return {
            "found":        True,
            "group":        root["name"],
            "group_rank":   root.get("rank"),
            "tax_id":       root.get("tax_id"),
            "target_rank":  rank,
            "total_found":  len(descendants),
            "descendants":  descendants,
        }

    # ------------------------------------------------------------------ 4. taxa-concept connections

    def find_taxa_connections(
        self,
        concept: str,
        rank: str = "species",
        limit: int = 15,
    ) -> Dict[str, Any]:
        """Find taxa connected to a given DEB concept through documents and facts."""
        limit = min(limit, 30)
        bind: Dict[str, Any] = {"concept": concept}

        # Path: concept → matching documents (title/abstract) → knowledge_graph → taxa
        doc_aql = """
        LET matching_doc_ids = (
          FOR d IN documents
            FILTER CONTAINS(LOWER(d.title),    LOWER(@concept))
                OR CONTAINS(LOWER(d.abstract), LOWER(@concept))
            FILTER d.source_type != "web"
            LIMIT 40
            RETURN d._id
        )
        FOR doc_id IN matching_doc_ids
          FOR e IN knowledge_graph
            FILTER e._from == doc_id
            LET t = DOCUMENT(e._to)
            FILTER t != null
            RETURN DISTINCT {name: t.name, rank: t.rank, tax_id: t.tax_id,
                             common_names: t.common_names[* LIMIT 3]}
        """
        via_docs = self.db.aql(doc_aql, bind)

        # Path: concept → matching facts (content) → document → knowledge_graph → taxa
        fact_aql = """
        LET matching_fact_doc_ids = (
          FOR f IN facts
            FILTER CONTAINS(LOWER(f.content), LOWER(@concept))
            LIMIT 30
            RETURN DISTINCT CONCAT("documents/", f.document_id)
        )
        FOR doc_id IN matching_fact_doc_ids
          FOR e IN knowledge_graph
            FILTER e._from == doc_id
            LET t = DOCUMENT(e._to)
            FILTER t != null
            RETURN DISTINCT {name: t.name, rank: t.rank, tax_id: t.tax_id,
                             common_names: t.common_names[* LIMIT 3]}
        """
        via_facts = self.db.aql(fact_aql, bind)

        # Merge and deduplicate by tax_id
        seen: Dict[int, Dict] = {}
        for item in via_docs + via_facts:
            tid = item.get("tax_id") or item.get("name", "")
            if tid not in seen:
                seen[tid] = item

        all_taxa = list(seen.values())

        # Rank filter
        if rank != "any":
            all_taxa = [t for t in all_taxa if t.get("rank") == rank]

        return {
            "concept": concept,
            "total_found": len(all_taxa),
            "rank_filter": rank,
            "taxa": all_taxa[:limit],
        }
