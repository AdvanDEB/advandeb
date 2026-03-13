use std::{
    collections::HashMap,
    sync::Arc,
    time::{Duration, SystemTime},
};

use serde::{Deserialize, Serialize};
use tokio::sync::RwLock;
use tracing::{info, warn};

use crate::mcp::protocol::ToolInfo;

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub enum AgentStatus {
    Healthy,
    Degraded,
    Unavailable,
}

#[derive(Debug, Clone)]
pub struct AgentInfo {
    pub name: String,
    pub websocket_url: String,
    pub tools: Vec<ToolInfo>,
    pub status: AgentStatus,
    pub registered_at: SystemTime,
    pub last_health_check: SystemTime,
}

#[derive(Serialize)]
pub struct AgentSummary {
    pub name: String,
    pub websocket_url: String,
    pub tools: Vec<String>,
    pub status: AgentStatus,
}

pub struct AgentRegistry {
    /// agent_name -> AgentInfo
    agents: Arc<RwLock<HashMap<String, AgentInfo>>>,
    /// tool_name -> Vec<agent_name>  (multiple replicas can serve the same tool)
    tool_index: Arc<RwLock<HashMap<String, Vec<String>>>>,
}

impl AgentRegistry {
    pub fn new() -> Self {
        Self {
            agents: Arc::new(RwLock::new(HashMap::new())),
            tool_index: Arc::new(RwLock::new(HashMap::new())),
        }
    }

    /// Register (or re-register) an agent. Multiple agents may advertise the
    /// same tool; all are tracked so the router can load-balance across them.
    pub async fn register(&self, name: String, websocket_url: String, tools: Vec<ToolInfo>) {
        let mut agents = self.agents.write().await;
        let mut index = self.tool_index.write().await;

        // Remove this agent's name from any existing tool entries
        for names in index.values_mut() {
            names.retain(|n| n != &name);
        }
        index.retain(|_, names| !names.is_empty());

        // Index new tools — append agent name (dedup in case of repeated registration)
        for tool in &tools {
            let names = index.entry(tool.name.clone()).or_default();
            if !names.contains(&name) {
                names.push(name.clone());
            }
        }

        let agent = AgentInfo {
            name: name.clone(),
            websocket_url,
            tools,
            status: AgentStatus::Healthy,
            registered_at: SystemTime::now(),
            last_health_check: SystemTime::now(),
        };

        info!("Registered agent '{}' with {} tool(s)", name, agent.tools.len());
        agents.insert(name, agent);
    }

    /// Remove an agent and all its tool index entries.
    pub async fn deregister(&self, name: &str) {
        let mut agents = self.agents.write().await;
        let mut index = self.tool_index.write().await;
        for names in index.values_mut() {
            names.retain(|n| n.as_str() != name);
        }
        index.retain(|_, names| !names.is_empty());
        agents.remove(name);
        info!("Deregistered agent '{}'", name);
    }

    /// Return all **healthy** agents that advertise `tool_name`, in registration order.
    /// Used by the load-balancer to select a target.
    pub async fn agents_for_tool(&self, tool_name: &str) -> Vec<AgentInfo> {
        let index = self.tool_index.read().await;
        let names = match index.get(tool_name) {
            Some(n) => n.clone(),
            None => return vec![],
        };
        drop(index);

        let agents = self.agents.read().await;
        names
            .iter()
            .filter_map(|n| agents.get(n))
            .filter(|a| a.status == AgentStatus::Healthy)
            .cloned()
            .collect()
    }

    /// Convenience: first healthy agent for a tool (for simple single-replica use).
    pub async fn agent_for_tool(&self, tool_name: &str) -> Option<AgentInfo> {
        self.agents_for_tool(tool_name).await.into_iter().next()
    }

    /// All tools across all healthy agents (for tools/list).
    pub async fn all_tools(&self) -> Vec<ToolInfo> {
        let agents = self.agents.read().await;
        agents
            .values()
            .filter(|a| a.status == AgentStatus::Healthy)
            .flat_map(|a| a.tools.iter().cloned())
            .collect()
    }

    /// Snapshot for REST listing.
    pub async fn list(&self) -> Vec<AgentSummary> {
        let agents = self.agents.read().await;
        agents
            .values()
            .map(|a| AgentSummary {
                name: a.name.clone(),
                websocket_url: a.websocket_url.clone(),
                tools: a.tools.iter().map(|t| t.name.clone()).collect(),
                status: a.status.clone(),
            })
            .collect()
    }

    /// Update a single agent's status (called by circuit breaker and health monitor).
    pub async fn set_status(&self, agent_name: &str, status: AgentStatus) {
        let mut agents = self.agents.write().await;
        if let Some(agent) = agents.get_mut(agent_name) {
            if agent.status != status {
                warn!("Agent '{}' status → {:?}", agent_name, status);
            }
            agent.status = status;
            agent.last_health_check = SystemTime::now();
        }
    }

