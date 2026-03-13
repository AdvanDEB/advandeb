use std::sync::Arc;
use std::time::Instant;

use futures_util::{SinkExt, StreamExt};
use serde_json::Value;
use tokio_tungstenite::tungstenite::Message;
use tracing::{debug, error, info};

use crate::mcp::protocol::ToolInfo;
use crate::metrics;

use super::balancer::RoundRobinBalancer;
use super::circuit_breaker::{BreakerConfig, CircuitBreakerRegistry};
use super::pool::{ConnectionPool, WsStream};
use super::registry::{AgentInfo, AgentRegistry};
use super::retry::retry_with_backoff;

/// Maximum retries for transient connection errors (total attempts = MAX_RETRIES + 1).
const MAX_RETRIES: u32 = 2;

pub struct AgentRouter {
    pub registry: Arc<AgentRegistry>,
    pool: ConnectionPool,
    balancer: RoundRobinBalancer,
    breakers: CircuitBreakerRegistry,
}

impl AgentRouter {
    pub fn new(registry: Arc<AgentRegistry>) -> Self {
        Self {
            registry,
            pool: ConnectionPool::new(),
            balancer: RoundRobinBalancer::new(),
            breakers: CircuitBreakerRegistry::new(BreakerConfig::default()),
        }
    }

    /// Return all tools across healthy agents.
    pub async fn all_tools(&self) -> Vec<ToolInfo> {
        self.registry.all_tools().await
    }

    /// Route a `tools/call` to an agent that owns `tool_name`.
    ///
    /// Selection: round-robin across healthy candidates that have an open
    /// circuit breaker.  If the selected agent fails, retries up to
    /// `MAX_RETRIES` times (with exponential backoff) before giving up.
    pub async fn route_tool_call(
        &self,
        tool_name: &str,
        arguments: Value,
    ) -> Result<Value, anyhow::Error> {
        let candidates = self.registry.agents_for_tool(tool_name).await;
        if candidates.is_empty() {
            return Err(anyhow::anyhow!(
                "No agent registered for tool '{}'",
                tool_name
            ));
        }

        // Filter out agents whose circuit breaker is open
        let allowed: Vec<AgentInfo> = {
            let mut v = Vec::new();
            for a in &candidates {
                if self.breakers.allow(&a.name).await {
                    v.push(a.clone());
                }
            }
            v
        };

        if allowed.is_empty() {
            return Err(anyhow::anyhow!(
                "All agents for tool '{}' are circuit-broken",
                tool_name
            ));
        }

        let agent = self
            .balancer
            .pick(&allowed)
            .expect("allowed is non-empty")
            .clone();

        let start = Instant::now();
        let timer = metrics::TOOL_LATENCY
            .with_label_values(&[tool_name, &agent.name])
            .start_timer();

        let agent_name = agent.name.clone();
        let ws_url = agent.websocket_url.clone();
        let tool_name_owned = tool_name.to_string();
        let arguments_clone = arguments.clone();

        let result = retry_with_backoff(
            || {
                let url = ws_url.clone();
                let tool = tool_name_owned.clone();
                let args = arguments_clone.clone();
                let pool = self.pool.clone();
                async move { call_with_pool(&pool, &url, &tool, args).await }
            },
            MAX_RETRIES,
            &format!("{tool_name}@{agent_name}"),
        )
        .await;

        timer.observe_duration();
        let elapsed_ms = start.elapsed().as_millis();

        match &result {
            Ok(_) => {
                self.breakers.record_success(&agent_name).await;
                metrics::TOOL_CALLS
                    .with_label_values(&[tool_name, &agent_name, "ok"])
                    .inc();
                info!(tool = tool_name, agent = agent_name, elapsed_ms, "Tool call succeeded");
            }
            Err(e) => {
                self.breakers.record_failure(&agent_name).await;
                metrics::TOOL_CALLS
                    .with_label_values(&[tool_name, &agent_name, "error"])
                    .inc();
                error!(tool = tool_name, agent = agent_name, elapsed_ms, error = %e, "Tool call failed");
            }
        }

        result
    }

    /// Idle connection count (for /pool/stats and metrics).
    pub async fn pool_idle_count(&self) -> usize {
        self.pool.idle_count().await
    }
}

// ── Pool-aware single attempt ─────────────────────────────────────────────────

async fn call_with_pool(
    pool: &ConnectionPool,
    ws_url: &str,
    tool_name: &str,
    arguments: Value,
) -> Result<Value, anyhow::Error> {
    let conn = pool.acquire(ws_url).await?;
    match do_tool_call(conn, tool_name, arguments).await {
        Ok((result, conn)) => {
            pool.release(ws_url.to_string(), conn).await;
            Ok(result)
        }
        Err(e) => {
            debug!("Connection to {ws_url} dropped after error: {e}");
            Err(e)
        }
    }
}

// ── Core WebSocket exchange ───────────────────────────────────────────────────

