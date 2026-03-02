use std::time::Duration;

use reqwest::Client;
use serde::{Deserialize, Serialize};
use thiserror::Error;

#[derive(Debug, Clone)]
pub struct OllamaClient {
    base_url: String,
    default_model: String,
    client: Client,
}

#[derive(Error, Debug)]
pub enum OllamaError {
    #[error("request failed: {0}")]
    Request(#[from] reqwest::Error),
    #[error("malformed response: {0}")]
    Malformed(String),
}

#[derive(Debug, Serialize, Deserialize, Clone)]
pub struct ChatMessage {
    pub role: String,
    pub content: String,
}

#[derive(Serialize)]
struct ChatRequest<'a> {
    model: &'a str,
    messages: &'a [ChatMessage],
}

#[derive(Deserialize)]
struct ChatResponse {
    message: Option<ChatMessage>,
    response: Option<String>,
}

impl OllamaClient {
    pub fn new(base_url: String, default_model: String, timeout_seconds: u64) -> anyhow::Result<Self> {
        let client = Client::builder()
            .timeout(Duration::from_secs(timeout_seconds))
            .build()?;

        Ok(Self {
            base_url: base_url.trim_end_matches('/').to_owned(),
            default_model,
            client,
        })
    }

    pub async fn chat(&self, messages: &[ChatMessage], model: Option<&str>) -> Result<String, OllamaError> {
        let model = model.unwrap_or(&self.default_model);
        let req = ChatRequest { model, messages };

        let res = self
            .client
            .post(format!("{}/api/chat", self.base_url))
            .json(&req)
            .send()
            .await?;

        let payload: ChatResponse = res.json().await?;
        if let Some(msg) = payload.message {
            return Ok(msg.content);
        }
        if let Some(content) = payload.response {
            return Ok(content);
        }
        Err(OllamaError::Malformed("no content in response".into()))
    }
}
