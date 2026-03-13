use criterion::{black_box, criterion_group, criterion_main, Criterion, BenchmarkId};
use advandeb_mcp::gateway::{
    balancer::RoundRobinBalancer,
    registry::{AgentRegistry, AgentInfo, AgentStatus},
    circuit_breaker::{CircuitBreakerRegistry, BreakerConfig},
};
use advandeb_mcp::mcp::protocol::ToolInfo;
use std::sync::Arc;
use std::time::SystemTime;
use tokio::runtime::Runtime;

// Benchmark agent registration
fn bench_agent_registration(c: &mut Criterion) {
    let rt = Runtime::new().unwrap();
    
    c.bench_function("agent_registration", |b| {
        b.iter(|| {
            rt.block_on(async {
                let registry = AgentRegistry::new();
                
                registry.register(
                    black_box("test-agent".to_string()),
                    black_box("ws://localhost:9001".to_string()),
                    black_box(vec![
                        ToolInfo {
                            name: "tool1".to_string(),
                            description: "Test tool".to_string(),
                            input_schema: serde_json::json!({}),
                        }
                    ])
                ).await;
            });
        });
    });
}

// Benchmark tool lookup
fn bench_tool_lookup(c: &mut Criterion) {
    let rt = Runtime::new().unwrap();
    let registry = Arc::new(AgentRegistry::new());
    
    // Setup: register multiple agents
    rt.block_on(async {
        for i in 0..10 {
            registry.register(
                format!("agent-{}", i),
                format!("ws://localhost:{}", 9000 + i),
                vec![
                    ToolInfo {
                        name: format!("tool-{}", i),
                        description: "Test tool".to_string(),
                        input_schema: serde_json::json!({}),
                    }
                ]
            ).await;
        }
    });
    
    c.bench_function("tool_lookup", |b| {
        b.iter(|| {
            rt.block_on(async {
                let agents = registry.agents_for_tool(black_box("tool-5")).await;
                black_box(agents);
            });
        });
    });
}

// Benchmark load balancer selection
fn bench_load_balancer(c: &mut Criterion) {
    let balancer = RoundRobinBalancer::new();
    let agents: Vec<AgentInfo> = (0..10).map(|i| AgentInfo {
        name: format!("agent-{}", i),
        websocket_url: format!("ws://localhost:{}", 9000 + i),
        tools: vec![],
        status: AgentStatus::Healthy,
        registered_at: SystemTime::now(),
        last_health_check: SystemTime::now(),
    }).collect();
    
    c.bench_function("load_balancer_pick", |b| {
        b.iter(|| {
            let agent = balancer.pick(black_box(&agents));
            black_box(agent);
        });
    });
}

// Benchmark circuit breaker operations
fn bench_circuit_breaker(c: &mut Criterion) {
    let rt = Runtime::new().unwrap();
    let breakers = CircuitBreakerRegistry::new(BreakerConfig::default());
    
    let mut group = c.benchmark_group("circuit_breaker");
    
    group.bench_function("allow", |b| {
        b.iter(|| {
            rt.block_on(async {
                let allowed = breakers.allow(black_box("test-agent")).await;
                black_box(allowed);
            });
        });
    });
    
    group.bench_function("record_success", |b| {
        b.iter(|| {
            rt.block_on(async {
                breakers.record_success(black_box("test-agent")).await;
            });
        });
    });
    
    group.bench_function("record_failure", |b| {
        b.iter(|| {
            rt.block_on(async {
                breakers.record_failure(black_box("test-agent")).await;
            });
        });
    });
    
    group.finish();
}

// Benchmark JSON-RPC serialization
fn bench_json_rpc_serialization(c: &mut Criterion) {
    let mut group = c.benchmark_group("json_rpc");
    
    group.bench_function("serialize_request", |b| {
        b.iter(|| {
            let request = serde_json::json!({
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {
                    "name": "test_tool",
                    "arguments": {"key": "value"}
                }
            });
            let serialized = serde_json::to_string(&request).unwrap();
            black_box(serialized);
        });
    });
    
    group.bench_function("deserialize_request", |b| {
        let json = r#"{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"test_tool","arguments":{"key":"value"}}}"#;
        b.iter(|| {
            let value: serde_json::Value = serde_json::from_str(black_box(json)).unwrap();
            black_box(value);
        });
    });
    
    group.finish();
}

// Benchmark concurrent operations
fn bench_concurrent_operations(c: &mut Criterion) {
    let rt = Runtime::new().unwrap();
    
    let mut group = c.benchmark_group("concurrent");
    
    for concurrency in [1, 10, 50, 100].iter() {
        group.bench_with_input(
            BenchmarkId::from_parameter(concurrency),
            concurrency,
            |b, &concurrency| {
                b.iter(|| {
                    rt.block_on(async {
                        let registry = Arc::new(AgentRegistry::new());
                        let mut handles = vec![];
                        
                        for i in 0..concurrency {
                            let registry = registry.clone();
                            let handle = tokio::spawn(async move {
                                registry.register(
                                    format!("agent-{}", i),
                                    format!("ws://localhost:{}", 9000 + i),
                                    vec![
                                        ToolInfo {
                                            name: format!("tool-{}", i),
                                            description: "Test".to_string(),
                                            input_schema: serde_json::json!({}),
                                        }
                                    ]
                                ).await;
                            });
                            handles.push(handle);
                        }
                        
                        for handle in handles {
                            handle.await.unwrap();
                        }
                    });
                });
            }
        );
    }
    
    group.finish();
}

criterion_group!(
    benches,
    bench_agent_registration,
    bench_tool_lookup,
    bench_load_balancer,
    bench_circuit_breaker,
    bench_json_rpc_serialization,
    bench_concurrent_operations,
);

criterion_main!(benches);
