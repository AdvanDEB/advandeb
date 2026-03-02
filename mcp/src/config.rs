use serde::Deserialize;

#[derive(Debug, Clone, Deserialize)]
pub struct Settings {
    #[serde(default = "default_bind")]
    pub bind: String,
    #[serde(default = "default_ollama_host")]
    pub ollama_host: String,
    #[serde(default = "default_ollama_model")]
    pub ollama_model: String,
    #[serde(default = "default_kb_api_base")]
    pub kb_api_base: String,
    #[serde(default = "default_ma_api_base")]
    pub ma_api_base: String,
    #[serde(default = "default_request_timeout")]
    pub request_timeout_seconds: u64,
}

fn default_bind() -> String {
    "0.0.0.0:8080".into()
}

fn default_ollama_host() -> String {
    "http://localhost:11434".into()
}

fn default_ollama_model() -> String {
    "llama2".into()
}

fn default_kb_api_base() -> String {
    "http://localhost:8000".into()
}

fn default_ma_api_base() -> String {
    "http://localhost:9000".into()
}

fn default_request_timeout() -> u64 {
    30
}

impl Settings {
    pub fn load() -> anyhow::Result<Self> {
        Ok(envy::prefixed("ADVANDEB_MCP_").from_env::<Self>()?)
    }
}
