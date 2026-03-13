use std::sync::atomic::{AtomicUsize, Ordering};

use crate::gateway::registry::AgentInfo;

/// Stateless round-robin selector over a slice of agents.
///
/// The counter is shared across calls so distribution is balanced even across
/// concurrent requests.  Wrapping on overflow is harmless.
pub struct RoundRobinBalancer {
    counter: AtomicUsize,
}

impl RoundRobinBalancer {
    pub fn new() -> Self {
        Self {
            counter: AtomicUsize::new(0),
        }
    }

    /// Pick one agent from `candidates`.  Returns `None` if the list is empty.
    pub fn pick<'a>(&self, candidates: &'a [AgentInfo]) -> Option<&'a AgentInfo> {
        if candidates.is_empty() {
            return None;
        }
        let idx = self.counter.fetch_add(1, Ordering::Relaxed) % candidates.len();
        Some(&candidates[idx])
    }
}

// ── Tests ─────────────────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;
    use crate::gateway::registry::{AgentInfo, AgentStatus};
    use std::time::SystemTime;

    fn fake_agent(name: &str) -> AgentInfo {
        AgentInfo {
            name: name.into(),
            websocket_url: format!("ws://localhost:808{}", name.len()),
            tools: vec![],
            status: AgentStatus::Healthy,
            registered_at: SystemTime::now(),
            last_health_check: SystemTime::now(),
        }
    }

    #[test]
    fn empty_candidates_returns_none() {
        let lb = RoundRobinBalancer::new();
        assert!(lb.pick(&[]).is_none());
    }

    #[test]
    fn single_agent_always_selected() {
        let lb = RoundRobinBalancer::new();
        let agents = vec![fake_agent("a")];
        for _ in 0..5 {
            assert_eq!(lb.pick(&agents).unwrap().name, "a");
        }
    }

    #[test]
    fn distributes_across_replicas() {
        let lb = RoundRobinBalancer::new();
        let agents = vec![fake_agent("a"), fake_agent("bb"), fake_agent("ccc")];
        let picks: Vec<_> = (0..9).map(|_| lb.pick(&agents).unwrap().name.clone()).collect();
        // Each agent should appear exactly 3 times out of 9
        assert_eq!(picks.iter().filter(|n| *n == "a").count(), 3);
        assert_eq!(picks.iter().filter(|n| *n == "bb").count(), 3);
        assert_eq!(picks.iter().filter(|n| *n == "ccc").count(), 3);
    }
}
