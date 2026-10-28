# AdvanDEB monitoring

Prometheus 2.45 and node-exporter 1.7 (Ubuntu packages) and Grafana run on the
host; this directory holds their AdvanDEB configuration.

| file | installed as |
|---|---|
| `prometheus/prometheus.yml` | `/etc/prometheus/prometheus.yml` |
| `prometheus/advandeb_alerts.yml` | `/etc/prometheus/advandeb_alerts.yml` |
| `grafana/provisioning/datasources/advandeb.yml` | `/etc/grafana/provisioning/datasources/` |
| `grafana/provisioning/dashboards/*` | `/etc/grafana/provisioning/dashboards/` (re-read every 30 s) |

Check before installing:

```bash
promtool check rules monitoring/prometheus/advandeb_alerts.yml
(cd monitoring/prometheus && promtool test rules advandeb_alerts_test.yml)
```

## What is scraped

| job | target | what |
|---|---|---|
| `advandeb_backend` | 127.0.0.1:8400/metrics | HTTP by route/status, chat turns by LLM path (`default` shared key, `byok`, `agent`) and outcome, open WebSockets, graph-rebuild queue, process RSS, and `advandeb_dependency_up` for MongoDB/ArangoDB/Ollama (probed at scrape time — none of them has a Prometheus endpoint without an extra exporter) |
| `advandeb_agents` | 127.0.0.1:8181–8186/metrics | MCP tool calls/latency/outcome per agent, process RSS |
| `mcp_gateway` | 127.0.0.1:8080/metrics | gateway (carries no chat traffic today) |
| `node` | 127.0.0.1:9100 | host disk, memory, CPU |

`/metrics` needs `prometheus-client` in the conda env; without it the app still
runs and `/metrics` answers 503 (which `AdvandebWebDown` reports). nginx does
not proxy `/metrics`, and the app refuses it on any request carrying
`X-Forwarded-For` or `CF-Connecting-IP`.

## Loopback only

Prometheus and node-exporter have no authentication. Bind them to loopback in
`/etc/default/prometheus` and `/etc/default/prometheus-node-exporter`:

```
ARGS="--web.listen-address=127.0.0.1:9090"
ARGS="--web.listen-address=127.0.0.1:9100"
```

To use the UIs from another machine: `ssh -L 9090:127.0.0.1:9090 -L 3100:127.0.0.1:3100 adeb@192.168.0.50`.

## Alerts

No Alertmanager is installed: alerts show in Prometheus (`/alerts`) and in
Grafana's alert list, but nothing is sent anywhere. To get notifications,
install `prometheus-alertmanager`, add an `alerting:` block to
`prometheus.yml`, and configure a receiver (e-mail, Slack, ntfy …).
