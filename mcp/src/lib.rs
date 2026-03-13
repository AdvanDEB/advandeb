//! # AdvanDEB MCP Gateway
//!
//! The MCP (Model Context Protocol) Gateway is a Rust-based WebSocket server that
//! routes tool calls from clients to registered agent servers. It provides:
//!
//! - **Agent Registry**: Dynamic agent discovery and health monitoring
//! - **Tool Routing**: Intelligent routing of tool calls to appropriate agents
//! - **Load Balancing**: Round-robin distribution across agent replicas
//! - **Resilience**: Circuit breakers, retries, and connection pooling
//! - **Workflows**: Multi-step orchestration with context passing
//! - **Observability**: Prometheus metrics and structured logging
//! - **Security**: Optional TLS/HTTPS support
//!
//! ## Quick Start
//!
//! ```no_run
//! use advandeb_mcp::{config::Settings, serve};
//!
//! #[tokio::main]
//! async fn main() -> anyhow::Result<()> {
//!     // Load configuration from files and environment
//!     let settings = Settings::load()?;
//!     
//!     // Start the gateway server
//!     serve(settings).await
//! }
//! ```
//!
//! ## Architecture
//!
//! The gateway consists of several key components:
//!
//! - **MCP Protocol** (`mcp` module): JSON-RPC 2.0 WebSocket protocol implementation
//! - **Gateway** (`gateway` module): Agent registry, routing, load balancing, resilience
//! - **Workflow** (`workflow` module): Multi-step workflow orchestration
//! - **Metrics** (`metrics` module): Prometheus metrics for observability
//!
//! ## Configuration
//!
//! See [`config::Settings`] for configuration options. Configuration can be provided via:
//! - Config files (`config/default.toml`, `config/local.toml`)
//! - Environment variables (prefix: `ADVANDEB_MCP_`)
//!
//! ## Endpoints
//!
//! ### REST Endpoints
//! - `GET /health` - Health check
//! - `GET /agents` - List registered agents
//! - `POST /agents` - Register a new agent
//! - `DELETE /agents/:name` - Deregister an agent
//! - `GET /tools` - List all available tools
//! - `GET /metrics` - Prometheus metrics
//!
//! ### WebSocket Endpoints
//! - `GET /mcp` - MCP protocol WebSocket connection

pub mod config;
pub mod gateway;
pub mod mcp;
pub mod metrics;
pub mod ollama;
pub mod workflow;

use std::{net::SocketAddr, sync::Arc, time::Duration};

use axum::{
    extract::State,
    http::StatusCode,
    response::IntoResponse,
    routing::{delete, get, post},
    Json, Router,
};
use tracing::{error, info};

use crate::config::Settings;
use crate::gateway::{registry::AgentRegistry, router::AgentRouter};
use crate::mcp::protocol::ToolInfo;
use crate::ollama::{ChatMessage, OllamaClient};

// ── Shared application state ────────────────────────────────────────────────

/// Shared application state passed to all HTTP handlers.
///
/// Contains the configuration, Ollama client, and agent router. This state is
/// wrapped in `Arc` and cloned for each request.
#[derive(Clone)]
pub struct AppState {
    /// Application configuration loaded from files/environment
    pub settings: Settings,
    /// Client for communicating with Ollama LLM
    pub ollama: OllamaClient,
    /// Agent router for tool call routing and load balancing
    pub router: Arc<AgentRouter>,
}

// ── HTTP handler types ───────────────────────────────────────────────────────

#[derive(serde::Serialize)]
struct HealthResponse {
    status: &'static str,
    ollama_model: String,
}

#[derive(serde::Deserialize)]
struct ChatRequestBody {
    messages: Vec<ChatMessage>,
    model: Option<String>,
}

#[derive(serde::Serialize)]
struct ChatResponseBody {
    reply: String,
}

/// Body expected by `POST /agents`
#[derive(serde::Deserialize)]
struct RegisterAgentBody {
    name: String,
    websocket_url: String,
    tools: Vec<ToolInfo>,
}

// ── Handlers ─────────────────────────────────────────────────────────────────

async fn health(State(state): State<Arc<AppState>>) -> Json<HealthResponse> {
    Json(HealthResponse {
        status: "ok",
        ollama_model: state.settings.ollama_model.clone(),
    })
}

async fn chat(
    State(state): State<Arc<AppState>>,
    Json(body): Json<ChatRequestBody>,
) -> Result<Json<ChatResponseBody>, (StatusCode, String)> {
    match state.ollama.chat(&body.messages, body.model.as_deref()).await {
        Ok(reply) => Ok(Json(ChatResponseBody { reply })),
        Err(err) => {
            error!(%err, "failed to chat with ollama");
            Err((StatusCode::BAD_GATEWAY, err.to_string()))
        }
    }
}

/// `GET /agents` — list all registered agents
async fn list_agents(State(state): State<Arc<AppState>>) -> Json<serde_json::Value> {
    let agents = state.router.registry.list().await;
    Json(serde_json::json!({ "agents": agents }))
}

/// `POST /agents` — register a new agent (body: `{ name, websocket_url, tools }`)
async fn register_agent(
    State(state): State<Arc<AppState>>,
    Json(body): Json<RegisterAgentBody>,
) -> (StatusCode, Json<serde_json::Value>) {
    state
        .router
        .registry
        .register(body.name.clone(), body.websocket_url, body.tools)
        .await;
    (
        StatusCode::CREATED,
        Json(serde_json::json!({ "status": "registered", "name": body.name })),
    )
}

