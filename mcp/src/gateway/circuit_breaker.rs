use std::{
    collections::HashMap,
    sync::Arc,
    time::{Duration, Instant},
};

use tokio::sync::Mutex;
use tracing::{info, warn};

/// Circuit-breaker states.
#[derive(Debug, Clone, PartialEq)]
enum State {
    /// Normal operation — requests pass through.
    Closed,
    /// Too many failures — requests are rejected immediately.
    Open { opened_at: Instant },
    /// Cooldown elapsed — one probe request is allowed through.
    HalfOpen,
}

/// Per-agent circuit breaker state.
struct BreakerState {
    state: State,
    failure_count: u32,
}

/// Configuration for all circuit breakers managed by this registry.
pub struct BreakerConfig {
    /// Number of consecutive failures that trips the breaker.
    pub failure_threshold: u32,
    /// How long the breaker stays Open before transitioning to HalfOpen.
    pub open_timeout: Duration,
}

impl Default for BreakerConfig {
    fn default() -> Self {
        Self {
            failure_threshold: 5,
            open_timeout: Duration::from_secs(30),
        }
    }
}

/// A collection of named circuit breakers, one per agent.
#[derive(Clone)]
pub struct CircuitBreakerRegistry {
    breakers: Arc<Mutex<HashMap<String, BreakerState>>>,
    config: Arc<BreakerConfig>,
}

impl CircuitBreakerRegistry {
    pub fn new(config: BreakerConfig) -> Self {
        Self {
            breakers: Arc::new(Mutex::new(HashMap::new())),
            config: Arc::new(config),
        }
    }

    /// Returns `true` if a request to `agent_name` should be allowed through.
    pub async fn allow(&self, agent_name: &str) -> bool {
        let mut breakers = self.breakers.lock().await;
        let entry = breakers.entry(agent_name.to_string()).or_insert(BreakerState {
            state: State::Closed,
            failure_count: 0,
        });

        match &entry.state {
            State::Closed => true,
            State::Open { opened_at } => {
                if opened_at.elapsed() >= self.config.open_timeout {
                    info!("Circuit breaker for '{}' → HalfOpen", agent_name);
                    entry.state = State::HalfOpen;
                    true
                } else {
                    false
                }
            }
            State::HalfOpen => true,
        }
    }

    /// Record a successful call — resets failure count and closes the breaker.
    pub async fn record_success(&self, agent_name: &str) {
        let mut breakers = self.breakers.lock().await;
        if let Some(entry) = breakers.get_mut(agent_name) {
            if entry.state == State::HalfOpen {
                info!("Circuit breaker for '{}' → Closed (probe succeeded)", agent_name);
            }
            entry.state = State::Closed;
            entry.failure_count = 0;
        }
    }

    /// Record a failed call — increments failure count and may trip the breaker.
    pub async fn record_failure(&self, agent_name: &str) {
        let mut breakers = self.breakers.lock().await;
        let entry = breakers.entry(agent_name.to_string()).or_insert(BreakerState {
            state: State::Closed,
            failure_count: 0,
        });

        entry.failure_count += 1;

        match &entry.state {
            State::Closed if entry.failure_count >= self.config.failure_threshold => {
                warn!(
                    "Circuit breaker for '{}' → Open ({} failures)",
                    agent_name, entry.failure_count
                );
                entry.state = State::Open { opened_at: Instant::now() };
            }
            State::HalfOpen => {
                // Probe failed — reopen immediately
                warn!("Circuit breaker for '{}' probe failed → Open again", agent_name);
                entry.state = State::Open { opened_at: Instant::now() };
                entry.failure_count = 0;
            }
            _ => {}
        }
    }

    /// Is the circuit currently open (rejecting requests) for `agent_name`?
    pub async fn is_open(&self, agent_name: &str) -> bool {
        let breakers = self.breakers.lock().await;
        matches!(
            breakers.get(agent_name).map(|e| &e.state),
            Some(State::Open { .. })
        )
    }
}

// ── Tests ─────────────────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;

    fn cfg(threshold: u32, timeout_secs: u64) -> BreakerConfig {
        BreakerConfig {
            failure_threshold: threshold,
            open_timeout: Duration::from_secs(timeout_secs),
        }
    }

    #[tokio::test]
    async fn starts_closed_allows_requests() {
        let cb = CircuitBreakerRegistry::new(cfg(3, 30));
        assert!(cb.allow("agent").await);
    }

    #[tokio::test]
    async fn trips_after_threshold_failures() {
        let cb = CircuitBreakerRegistry::new(cfg(3, 30));
        for _ in 0..3 {
            cb.record_failure("agent").await;
        }
        assert!(!cb.allow("agent").await);
        assert!(cb.is_open("agent").await);
    }

    #[tokio::test]
    async fn success_resets_failure_count() {
        let cb = CircuitBreakerRegistry::new(cfg(3, 30));
        cb.record_failure("agent").await;
        cb.record_failure("agent").await;
        cb.record_success("agent").await;
        // Two failures then a reset — should still be Closed
        assert!(cb.allow("agent").await);
        assert!(!cb.is_open("agent").await);
    }

    #[tokio::test]
    async fn half_open_after_timeout() {
        let cb = CircuitBreakerRegistry::new(BreakerConfig {
            failure_threshold: 1,
            open_timeout: Duration::from_millis(10), // very short for test
        });
        cb.record_failure("agent").await;
        assert!(!cb.allow("agent").await); // Open immediately

        tokio::time::sleep(Duration::from_millis(15)).await;
        assert!(cb.allow("agent").await); // Now HalfOpen → allowed
    }

    #[tokio::test]
    async fn half_open_probe_success_closes() {
        let cb = CircuitBreakerRegistry::new(BreakerConfig {
            failure_threshold: 1,
            open_timeout: Duration::from_millis(10),
        });
        cb.record_failure("agent").await;
        tokio::time::sleep(Duration::from_millis(15)).await;
        cb.allow("agent").await; // Transition to HalfOpen
        cb.record_success("agent").await;
        assert!(!cb.is_open("agent").await);
        assert!(cb.allow("agent").await);
    }

    #[tokio::test]
    async fn half_open_probe_failure_reopens() {
        let cb = CircuitBreakerRegistry::new(BreakerConfig {
            failure_threshold: 1,
            open_timeout: Duration::from_millis(10),
        });
        cb.record_failure("agent").await;
        tokio::time::sleep(Duration::from_millis(15)).await;
        cb.allow("agent").await; // HalfOpen
        cb.record_failure("agent").await; // Probe fails → reopen
        assert!(cb.is_open("agent").await);
    }
}
