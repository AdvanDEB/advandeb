# AdvanDEB systemd units

```
advandeb.target                       umbrella: everything
├── advandeb.service                  web app, uvicorn 127.0.0.1:8400 (behind nginx)
└── advandeb-stack.target             agent stack
    ├── advandeb-gateway.service      MCP gateway, 127.0.0.1:8080
    ├── advandeb-agent@<name>.service retrieval_agent, graph_explorer_agent, synthesis_agent,
    │                                 query_planner_agent, curator_agent, chatbot_agent
    └── advandeb-register-agents.service   oneshot: registers the agents with the gateway
```

Each component is its own unit with `Restart=on-failure`, a start limit
(5 starts per 10 min, then it stays failed and the alert fires) and a
`MemoryHigh`/`MemoryMax` cap; `retrieval_agent` gets a larger cap from
`advandeb-agent@retrieval_agent.service.d/memory.conf`. Agents and the gateway
are started through `scripts/run_component.py`, which passes each one only the
variables it needs from `app/backend/.env`.

This replaces `advandeb-stack.service` (one `Type=forking` script running all
seven processes): systemd tracked no main PID there, so a crashed agent was
never restarted, and `advandeb.service` had `Requires=` on it, so a stack that
failed to start took the web app down with it.

## Install / migrate from advandeb-stack.service

Needs the live checkout (`/home/adeb/dev/advandeb`) on a commit that contains
these files (`scripts/run_component.py` must exist). Run from the checkout.

Order matters: the *old* advandeb.service has `Requires=advandeb-stack.service`,
so the new unit files must be loaded (daemon-reload) **before** the legacy
stack is stopped, or stopping it takes the web app down too.

```bash
B=/var/backups/advandeb-systemd-$(date +%Y%m%d-%H%M%S); sudo mkdir -p "$B" && sudo cp -a /etc/systemd/system/advandeb* "$B"/ && echo "backup: $B"
sudo cp scripts/systemd/advandeb.service scripts/systemd/advandeb.target \
        scripts/systemd/advandeb-stack.target scripts/systemd/advandeb-gateway.service \
        scripts/systemd/advandeb-register-agents.service 'scripts/systemd/advandeb-agent@.service' \
        /etc/systemd/system/ \
  && sudo cp -r 'scripts/systemd/advandeb-agent@retrieval_agent.service.d' /etc/systemd/system/ \
  && sudo systemctl daemon-reload
sudo systemctl disable --now advandeb-stack.service
sudo rm /etc/systemd/system/advandeb-stack.service && sudo systemctl daemon-reload
sudo systemctl start advandeb-stack.target
sudo systemctl restart advandeb.service
./scripts/status_stack.sh
```

Rollback (`$B` = the backup directory printed above):

```bash
sudo systemctl stop advandeb-stack.target \
  && sudo rm -rf /etc/systemd/system/advandeb-stack.target /etc/systemd/system/advandeb-gateway.service \
       /etc/systemd/system/advandeb-register-agents.service '/etc/systemd/system/advandeb-agent@.service' \
       '/etc/systemd/system/advandeb-agent@retrieval_agent.service.d' \
  && sudo cp -a "$B"/. /etc/systemd/system/ && sudo systemctl daemon-reload \
  && sudo systemctl enable --now advandeb-stack.service && sudo systemctl restart advandeb.service
```

## Day to day

| task | command |
|---|---|
| restart everything | `sudo systemctl restart advandeb.target` |
| restart only the web app | `sudo systemctl restart advandeb.service` |
| restart the agent stack | `sudo systemctl restart advandeb-stack.target` |
| restart one agent | `sudo systemctl restart advandeb-agent@chatbot_agent.service` (or `./scripts/restart_agent.sh chatbot_agent`) |
| status | `./scripts/status_stack.sh` |
| logs | `journalctl -u advandeb.service -f`, `journalctl -u 'advandeb-agent@*' -f` |
| a unit hit its start limit | fix the cause, then `sudo systemctl reset-failed <unit>` and start it |

`./scripts/start_stack.sh` / `stop_stack.sh` are for running the stack by hand
without these units; they refuse while the units are active.
