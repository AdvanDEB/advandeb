# Performance Benchmarks

This directory contains performance benchmarks for the MCP Gateway using Criterion.rs.

## Running Benchmarks

```bash
# Run all benchmarks
cargo bench

# Run specific benchmark
cargo bench agent_registration
cargo bench tool_lookup
cargo bench load_balancer

# Save baseline for comparison
cargo bench -- --save-baseline my_baseline

# Compare against baseline
cargo bench -- --baseline my_baseline
```

## Benchmark Categories

### 1. Agent Registration
Measures the time to register a new agent with the gateway, including:
- Adding agent to registry
- Building tool index
- Updating internal state

**Target**: < 1ms per registration

### 2. Tool Lookup
Measures the time to find agents that provide a specific tool:
- Hash map lookup
- Agent filtering

**Target**: < 100μs per lookup

### 3. Load Balancer
Measures round-robin selection performance across multiple agents:
- Atomic counter increment
- Array indexing

**Target**: < 10μs per selection

### 4. Circuit Breaker
Measures circuit breaker state management:
- `allow()` check (should circuit allow request)
- `record_success()` (update success counter)
- `record_failure()` (update failure counter, check threshold)

**Target**: < 100μs per operation

### 5. JSON-RPC Serialization
Measures JSON serialization/deserialization performance for MCP protocol messages:
- Request serialization
- Response deserialization

**Target**: < 50μs per message

### 6. Concurrent Operations
Measures performance under concurrent load with varying concurrency levels (1, 10, 50, 100):
- Multiple agent registrations in parallel
- Lock contention
- Task scheduling overhead

**Target**: Linear scaling up to 100 concurrent operations

## Viewing Results

After running benchmarks, reports are generated in `target/criterion/`:

```bash
# Open HTML report in browser
open target/criterion/report/index.html

# Or on Linux
xdg-open target/criterion/report/index.html
```

Each benchmark includes:
- Mean execution time
- Standard deviation
- Throughput
- Performance graphs
- Statistical analysis

## Performance Targets

Based on the 12-week plan, the gateway should achieve:

- **Tool Call Overhead**: < 50ms end-to-end (routing + network + agent processing)
- **Gateway Internal Overhead**: < 5ms (everything except agent processing)
  - Registry lookup: < 100μs
  - Load balancer: < 10μs
  - Circuit breaker: < 100μs
  - Connection pool: < 1ms
  - JSON serialization: < 50μs

- **Concurrent Connections**: 100+ simultaneous WebSocket connections
- **Throughput**: 1000+ tool calls per second (with fast agents)

## Continuous Benchmarking

To track performance over time:

```bash
# Before making changes
cargo bench -- --save-baseline before

# After making changes
cargo bench -- --baseline before

# Criterion will show % change for each benchmark
```

## Notes

- Benchmarks use mock data and don't involve actual network calls
- For end-to-end performance testing, use `examples/test_api.sh`
- Results may vary based on system load and hardware
- Run on a quiet system for consistent results
- Criterion automatically warms up and runs multiple iterations
