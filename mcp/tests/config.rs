use advandeb_mcp::config::Settings;
use std::sync::{Mutex, MutexGuard};

/// Tests in this binary run on parallel threads but share one process
/// environment, so any test that reads or writes `ADVANDEB_MCP_*` variables
/// (every `Settings::load()` does) takes this lock first.
static ENV_LOCK: Mutex<()> = Mutex::new(());

fn env_lock() -> MutexGuard<'static, ()> {
    // A panicking test poisons the lock; the environment is still usable.
    ENV_LOCK.lock().unwrap_or_else(|e| e.into_inner())
}

/// Test that configuration loads correctly from files
#[test]
fn test_config_loading() {
    let _env = env_lock();

    // Test loading default config (should succeed even without files)
    let settings = Settings::load();
    assert!(settings.is_ok(), "Settings should load with defaults");

    let settings = settings.unwrap();
    // Note: If config/default.toml exists, it will be loaded
    // We just verify that settings load successfully and have reasonable values
    assert!(!settings.bind.is_empty());
    assert!(!settings.ollama_model.is_empty());
}

/// Test that an environment variable overrides the config files
#[test]
fn test_env_config() {
    let _env = env_lock();

    std::env::set_var("ADVANDEB_MCP_BIND", "127.0.0.1:9999");
    let settings = Settings::load();
    std::env::remove_var("ADVANDEB_MCP_BIND");

    let settings = settings.expect("Should load from env");
    assert_eq!(settings.bind, "127.0.0.1:9999");
}

/// Test TLS configuration structure
#[test]
fn test_tls_config_structure() {
    use advandeb_mcp::config::TlsConfig;

    let tls_config = TlsConfig {
        enabled: true,
        cert_path: "certs/cert.pem".to_string(),
        key_path: "certs/key.pem".to_string(),
    };

    assert!(tls_config.enabled);
    assert_eq!(tls_config.cert_path, "certs/cert.pem");
    assert_eq!(tls_config.key_path, "certs/key.pem");
}

/// Test that server can start (but don't actually bind to avoid port conflicts)
#[test]
fn test_build_state() {
    let _env = env_lock();

    let settings = Settings::load().expect("Settings should load");
    let state = advandeb_mcp::build_state(settings);

    assert!(state.is_ok(), "Should be able to build app state");
}

/// Test configuration validation
#[test]
fn test_config_defaults() {
    let _env = env_lock();

    let settings = Settings::load().expect("Settings should load");

    // Verify default values
    assert!(settings.request_timeout_seconds > 0);
    assert!(settings.agents.health_check_interval_seconds > 0);
    assert!(settings.pool.max_idle_per_agent > 0);
    assert!(settings.circuit_breaker.failure_threshold > 0);
}
