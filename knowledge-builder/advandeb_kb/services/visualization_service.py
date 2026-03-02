import networkx as nx
from typing import List, Dict, Any, Optional
from advandeb_kb.models.knowledge import KnowledgeGraph, Fact, StylizedFact
from bson import ObjectId
from datetime import datetime
import json
import logging

logger = logging.getLogger(__name__)

class VisualizationService:
    def __init__(self, database):
        self.db = database
        self.graphs_collection = database.knowledge_graphs
        self.facts_collection = database.facts
        self.stylized_facts_collection = database.stylized_facts

    async def get_graph_visualization(self, graph_id: str, layout: str = "spring") -> Dict[str, Any]:
        """Get graph visualization data"""
        graph_data = await self.graphs_collection.find_one({"_id": ObjectId(graph_id)})
        if not graph_data:
            raise ValueError("Graph not found")
        
        # Create NetworkX graph
        G = nx.Graph()
        
        # Add nodes
        for node in graph_data.get("nodes", []):
            G.add_node(node["id"], **node.get("attributes", {}))
        
        # Add edges
        for edge in graph_data.get("edges", []):
            G.add_edge(edge["source"], edge["target"], **edge.get("attributes", {}))
        
        # Calculate layout
        if layout == "spring":
            pos = nx.spring_layout(G, k=1, iterations=50)
        elif layout == "circular":
            pos = nx.circular_layout(G)
        elif layout == "random":
            pos = nx.random_layout(G)
        elif layout == "shell":
            pos = nx.shell_layout(G)
        else:
            pos = nx.spring_layout(G)
        
        # Prepare visualization data
        viz_data = {
            "nodes": [],
            "edges": [],
            "layout": layout,
            "statistics": {
                "node_count": G.number_of_nodes(),
                "edge_count": G.number_of_edges(),
                "density": nx.density(G),
                "connected_components": nx.number_connected_components(G)
            }
        }
        
        # Add nodes with positions
        for node_id, (x, y) in pos.items():
            node_data = G.nodes[node_id]
            viz_data["nodes"].append({
                "id": node_id,
                "x": float(x),
                "y": float(y),
                "label": node_data.get("label", node_id),
                "size": node_data.get("size", 10),
                "color": node_data.get("color", "#1f77b4"),
                "type": node_data.get("type", "default")
            })
        
        # Add edges
        for source, target, edge_data in G.edges(data=True):
            viz_data["edges"].append({
                "source": source,
                "target": target,
                "weight": edge_data.get("weight", 1),
                "color": edge_data.get("color", "#999"),
                "type": edge_data.get("type", "default")
            })
        
        return viz_data

    async def create_graph_from_facts(self, fact_ids: List[str], graph_name: str, description: str = "") -> Dict[str, Any]:
        """Create a knowledge graph from selected facts"""
        # Fetch facts
        fact_object_ids = [ObjectId(fid) for fid in fact_ids]
        cursor = self.facts_collection.find({"_id": {"$in": fact_object_ids}})
        facts = []
        async for fact_data in cursor:
            facts.append(Fact(**fact_data))
        
        if not facts:
            raise ValueError("No facts found")
        
        # Create nodes and edges from facts
        nodes = []
        edges = []
        entity_counts = {}
        
        # Extract entities and create nodes
        for i, fact in enumerate(facts):
            # Create a fact node
            fact_node_id = f"fact_{i}"
            nodes.append({
                "id": fact_node_id,
                "label": fact.content[:50] + "..." if len(fact.content) > 50 else fact.content,
                "type": "fact",
                "fact_id": str(fact.id),
                "content": fact.content,
                "source": fact.source,
                "confidence": fact.confidence,
                "size": 15,
                "color": "#ff7f0e"
            })
            
            # Extract entities from fact and create entity nodes
            for entity in fact.entities:
                entity_id = entity.get("text", "").lower().replace(" ", "_")
                if entity_id and len(entity_id) > 2:
                    if entity_id not in entity_counts:
                        entity_counts[entity_id] = {
                            "count": 0,
                            "text": entity.get("text", ""),
                            "type": entity.get("type", "ENTITY")
                        }
                    entity_counts[entity_id]["count"] += 1
                    
                    # Create edge from fact to entity
                    edges.append({
                        "source": fact_node_id,
                        "target": entity_id,
                        "type": "mentions",
                        "weight": 1
                    })
        
        # Add entity nodes
        for entity_id, entity_data in entity_counts.items():
            nodes.append({
                "id": entity_id,
                "label": entity_data["text"],
                "type": "entity",
                "entity_type": entity_data["type"],
                "count": entity_data["count"],
                "size": min(30, 10 + entity_data["count"] * 2),
                "color": "#2ca02c"
            })
        
        # Create co-occurrence edges between entities
        for i, fact in enumerate(facts):
            fact_entities = [e.get("text", "").lower().replace(" ", "_") for e in fact.entities]
            fact_entities = [e for e in fact_entities if e and len(e) > 2]
            
            # Create edges between entities that appear in the same fact
            for j in range(len(fact_entities)):
                for k in range(j + 1, len(fact_entities)):
                    edges.append({
                        "source": fact_entities[j],
                        "target": fact_entities[k],
                        "type": "co_occurrence",
                        "weight": 2
                    })
        
        # Create knowledge graph
        graph = KnowledgeGraph(
            name=graph_name,
            description=description,
            nodes=nodes,
            edges=edges,
            metadata={
                "fact_count": len(facts),
                "entity_count": len(entity_counts),
                "creation_method": "fact_extraction"
            }
        )
        
        # Save to database
        graph_dict = graph.dict(by_alias=True, exclude_unset=True)
        graph_dict["_id"] = ObjectId()
        result = await self.graphs_collection.insert_one(graph_dict)
        
        return {
            "graph_id": str(result.inserted_id),
            "name": graph_name,
            "nodes": len(nodes),
            "edges": len(edges),
            "status": "created"
        }

    async def get_network_statistics(self, graph_id: str) -> Dict[str, Any]:
        """Get network analysis statistics for a graph"""
        graph_data = await self.graphs_collection.find_one({"_id": ObjectId(graph_id)})
        if not graph_data:
            raise ValueError("Graph not found")
        
        # Create NetworkX graph
        G = nx.Graph()
        
        # Add nodes and edges
        for node in graph_data.get("nodes", []):
            G.add_node(node["id"])
        
        for edge in graph_data.get("edges", []):
            G.add_edge(edge["source"], edge["target"])
        
        if G.number_of_nodes() == 0:
            return {"error": "Empty graph"}
        
        # Calculate statistics
        stats = {
            "basic": {
                "nodes": G.number_of_nodes(),
                "edges": G.number_of_edges(),
                "density": nx.density(G),
                "connected_components": nx.number_connected_components(G)
            },
            "centrality": {},
            "clustering": {},
            "connectivity": {}
        }
        
        if G.number_of_nodes() > 0:
            # Centrality measures
            degree_centrality = nx.degree_centrality(G)
            stats["centrality"]["top_degree"] = sorted(
                degree_centrality.items(), key=lambda x: x[1], reverse=True
            )[:5]
            
            if nx.is_connected(G):
                betweenness_centrality = nx.betweenness_centrality(G)
                stats["centrality"]["top_betweenness"] = sorted(
                    betweenness_centrality.items(), key=lambda x: x[1], reverse=True
                )[:5]
                
                closeness_centrality = nx.closeness_centrality(G)
                stats["centrality"]["top_closeness"] = sorted(
                    closeness_centrality.items(), key=lambda x: x[1], reverse=True
                )[:5]
            
            # Clustering
            clustering_coeffs = nx.clustering(G)
            stats["clustering"]["average"] = sum(clustering_coeffs.values()) / len(clustering_coeffs)
            stats["clustering"]["top_nodes"] = sorted(
                clustering_coeffs.items(), key=lambda x: x[1], reverse=True
            )[:5]
        
        return stats

    async def update_graph_layout(self, graph_id: str, layout_type: str, layout_params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Update graph layout"""
        # This would update the node positions in the database
        # For now, we'll just return the new layout data
        viz_data = await self.get_graph_visualization(graph_id, layout_type)
        
        # Update the graph in the database with new positions
        nodes_update = []
        for node in viz_data["nodes"]:
            nodes_update.append({
                "id": node["id"],
                "x": node["x"],
                "y": node["y"],
                "attributes": {k: v for k, v in node.items() if k not in ["id", "x", "y"]}
            })
        
        await self.graphs_collection.update_one(
            {"_id": ObjectId(graph_id)},
            {
                "$set": {
                    "nodes": nodes_update,
                    "updated_at": datetime.utcnow()
                }
            }
        )
        
        return {"status": "updated", "layout": layout_type}

    async def get_entity_relationships(self, entity: str, depth: int = 2) -> List[Dict[str, Any]]:
        """Get relationships for a specific entity"""
        # Search for facts containing the entity
        entity_regex = {"$regex": entity, "$options": "i"}
        cursor = self.facts_collection.find({
            "$or": [
                {"content": entity_regex},
                {"entities.text": entity_regex}
            ]
        })
        
        relationships = []
        async for fact_data in cursor:
            fact = Fact(**fact_data)
            
            # Extract related entities
            for ent in fact.entities:
                if ent.get("text", "").lower() != entity.lower():
                    relationships.append({
                        "entity": ent.get("text", ""),
                        "type": ent.get("type", "UNKNOWN"),
                        "context": fact.content,
                        "source": fact.source,
                        "confidence": fact.confidence
                    })
        
        return relationships[:20]  # Limit results

    async def detect_communities(self, graph_id: str, algorithm: str = "louvain") -> Dict[str, Any]:
        """Detect communities/clusters in the knowledge graph"""
        graph_data = await self.graphs_collection.find_one({"_id": ObjectId(graph_id)})
        if not graph_data:
            raise ValueError("Graph not found")
        
        # Create NetworkX graph
        G = nx.Graph()
        
        for node in graph_data.get("nodes", []):
            G.add_node(node["id"])
        
        for edge in graph_data.get("edges", []):
            G.add_edge(edge["source"], edge["target"])
        
        if G.number_of_nodes() == 0:
            return {"communities": []}
        
        # Detect communities using different algorithms
        if algorithm == "louvain":
            try:
                import community as community_louvain
                partition = community_louvain.best_partition(G)
            except ImportError:
                # Fallback to connected components
                partition = {}
                for i, component in enumerate(nx.connected_components(G)):
                    for node in component:
                        partition[node] = i
        else:
            # Use connected components as fallback
            partition = {}
            for i, component in enumerate(nx.connected_components(G)):
                for node in component:
                    partition[node] = i
        
        # Group nodes by community
        communities = {}
        for node, community_id in partition.items():
            if community_id not in communities:
                communities[community_id] = []
            communities[community_id].append(node)
        
        return {
            "algorithm": algorithm,
            "communities": [{"id": cid, "nodes": nodes} for cid, nodes in communities.items()],
            "modularity": nx.algorithms.community.modularity(G, communities.values()) if communities else 0
        }

    async def export_graph(self, graph_id: str, format: str = "json") -> Dict[str, Any]:
        """Export graph in various formats"""
        graph_data = await self.graphs_collection.find_one({"_id": ObjectId(graph_id)})
        if not graph_data:
            raise ValueError("Graph not found")
        
        if format == "json":
            # Clean up for JSON export
            export_data = {
                "name": graph_data["name"],
                "description": graph_data["description"],
                "nodes": graph_data.get("nodes", []),
                "edges": graph_data.get("edges", []),
                "metadata": graph_data.get("metadata", {}),
                "created_at": graph_data["created_at"].isoformat(),
                "updated_at": graph_data["updated_at"].isoformat()
            }
            return export_data
        
        elif format == "gexf":
            # Export as GEXF format for Gephi
            G = nx.Graph()
            for node in graph_data.get("nodes", []):
                G.add_node(node["id"], **node.get("attributes", {}))
            for edge in graph_data.get("edges", []):
                G.add_edge(edge["source"], edge["target"], **edge.get("attributes", {}))
            
            # This would need to be implemented to generate GEXF
            return {"error": "GEXF export not implemented"}
        
        else:
            return {"error": f"Format {format} not supported"}