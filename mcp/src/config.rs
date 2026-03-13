use serde::Deserialize;
use std::path::Path;

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

    // TLS Configuration
    #[serde(default)]
    pub tls: Option<TlsConfig>,

    // Agent Configuration
    #[serde(default)]
    pub agents: AgentConfig,

    // Connection Pool Configuration
    #[serde(default)]
    pub pool: PoolConfig,

    // Circuit Breaker Configuration
    #[serde(default)]
    pub circuit_breaker: CircuitBreakerConfig,
}

#[derive(Debug, Clone, Deserialize)]
pub struct TlsConfig {
    pub enabled: bool,
    pub cert_path: String,
    pub key_path: String,
}

#[derive(Debug, Clone, Deserialize)]
pub struct AgentConfig {
    #[serde(default = "default_health_check_interval")]
    pub health_check_interval_seconds: u64,
    #[serde(default = "default_max_agents_per_tool")]
    pub max_agents_per_tool: usize,
}

impl Default for AgentConfig {
    fn default() -> Self {
        Self {
            health_check_interval_seconds: default_health_check_interval(),
            max_agents_per_tool: default_max_agents_per_tool(),
        }
    }
}

#[derive(Debug, Clone, Deserialize)]
pub struct PoolConfig {
    #[serde(default = "default_max_idle_per_agent")]
    pub max_idle_per_agent: usize,
    #[serde(default = "default_connection_timeout")]
    pub connection_timeout_seconds: u64,
}

impl Default for PoolConfig {
    fn default() -> Self {
        Self {
            max_idle_per_agent: default_max_idle_per_agent(),
            connection_timeout_seconds: default_connection_timeout(),
        }
    }
}

#[derive(Debug, Clone, Deserialize)]
pub struct CircuitBreakerConfig {
    #[serde(default = "default_failure_threshold")]
    pub failure_threshold: usize,
    #[serde(default = "default_timeout_seconds")]
    pub timeout_seconds: u64,
    #[serde(default = "default_half_open_max_requests")]
    pub half_open_max_requests: usize,
}

impl Default for CircuitBreakerConfig {
    fn default() -> Self {
        Self {
            failure_threshold: default_failure_threshold(),
            timeout_seconds: default_timeout_seconds(),
            half_open_max_requests: default_half_open_max_requests(),
        }
    }
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

fn default_health_check_interval() -> u64 {
    30
}

fn default_max_agents_per_tool() -> usize {
    10
}

fn default_max_idle_per_agent() -> usize {
    5
}

fn default_connection_timeout() -> u64 {
    10
}

fn default_failure_threshold() -> usize {
    5
}

fn default_timeout_seconds() -> u64 {
    30
}

fn default_half_open_max_requests() -> usize {
    3
}

impl Settings {
    /// Load settings from config files and environment variables
    /// Priority (highest to lowest):
    /// 1. Environment variables (ADVANDEB_MCP_*)
    /// 2. config/local.toml
    /// 3. config/default.toml
    /// 4. Built-in defaults
    pub fn load() -> anyhow::Result<Self> {
        // Try to load from config files first
        let mut builder = config::Config::builder();

        // Add default config file if it exists
        if Path::new("config/default.toml").exists() {
            builder = builder.add_source(config::File::with_name("config/default"));
        }

        // Add local config file if it exists (overrides default)
        if Path::new("config/local.toml").exists() {
            builder = builder.add_source(config::File::with_name("config/local"));
        }

        // Add environment variables (highest priority)
        builder = builder.add_source(
            config::Environment::with_prefix("ADVANDEB_MCP")
                .separator("_")
                .try_parsing(true),
        );

        // Build and deserialize
        let config = builder.build()?;
        let settings: Settings = config.try_deserialize()?;

        tracing::info!("Configuration loaded successfully");
        tracing::debug!("Settings: {:?}", settings);

        Ok(settings)
    }

    /// Load settings from environment variables only (fallback mode)
    pub fn load_from_env() -> anyhow::Result<Self> {
        tracing::warn!("Loading configuration from environment variables only");
        Ok(envy::prefixed("ADVANDEB_MCP_").from_env::<Self>()?)
    }
}
