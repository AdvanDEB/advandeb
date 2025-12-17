pub mod config;
pub mod ollama;

use std::{net::SocketAddr, sync::Arc};

use axum::{
    extract::State,
    http::StatusCode,
    routing::{get, post},
    Json, Router,
};
use tracing::{error, info};

use crate::config::Settings;
use crate::ollama::{ChatMessage, OllamaClient, OllamaError};

#[derive(Clone)]
pub struct AppState {
    pub settings: Settings,
    pub ollama: OllamaClient,
}

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
    match state
        .ollama
        .chat(&body.messages, body.model.as_deref())
        .await
    {
        Ok(reply) => Ok(Json(ChatResponseBody { reply })),
        Err(err) => {
            error!(%err, "failed to chat with ollama");
            Err((StatusCode::BAD_GATEWAY, err.to_string()))
        }
    }
}

pub fn build_router(state: Arc<AppState>) -> Router {
    Router::new()
        .route("/health", get(health))
        .route("/chat", post(chat))
        .with_state(state)
}

pub fn build_state(settings: Settings) -> anyhow::Result<Arc<AppState>> {
    let ollama = OllamaClient::new(
        settings.ollama_host.clone(),
        settings.ollama_model.clone(),
        settings.request_timeout_seconds,
    )?;
    Ok(Arc::new(AppState { settings, ollama }))
}

pub async fn serve(settings: Settings) -> anyhow::Result<()> {
    let state = build_state(settings.clone())?;
    let app = build_router(state.clone());
    let addr: SocketAddr = state.settings.bind.parse()?;
    info!(
        listening = %addr,
        ollama_model = %state.settings.ollama_model,
        "Starting AdvanDEB MCP server"
    );
    axum::serve(tokio::net::TcpListener::bind(addr).await?, app).await?;
    Ok(())
}