async fn do_tool_call(
    mut conn: WsStream,
    tool_name: &str,
    arguments: Value,
) -> Result<(Value, WsStream), anyhow::Error> {
    let request = serde_json::json!({
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": { "name": tool_name, "arguments": arguments }
    });

    conn.send(Message::Text(serde_json::to_string(&request)?))
        .await
        .map_err(|e| anyhow::anyhow!("Send to agent failed: {}", e))?;

    loop {
        match conn.next().await {
            Some(Ok(Message::Text(text))) => {
                let response: Value = serde_json::from_str(&text)
                    .map_err(|e| anyhow::anyhow!("Invalid JSON from agent: {}", e))?;

                if let Some(error) = response.get("error") {
                    let msg = error["message"]
                        .as_str()
                        .unwrap_or("unknown error")
                        .to_string();
                    return Err(anyhow::anyhow!("Agent error: {}", msg));
                }

                let result = response.get("result").cloned().unwrap_or(Value::Null);
                return Ok((result, conn));
            }
            Some(Ok(Message::Ping(_) | Message::Pong(_))) => continue,
            Some(Ok(_)) => continue,
            Some(Err(e)) => {
                return Err(anyhow::anyhow!("WebSocket error from agent: {}", e));
            }
            None => {
                return Err(anyhow::anyhow!("Agent closed connection before responding"));
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use tokio::net::TcpListener;
    use tokio_tungstenite::accept_async;

    async fn spawn_mock_agent(tool_name: &str, response_result: Value) -> String {
        let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
        let addr = listener.local_addr().unwrap();
        let _tool_name = tool_name.to_string();

        tokio::spawn(async move {
            while let Ok((stream, _)) = listener.accept().await {
                let response_result = response_result.clone();
                
                tokio::spawn(async move {
                    let mut ws = accept_async(stream).await.unwrap();
                    
                    // Read request
                    if let Some(Ok(Message::Text(_text))) = ws.next().await {
                        // Send response
                        let response = serde_json::json!({
                            "jsonrpc": "2.0",
                            "id": 1,
                            "result": response_result
                        });
                        let _ = ws.send(Message::Text(response.to_string())).await;
                    }
                });
            }
        });

        format!("ws://127.0.0.1:{}", addr.port())
    }

    #[tokio::test]
    async fn test_router_new() {
        let registry = Arc::new(AgentRegistry::new());
        let router = AgentRouter::new(registry.clone());
        
        assert_eq!(router.pool_idle_count().await, 0);
        assert!(router.all_tools().await.is_empty());
    }

    #[tokio::test]
    async fn test_all_tools_from_registry() {
        let registry = Arc::new(AgentRegistry::new());
        let router = AgentRouter::new(registry.clone());
        
        let url = spawn_mock_agent("test_tool", serde_json::json!({"status": "ok"})).await;
        
        registry.register(
            "agent1".to_string(),
            url,
            vec![
                ToolInfo { 
                    name: "tool1".to_string(), 
                    description: "Test tool 1".to_string(),
                    input_schema: serde_json::json!({})
                },
                ToolInfo { 
                    name: "tool2".to_string(), 
                    description: "Test tool 2".to_string(),
                    input_schema: serde_json::json!({})
                },
            ]
        ).await;
        
        let tools = router.all_tools().await;
        assert_eq!(tools.len(), 2);
        assert_eq!(tools[0].name, "tool1");
        assert_eq!(tools[1].name, "tool2");
    }

    #[tokio::test]
    async fn test_route_tool_call_no_agent() {
        let registry = Arc::new(AgentRegistry::new());
        let router = AgentRouter::new(registry.clone());
        
        let result = router.route_tool_call("nonexistent_tool", serde_json::json!({})).await;
        
        assert!(result.is_err());
        assert!(result.unwrap_err().to_string().contains("No agent registered"));
    }

    #[tokio::test]
    async fn test_route_tool_call_success() {
        let registry = Arc::new(AgentRegistry::new());
        let router = AgentRouter::new(registry.clone());
        
        let expected_result = serde_json::json!({"answer": 42});
        let url = spawn_mock_agent("calculate", expected_result.clone()).await;
        
        registry.register(
            "math_agent".to_string(),
            url,
            vec![
                ToolInfo { 
                    name: "calculate".to_string(), 
                    description: "Do math".to_string(),
                    input_schema: serde_json::json!({})
                },
            ]
        ).await;
        
        let result = router.route_tool_call("calculate", serde_json::json!({"expr": "6*7"})).await;
        
        assert!(result.is_ok());
        assert_eq!(result.unwrap(), expected_result);
    }

    #[tokio::test]
    async fn test_route_tool_call_with_multiple_agents_round_robin() {
        let registry = Arc::new(AgentRegistry::new());
        let router = AgentRouter::new(registry.clone());
        
        let url1 = spawn_mock_agent("tool", serde_json::json!({"from": "agent1"})).await;
        let url2 = spawn_mock_agent("tool", serde_json::json!({"from": "agent2"})).await;
        
        registry.register(
            "agent1".to_string(),
            url1,
            vec![ToolInfo { 
                name: "tool".to_string(), 
                description: "Test".to_string(),
                input_schema: serde_json::json!({})
            }]
        ).await;
        
        registry.register(
            "agent2".to_string(),
            url2,
            vec![ToolInfo { 
                name: "tool".to_string(), 
                description: "Test".to_string(),
                input_schema: serde_json::json!({})
            }]
        ).await;
        
        // Make multiple calls - should round-robin between agents
        let result1 = router.route_tool_call("tool", serde_json::json!({})).await;
        let result2 = router.route_tool_call("tool", serde_json::json!({})).await;
        
        assert!(result1.is_ok());
        assert!(result2.is_ok());
        // Both should succeed (exact ordering depends on round-robin state)
    }

    #[tokio::test]
    async fn test_pool_idle_count() {
        let registry = Arc::new(AgentRegistry::new());
        let router = AgentRouter::new(registry.clone());
        
        let url = spawn_mock_agent("tool", serde_json::json!({"ok": true})).await;
        
        registry.register(
            "agent".to_string(),
            url,
            vec![ToolInfo { 
                name: "tool".to_string(), 
                description: "Test".to_string(),
                input_schema: serde_json::json!({})
            }]
        ).await;
        
        assert_eq!(router.pool_idle_count().await, 0);
        
        // Make a call which should acquire and release a connection
        let _ = router.route_tool_call("tool", serde_json::json!({})).await;
        
        // Connection should be returned to pool after successful call
        assert_eq!(router.pool_idle_count().await, 1);
    }
}
