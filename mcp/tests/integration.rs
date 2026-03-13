use advandeb_mcp::{build_state, config::Settings, gateway::registry::AgentStatus};
use axum::{
    extract::ws::{Message, WebSocket, WebSocketUpgrade},
    response::IntoResponse,
    routing::get,
    Router,
};
use futures_util::StreamExt;
use serde_json::json;
use std::net::SocketAddr;
use tokio::net::TcpListener;

/// Mock agent server that responds to MCP protocol messages
async fn mock_agent_handler(ws: WebSocketUpgrade) -> impl IntoResponse {
    ws.on_upgrade(handle_mock_agent_socket)
}

async fn handle_mock_agent_socket(mut socket: WebSocket) {
    while let Some(Ok(msg)) = socket.next().await {
        if let Message::Text(text) = msg {
            // Parse JSON-RPC request
            if let Ok(request) = serde_json::from_str::<serde_json::Value>(&text) {
                let method = request["method"].as_str().unwrap_or("");
                let id = request.get("id").cloned();
                
                let response = match method {
                    "tools/list" => {
                        json!({
                            "jsonrpc": "2.0",
                            "id": id,
                            "result": {
                                "tools": [
                                    {
                                        "name": "mock_tool",
                                        "description": "A mock tool for testing",
                                        "inputSchema": {}
                                    }
                                ]
                            }
                        })
                    }
                    "tools/call" => {
                        let params = &request["params"];
                        json!({
                            "jsonrpc": "2.0",
                            "id": id,
                            "result": {
                                "success": true,
                                "tool": params["name"],
                                "arguments": params["arguments"]
                            }
                        })
                    }
                    "ping" => {
                        json!({
                            "jsonrpc": "2.0",
                            "id": id,
                            "result": "pong"
                        })
                    }
                    _ => {
                        json!({
                            "jsonrpc": "2.0",
                            "id": id,
                            "error": {
                                "code": -32601,
                                "message": "Method not found"
                            }
                        })
                    }
                };
                
                if let Ok(response_text) = serde_json::to_string(&response) {
                    let _ = socket.send(Message::Text(response_text)).await;
                }
            }
        }
    }
}

/// Start a mock agent server on the given port
async fn start_mock_agent(port: u16) -> Result<(), Box<dyn std::error::Error>> {
    let app = Router::new().route("/", get(mock_agent_handler));
    let addr = SocketAddr::from(([127, 0, 0, 1], port));
    let listener = TcpListener::bind(addr).await?;
    
    axum::serve(listener, app).await?;
    Ok(())
}

#[tokio::test]
async fn test_gateway_with_mock_agent() {
    // Start mock agent server
    tokio::spawn(async {
        let _ = start_mock_agent(18081).await;
    });
    
    // Give the mock agent time to start
    tokio::time::sleep(tokio::time::Duration::from_millis(100)).await;
    
    // Build gateway state
    let mut settings = Settings::load().unwrap_or_else(|_| {
        // Fallback to defaults if config fails
        Settings::load_from_env().unwrap()
    });
    settings.bind = "127.0.0.1:18080".to_string();
    
    let state = build_state(settings).expect("Should build state");
    
    // Register the mock agent
    state
        .router
        .registry
        .register(
            "mock_agent".to_string(),
            "ws://127.0.0.1:18081".to_string(),
            vec![advandeb_mcp::mcp::protocol::ToolInfo {
                name: "mock_tool".to_string(),
                description: "A mock tool".to_string(),
                input_schema: json!({}),
            }],
        )
        .await;
    
    // Verify agent is registered
    let agents = state.router.registry.list().await;
    assert_eq!(agents.len(), 1);
    assert_eq!(agents[0].name, "mock_agent");
    
    // Test tool listing
    let tools = state.router.all_tools().await;
    assert!(!tools.is_empty());
}

#[tokio::test]
async fn test_agent_registration_and_deregistration() {
    let settings = Settings::load().unwrap_or_else(|_| Settings::load_from_env().unwrap());
    let state = build_state(settings).expect("Should build state");
    
    // Register an agent
    state
        .router
        .registry
        .register(
            "test_agent".to_string(),
            "ws://localhost:8081".to_string(),
            vec![],
        )
        .await;
    
    // Verify registration
    let agents = state.router.registry.list().await;
    assert_eq!(agents.len(), 1);
    
    // Deregister the agent
    state.router.registry.deregister("test_agent").await;
    
    // Verify deregistration
    let agents = state.router.registry.list().await;
    assert_eq!(agents.len(), 0);
}

#[tokio::test]
async fn test_multiple_agents_registration() {
    let settings = Settings::load().unwrap_or_else(|_| Settings::load_from_env().unwrap());
    let state = build_state(settings).expect("Should build state");
    
    // Register multiple agents
    for i in 1..=3 {
        state
            .router
            .registry
            .register(
                format!("agent_{}", i),
                format!("ws://localhost:808{}", i),
                vec![advandeb_mcp::mcp::protocol::ToolInfo {
                    name: format!("tool_{}", i),
                    description: format!("Tool {}", i),
                    input_schema: json!({}),
                }],
            )
            .await;
    }
    
    // Verify all agents are registered
    let agents = state.router.registry.list().await;
    assert_eq!(agents.len(), 3);
    
    // Verify tools are available
    let tools = state.router.all_tools().await;
    assert_eq!(tools.len(), 3);
}

#[tokio::test]
async fn test_agent_health_status() {
    let settings = Settings::load().unwrap_or_else(|_| Settings::load_from_env().unwrap());
    let state = build_state(settings).expect("Should build state");
    
    // Register an agent
    state
        .router
        .registry
        .register(
            "health_test_agent".to_string(),
            "ws://localhost:9999".to_string(),
            vec![],
        )
        .await;
    
    // Get agent info
    let agents = state.router.registry.list().await;
    assert_eq!(agents.len(), 1);
    
    // Agent should initially be marked as Healthy or Unavailable
    // (Unavailable is expected since we're connecting to a non-existent server)
    assert!(
        matches!(agents[0].status, AgentStatus::Healthy | AgentStatus::Unavailable),
        "Agent should be Healthy or Unavailable initially"
    );
}