    /// Spawn background health monitoring (HTTP GET to each agent's /health).
    pub fn start_health_monitoring(self: &Arc<Self>, interval: Duration) {
        let registry = Arc::clone(self);
        tokio::spawn(async move {
            let mut ticker = tokio::time::interval(interval);
            loop {
                ticker.tick().await;
                registry.run_health_checks().await;
            }
        });
    }

    async fn run_health_checks(&self) {
        let agent_entries: Vec<(String, String)> = {
            let agents = self.agents.read().await;
            agents
                .values()
                .map(|a| (a.name.clone(), a.websocket_url.clone()))
                .collect()
        };

        for (name, ws_url) in agent_entries {
            let http_url = ws_url
                .replacen("ws://", "http://", 1)
                .replacen("wss://", "https://", 1);
            let health_url = format!("{http_url}/health");

            let status = match reqwest::get(&health_url).await {
                Ok(r) if r.status().is_success() => AgentStatus::Healthy,
                Ok(_) => AgentStatus::Degraded,
                Err(_) => AgentStatus::Unavailable,
            };

            self.set_status(&name, status).await;
        }
    }
}

// ── Unit tests ────────────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;
    use crate::mcp::protocol::ToolInfo;

    fn make_tool(name: &str) -> ToolInfo {
        ToolInfo {
            name: name.into(),
            description: format!("{name} tool"),
            input_schema: serde_json::Value::Null,
        }
    }

    #[tokio::test]
    async fn register_and_lookup() {
        let reg = AgentRegistry::new();
        reg.register(
            "agent_a".into(),
            "ws://localhost:8081".into(),
            vec![make_tool("search"), make_tool("embed")],
        )
        .await;

        let agent = reg.agent_for_tool("search").await.expect("should find agent");
        assert_eq!(agent.name, "agent_a");
        assert_eq!(agent.status, AgentStatus::Healthy);
    }

    #[tokio::test]
    async fn missing_tool_returns_none() {
        let reg = AgentRegistry::new();
        assert!(reg.agent_for_tool("nonexistent").await.is_none());
    }

    #[tokio::test]
    async fn deregister_removes_tool_index() {
        let reg = AgentRegistry::new();
        reg.register(
            "agent_b".into(),
            "ws://localhost:8082".into(),
            vec![make_tool("graph_query")],
        )
        .await;

        assert!(reg.agent_for_tool("graph_query").await.is_some());
        reg.deregister("agent_b").await;
        assert!(reg.agent_for_tool("graph_query").await.is_none());
    }

    #[tokio::test]
    async fn re_register_updates_tool_index() {
        let reg = AgentRegistry::new();
        reg.register(
            "agent_c".into(),
            "ws://localhost:8083".into(),
            vec![make_tool("old_tool")],
        )
        .await;

        reg.register(
            "agent_c".into(),
            "ws://localhost:8083".into(),
            vec![make_tool("new_tool")],
        )
        .await;

        assert!(reg.agent_for_tool("old_tool").await.is_none());
        assert!(reg.agent_for_tool("new_tool").await.is_some());
    }

    #[tokio::test]
    async fn all_tools_returns_all_healthy() {
        let reg = AgentRegistry::new();
        reg.register(
            "a1".into(),
            "ws://localhost:8084".into(),
            vec![make_tool("t1"), make_tool("t2")],
        )
        .await;
        reg.register(
            "a2".into(),
            "ws://localhost:8085".into(),
            vec![make_tool("t3")],
        )
        .await;

        let tools = reg.all_tools().await;
        let names: Vec<_> = tools.iter().map(|t| t.name.as_str()).collect();
        assert!(names.contains(&"t1"));
        assert!(names.contains(&"t2"));
        assert!(names.contains(&"t3"));
    }

    #[tokio::test]
    async fn multiple_agents_per_tool() {
        let reg = AgentRegistry::new();
        reg.register(
            "replica_1".into(),
            "ws://localhost:8091".into(),
            vec![make_tool("search")],
        )
        .await;
        reg.register(
            "replica_2".into(),
            "ws://localhost:8092".into(),
            vec![make_tool("search")],
        )
        .await;

        let agents = reg.agents_for_tool("search").await;
        assert_eq!(agents.len(), 2);
        let names: Vec<_> = agents.iter().map(|a| a.name.as_str()).collect();
        assert!(names.contains(&"replica_1"));
        assert!(names.contains(&"replica_2"));
    }

    #[tokio::test]
    async fn unavailable_agent_excluded_from_candidates() {
        let reg = AgentRegistry::new();
        reg.register(
            "r1".into(),
            "ws://localhost:8093".into(),
            vec![make_tool("search")],
        )
        .await;
        reg.register(
            "r2".into(),
            "ws://localhost:8094".into(),
            vec![make_tool("search")],
        )
        .await;

        reg.set_status("r1", AgentStatus::Unavailable).await;

        let agents = reg.agents_for_tool("search").await;
        assert_eq!(agents.len(), 1);
        assert_eq!(agents[0].name, "r2");
    }
}