/// `DELETE /agents/:name` — deregister an agent
async fn deregister_agent(
    State(state): State<Arc<AppState>>,
    axum::extract::Path(name): axum::extract::Path<String>,
) -> Json<serde_json::Value> {
    state.router.registry.deregister(&name).await;
    Json(serde_json::json!({ "status": "deregistered", "name": name }))
}

/// `GET /tools` — list all tools across registered agents
async fn list_tools(State(state): State<Arc<AppState>>) -> Json<serde_json::Value> {
    let tools = state.router.all_tools().await;
    Json(serde_json::json!({ "tools": tools }))
}

/// `GET /pool/stats` — debug: idle connection counts
async fn pool_stats(State(state): State<Arc<AppState>>) -> Json<serde_json::Value> {
    let idle = state.router.pool_idle_count().await;
    // Keep pool gauge in sync
    metrics::POOL_IDLE.set(idle as i64);
    Json(serde_json::json!({ "idle_connections": idle }))
}

/// `GET /metrics` — Prometheus text format metrics
async fn prometheus_metrics() -> impl IntoResponse {
    (
        [(axum::http::header::CONTENT_TYPE, "text/plain; version=0.0.4")],
        metrics::render(),
    )
}

// ── Router builder ────────────────────────────────────────────────────────────

/// Build the Axum router with all endpoints configured.
///
/// This creates a router with REST endpoints for agent management, tool listing,
/// health checks, and metrics, plus a WebSocket endpoint for the MCP protocol.
///
/// # Arguments
///
/// * `state` - Application state to be shared across handlers
///
/// # Returns
///
/// Configured `Router` ready to be served
pub fn build_router(state: Arc<AppState>) -> Router {
    Router::new()
        // Legacy / Ollama endpoints
        .route("/health", get(health))
        .route("/chat", post(chat))
        // Agent management (REST)
        .route("/agents", get(list_agents).post(register_agent))
        .route("/agents/:name", delete(deregister_agent))
        // Tool listing (REST)
        .route("/tools", get(list_tools))
        // Debug / observability
        .route("/pool/stats", get(pool_stats))
        .route("/metrics", get(prometheus_metrics))
        // MCP WebSocket endpoint — state needs the AgentRouter
        .route(
            "/mcp",
            get(mcp::server::websocket_handler).with_state(state.router.clone()),
        )
        .with_state(state)
}

/// Build the application state from settings.
///
/// Creates the Ollama client, agent registry, and router from the provided settings.
///
/// # Arguments
///
/// * `settings` - Configuration settings
///
/// # Returns
///
/// * `Ok(Arc<AppState>)` - Shared application state
/// * `Err(anyhow::Error)` - If initialization fails
pub fn build_state(settings: Settings) -> anyhow::Result<Arc<AppState>> {
    let ollama = OllamaClient::new(
        settings.ollama_host.clone(),
        settings.ollama_model.clone(),
        settings.request_timeout_seconds,
    )?;
    let registry = Arc::new(AgentRegistry::new());
    let router = Arc::new(AgentRouter::new(registry));
    Ok(Arc::new(AppState { settings, ollama, router }))
}

/// Start the MCP Gateway server.
///
/// This is the main entry point for running the gateway. It:
/// - Initializes metrics collection
/// - Builds the application state
/// - Starts background health monitoring
/// - Binds to the configured address (HTTP or HTTPS)
/// - Serves incoming requests
///
/// # Arguments
///
/// * `settings` - Configuration settings for the gateway
///
/// # Returns
///
/// * `Ok(())` - Server ran successfully (unreachable in normal operation)
/// * `Err(anyhow::Error)` - If server startup or operation fails
///
/// # Examples
///
/// ```no_run
/// use advandeb_mcp::{config::Settings, serve};
///
/// #[tokio::main]
/// async fn main() -> anyhow::Result<()> {
///     let settings = Settings::load()?;
///     serve(settings).await
/// }
/// ```
pub async fn serve(settings: Settings) -> anyhow::Result<()> {
    metrics::init();
    let state = build_state(settings.clone())?;

    // Start background health monitoring (configurable interval)
    let health_interval = Duration::from_secs(settings.agents.health_check_interval_seconds);
    state
        .router
        .registry
        .start_health_monitoring(health_interval);

    let app = build_router(state.clone());
    let addr: SocketAddr = state.settings.bind.parse()?;
    
    // Check if TLS is enabled
    if let Some(tls_config) = &state.settings.tls {
        if tls_config.enabled {
            info!(
                listening = %addr,
                tls = "enabled",
                cert = %tls_config.cert_path,
                ollama_model = %state.settings.ollama_model,
                "Starting AdvanDEB MCP Gateway with TLS"
            );
            
            // Load TLS configuration
            let tls_server_config = axum_server::tls_rustls::RustlsConfig::from_pem_file(
                &tls_config.cert_path,
                &tls_config.key_path,
            )
            .await?;
            
            // Start HTTPS server
            axum_server::bind_rustls(addr, tls_server_config)
                .serve(app.into_make_service())
                .await?;
        } else {
            info!(
                listening = %addr,
                tls = "disabled (configured but not enabled)",
                ollama_model = %state.settings.ollama_model,
                "Starting AdvanDEB MCP Gateway"
            );
            axum::serve(tokio::net::TcpListener::bind(addr).await?, app).await?;
        }
    } else {
        info!(
            listening = %addr,
            tls = "not configured",
            ollama_model = %state.settings.ollama_model,
            "Starting AdvanDEB MCP Gateway"
        );
        axum::serve(tokio::net::TcpListener::bind(addr).await?, app).await?;
    }
    
    Ok(())
}
