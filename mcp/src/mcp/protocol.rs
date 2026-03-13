use serde::{Deserialize, Serialize};
use serde_json::Value;

/// JSON-RPC 2.0 request envelope (inbound from clients/agents)
#[derive(Debug, Deserialize)]
pub struct JsonRpcRequest {
    #[allow(dead_code)]
    pub jsonrpc: Option<String>,
    pub id: Option<Value>,
    pub method: String,
    #[serde(default)]
    pub params: Value,
}

/// JSON-RPC 2.0 response envelope
#[derive(Debug, Serialize)]
pub struct JsonRpcResponse {
    pub jsonrpc: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub id: Option<Value>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub result: Option<Value>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub error: Option<JsonRpcError>,
}

impl JsonRpcResponse {
    pub fn success(id: Option<Value>, result: Value) -> Self {
        Self {
            jsonrpc: "2.0".into(),
            id,
            result: Some(result),
            error: None,
        }
    }

    pub fn error(id: Option<Value>, code: i32, message: impl Into<String>) -> Self {
        Self {
            jsonrpc: "2.0".into(),
            id,
            result: None,
            error: Some(JsonRpcError {
                code,
                message: message.into(),
                data: None,
            }),
        }
    }
}

#[derive(Debug, Serialize)]
pub struct JsonRpcError {
    pub code: i32,
    pub message: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub data: Option<Value>,
}

// Well-known JSON-RPC error codes
pub const PARSE_ERROR: i32 = -32700;
pub const METHOD_NOT_FOUND: i32 = -32601;
pub const INTERNAL_ERROR: i32 = -32603;

/// Params for tools/call
#[derive(Debug, Deserialize)]
pub struct ToolCallParams {
    pub name: String,
    #[serde(default)]
    pub arguments: Value,
}

/// Params for agent/register (HTTP REST endpoint — not a WS message)
#[derive(Debug, Deserialize, Serialize)]
pub struct AgentRegisterParams {
    pub name: String,
    pub websocket_url: String,
}

/// Info about a single tool exposed by an agent
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ToolInfo {
    pub name: String,
    pub description: String,
    #[serde(rename = "inputSchema", default)]
    pub input_schema: Value,
}

/// Params for initialize handshake
#[derive(Debug, Deserialize)]
pub struct InitializeParams {
    #[serde(rename = "protocolVersion", default)]
    pub protocol_version: String,
    #[serde(rename = "clientInfo", default)]
    pub client_info: Value,
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn test_jsonrpc_request_deserialize() {
        let json = r#"{
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": "test_tool", "arguments": {"arg1": "value1"}}
        }"#;

        let req: JsonRpcRequest = serde_json::from_str(json).unwrap();
        assert_eq!(req.method, "tools/call");
        assert_eq!(req.id, Some(json!(1)));
    }

    #[test]
    fn test_jsonrpc_request_without_params() {
        let json = r#"{
            "method": "tools/list"
        }"#;

        let req: JsonRpcRequest = serde_json::from_str(json).unwrap();
        assert_eq!(req.method, "tools/list");
        assert_eq!(req.params, json!(null));
    }

    #[test]
    fn test_jsonrpc_response_success() {
        let response = JsonRpcResponse::success(Some(json!(1)), json!({"result": "ok"}));

        assert_eq!(response.jsonrpc, "2.0");
        assert_eq!(response.id, Some(json!(1)));
        assert!(response.result.is_some());
        assert!(response.error.is_none());

        let serialized = serde_json::to_string(&response).unwrap();
        assert!(serialized.contains("\"result\""));
        assert!(!serialized.contains("\"error\""));
    }

    #[test]
    fn test_jsonrpc_response_error() {
        let response = JsonRpcResponse::error(Some(json!(2)), METHOD_NOT_FOUND, "Method not found");

        assert_eq!(response.jsonrpc, "2.0");
        assert_eq!(response.id, Some(json!(2)));
        assert!(response.result.is_none());
        assert!(response.error.is_some());

        let error = response.error.unwrap();
        assert_eq!(error.code, METHOD_NOT_FOUND);
        assert_eq!(error.message, "Method not found");
    }

    #[test]
    fn test_tool_call_params_deserialize() {
        let json = r#"{
            "name": "semantic_search",
            "arguments": {"query": "test query", "limit": 10}
        }"#;

        let params: ToolCallParams = serde_json::from_str(json).unwrap();
        assert_eq!(params.name, "semantic_search");
        assert_eq!(params.arguments["query"], "test query");
        assert_eq!(params.arguments["limit"], 10);
    }

    #[test]
    fn test_tool_call_params_without_arguments() {
        let json = r#"{"name": "ping"}"#;

        let params: ToolCallParams = serde_json::from_str(json).unwrap();
        assert_eq!(params.name, "ping");
        assert_eq!(params.arguments, json!(null));
    }

    #[test]
    fn test_tool_info_serialize_deserialize() {
        let tool = ToolInfo {
            name: "test_tool".to_string(),
            description: "A test tool".to_string(),
            input_schema: json!({
                "type": "object",
                "properties": {
                    "query": {"type": "string"}
                }
            }),
        };

        let serialized = serde_json::to_string(&tool).unwrap();
        let deserialized: ToolInfo = serde_json::from_str(&serialized).unwrap();

        assert_eq!(deserialized.name, "test_tool");
        assert_eq!(deserialized.description, "A test tool");
        assert!(deserialized.input_schema.is_object());
    }

    #[test]
    fn test_initialize_params_deserialize() {
        let json = r#"{
            "protocolVersion": "2024-11-05",
            "clientInfo": {"name": "test-client", "version": "1.0"}
        }"#;

        let params: InitializeParams = serde_json::from_str(json).unwrap();
        assert_eq!(params.protocol_version, "2024-11-05");
        assert_eq!(params.client_info["name"], "test-client");
    }

    #[test]
    fn test_agent_register_params_serialize_deserialize() {
        let params = AgentRegisterParams {
            name: "retrieval_agent".to_string(),
            websocket_url: "ws://localhost:8081".to_string(),
        };

        let serialized = serde_json::to_string(&params).unwrap();
        let deserialized: AgentRegisterParams = serde_json::from_str(&serialized).unwrap();

        assert_eq!(deserialized.name, "retrieval_agent");
        assert_eq!(deserialized.websocket_url, "ws://localhost:8081");
    }

    #[test]
    fn test_error_codes() {
        assert_eq!(PARSE_ERROR, -32700);
        assert_eq!(METHOD_NOT_FOUND, -32601);
        assert_eq!(INTERNAL_ERROR, -32603);
    }
}
