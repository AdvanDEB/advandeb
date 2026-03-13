use axum::{
    extract::{
        ws::{Message, WebSocket, WebSocketUpgrade},
        State,
    },
    response::Response,
};
use futures_util::{SinkExt, StreamExt};
use std::sync::Arc;
use tracing::{debug, error, info, warn};

use super::protocol::{
    InitializeParams, JsonRpcRequest, JsonRpcResponse, ToolCallParams, INTERNAL_ERROR,
    METHOD_NOT_FOUND, PARSE_ERROR,
};
use crate::gateway::router::AgentRouter;
use crate::metrics;
use crate::workflow::executor::{Workflow, WorkflowExecutor};

/// Axum handler — upgrades HTTP connection to WebSocket.
pub async fn websocket_handler(
    ws: WebSocketUpgrade,
    State(router): State<Arc<AgentRouter>>,
) -> Response {
    ws.on_upgrade(|socket| handle_socket(socket, router))
}

async fn handle_socket(socket: WebSocket, router: Arc<AgentRouter>) {
    metrics::WS_CONNECTIONS.inc();
    let (mut sender, mut receiver) = socket.split();
    info!("New WebSocket MCP client connected");

    while let Some(msg_result) = receiver.next().await {
        let msg = match msg_result {
            Ok(m) => m,
            Err(e) => {
                error!("WebSocket receive error: {e}");
                break;
            }
        };

        match msg {
            Message::Text(text) => {
                debug!("Received MCP message: {text}");
                let response = process_message(&text, &router).await;
                let response_text = serde_json::to_string(&response).unwrap_or_else(|_| {
                    r#"{"jsonrpc":"2.0","error":{"code":-32603,"message":"serialization error"}}"#
                        .into()
                });
                if sender.send(Message::Text(response_text)).await.is_err() {
                    break;
                }
            }
            Message::Close(_) => {
                info!("WebSocket client disconnected");
                break;
            }
            Message::Ping(data) => {
                let _ = sender.send(Message::Pong(data)).await;
            }
            _ => {}
        }
    }
    metrics::WS_CONNECTIONS.dec();
}

async fn process_message(text: &str, router: &Arc<AgentRouter>) -> JsonRpcResponse {
    let req: JsonRpcRequest = match serde_json::from_str(text) {
        Ok(r) => r,
        Err(e) => {
            warn!("Failed to parse MCP message: {e}");
            return JsonRpcResponse::error(None, PARSE_ERROR, format!("Parse error: {e}"));
        }
    };

    let id = req.id.clone();

    match req.method.as_str() {
        "initialize" => handle_initialize(id, req.params).await,
        "tools/list" => handle_tools_list(id, router).await,
        "tools/call" => handle_tools_call(id, req.params, router).await,
        "workflow/run" => handle_workflow_run(id, req.params, router).await,
        other => {
            warn!("Unknown MCP method: {other}");
            JsonRpcResponse::error(id, METHOD_NOT_FOUND, format!("Method not found: {other}"))
        }
    }
}

async fn handle_initialize(
    id: Option<serde_json::Value>,
    params: serde_json::Value,
) -> JsonRpcResponse {
    let _parsed: InitializeParams = match serde_json::from_value(params) {
        Ok(p) => p,
        Err(_) => InitializeParams {
            protocol_version: "1.0".into(),
            client_info: serde_json::Value::Null,
        },
    };

    JsonRpcResponse::success(
        id,
        serde_json::json!({
            "protocolVersion": "1.0",
            "capabilities": { "tools": {}, "workflows": {} },
            "serverInfo": {
                "name": "advandeb-mcp-gateway",
                "version": env!("CARGO_PKG_VERSION")
            }
        }),
    )
}

async fn handle_tools_list(
    id: Option<serde_json::Value>,
    router: &AgentRouter,
) -> JsonRpcResponse {
    let tools = router.all_tools().await;
    JsonRpcResponse::success(id, serde_json::json!({ "tools": tools }))
}

async fn handle_tools_call(
    id: Option<serde_json::Value>,
    params: serde_json::Value,
    router: &AgentRouter,
) -> JsonRpcResponse {
    let call_params: ToolCallParams = match serde_json::from_value(params) {
        Ok(p) => p,
        Err(e) => {
            return JsonRpcResponse::error(id, PARSE_ERROR, format!("Invalid params: {e}"));
        }
    };

    match router
        .route_tool_call(&call_params.name, call_params.arguments)
        .await
    {
        Ok(result) => JsonRpcResponse::success(id, result),
        Err(e) => JsonRpcResponse::error(id, INTERNAL_ERROR, e.to_string()),
    }
}

async fn handle_workflow_run(
    id: Option<serde_json::Value>,
    params: serde_json::Value,
    router: &Arc<AgentRouter>,
) -> JsonRpcResponse {
    let workflow: Workflow = match serde_json::from_value(params) {
        Ok(w) => w,
        Err(e) => {
            return JsonRpcResponse::error(id, PARSE_ERROR, format!("Invalid workflow params: {e}"));
        }
    };

    let executor = WorkflowExecutor::new(Arc::clone(router));
    match executor.run(workflow).await {
        Ok(result) => {
            metrics::WORKFLOW_RUNS.with_label_values(&["ok"]).inc();
            let result_val = serde_json::to_value(result).unwrap_or(serde_json::Value::Null);
            JsonRpcResponse::success(id, result_val)
        }
        Err(e) => {
            metrics::WORKFLOW_RUNS.with_label_values(&["error"]).inc();
            JsonRpcResponse::error(id, INTERNAL_ERROR, e)
        }
    }
}
