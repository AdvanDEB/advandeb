use once_cell::sync::Lazy;
use prometheus::{
    register_histogram_vec, register_int_counter_vec, register_int_gauge,
    Encoder, HistogramVec, IntCounterVec, IntGauge, TextEncoder,
};

// ── Metric definitions ────────────────────────────────────────────────────────

/// Total tool calls routed, labelled by tool name, agent, and outcome.
pub static TOOL_CALLS: Lazy<IntCounterVec> = Lazy::new(|| {
    register_int_counter_vec!(
        "mcp_tool_calls_total",
        "Total number of tool calls routed by the MCP gateway",
        &["tool", "agent", "status"]
    )
    .expect("register mcp_tool_calls_total")
});

/// Tool call latency histogram (seconds), labelled by tool and agent.
pub static TOOL_LATENCY: Lazy<HistogramVec> = Lazy::new(|| {
    register_histogram_vec!(
        "mcp_tool_latency_seconds",
        "Tool call latency in seconds",
        &["tool", "agent"],
        vec![0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0]
    )
    .expect("register mcp_tool_latency_seconds")
});

/// Workflow runs, labelled by outcome.
pub static WORKFLOW_RUNS: Lazy<IntCounterVec> = Lazy::new(|| {
    register_int_counter_vec!(
        "mcp_workflow_runs_total",
        "Total number of workflow/run calls",
        &["status"]
    )
    .expect("register mcp_workflow_runs_total")
});

/// Current WebSocket client connections (gauge).
pub static WS_CONNECTIONS: Lazy<IntGauge> = Lazy::new(|| {
    register_int_gauge!(
        "mcp_websocket_connections",
        "Current number of active MCP WebSocket connections"
    )
    .expect("register mcp_websocket_connections")
});

/// Current idle pool connections (gauge).
pub static POOL_IDLE: Lazy<IntGauge> = Lazy::new(|| {
    register_int_gauge!(
        "mcp_pool_idle_connections",
        "Current number of idle agent WebSocket connections in the pool"
    )
    .expect("register mcp_pool_idle_connections")
});

// ── Initialise all metrics (force lazy evaluation) ────────────────────────────

pub fn init() {
    Lazy::force(&TOOL_CALLS);
    Lazy::force(&TOOL_LATENCY);
    Lazy::force(&WORKFLOW_RUNS);
    Lazy::force(&WS_CONNECTIONS);
    Lazy::force(&POOL_IDLE);
}

// ── Prometheus text exposition ────────────────────────────────────────────────

/// Render all registered metrics in Prometheus text format.
pub fn render() -> String {
    let encoder = TextEncoder::new();
    let metric_families = prometheus::gather();
    let mut buf = Vec::new();
    encoder.encode(&metric_families, &mut buf).unwrap_or(());
    String::from_utf8(buf).unwrap_or_default()
}
