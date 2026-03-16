# Monitoring & Error Tracking Setup

## Overview

This document covers the setup of monitoring and error tracking for the AdvanDEB platform in production.

## Sentry Integration (Recommended)

### Backend (FastAPI)

1. Install Sentry SDK:
```bash
cd app/backend
pip install sentry-sdk[fastapi]
```

2. Add to `requirements.txt`:
```
sentry-sdk[fastapi]==1.40.0
```

3. Add to `backend/.env`:
```env
SENTRY_DSN=https://your-sentry-dsn@sentry.io/your-project-id
SENTRY_ENVIRONMENT=production
SENTRY_TRACES_SAMPLE_RATE=0.1
```

4. Initialize in `app/main.py`:
```python
import sentry_sdk
from sentry_sdk.integrations.fastapi import FastApiIntegration
from sentry_sdk.integrations.starlette import StarletteIntegration

from app.core.config import settings

if settings.SENTRY_DSN:
    sentry_sdk.init(
        dsn=settings.SENTRY_DSN,
        environment=settings.SENTRY_ENVIRONMENT,
        traces_sample_rate=settings.SENTRY_TRACES_SAMPLE_RATE,
        integrations=[
            StarletteIntegration(),
            FastApiIntegration(),
        ],
    )
```

5. Add settings to `app/core/config.py`:
```python
class Settings(BaseSettings):
    # ... existing settings ...
    
    # Sentry
    SENTRY_DSN: Optional[str] = None
    SENTRY_ENVIRONMENT: str = "development"
    SENTRY_TRACES_SAMPLE_RATE: float = 0.1
```

### Frontend (Vue 3)

1. Install Sentry SDK:
```bash
cd app/frontend
npm install @sentry/vue
```

2. Add to `frontend/.env`:
```env
VITE_SENTRY_DSN=https://your-sentry-dsn@sentry.io/your-project-id
VITE_SENTRY_ENVIRONMENT=production
```

3. Initialize in `frontend/src/main.ts`:
```typescript
import { createApp } from 'vue'
import * as Sentry from '@sentry/vue'
import App from './App.vue'
import router from './router'
import { createPinia } from 'pinia'

const app = createApp(App)

// Initialize Sentry
if (import.meta.env.VITE_SENTRY_DSN) {
    Sentry.init({
        app,
        dsn: import.meta.env.VITE_SENTRY_DSN,
        environment: import.meta.env.VITE_SENTRY_ENVIRONMENT || 'development',
        integrations: [
            Sentry.browserTracingIntegration({ router }),
            Sentry.replayIntegration({
                maskAllText: false,
                blockAllMedia: false,
            }),
        ],
        tracesSampleRate: 0.1,
        replaysSessionSampleRate: 0.1,
        replaysOnErrorSampleRate: 1.0,
    })
}

app.use(createPinia())
app.use(router)
app.mount('#app')
```

---

## Prometheus Metrics

### Backend Metrics

1. Install prometheus client:
```bash
cd app/backend
pip install prometheus-fastapi-instrumentator
```

2. Add to `requirements.txt`:
```
prometheus-fastapi-instrumentator==6.1.0
```

3. Add to `app/main.py`:
```python
from prometheus_fastapi_instrumentator import Instrumentator

# After creating the app
app = FastAPI(...)

# Add Prometheus metrics
Instrumentator().instrument(app).expose(app, endpoint="/metrics")
```

4. Access metrics at: `http://localhost:8000/metrics`

### Grafana Dashboard

Create a Grafana dashboard to visualize metrics:

1. Add Prometheus data source in Grafana
2. Import dashboard template for FastAPI:
   - Go to: https://grafana.com/grafana/dashboards/
   - Search for "FastAPI"
   - Import dashboard ID: 16110

---

## Application Performance Monitoring (APM)

### Custom Timing Middleware

Add custom timing middleware to track endpoint performance:

```python
# app/middleware/timing.py
import time
from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
import logging

logger = logging.getLogger(__name__)

class TimingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        start_time = time.time()
        
        response = await call_next(request)
        
        process_time = time.time() - start_time
        response.headers["X-Process-Time"] = str(process_time)
        
        # Log slow requests (> 1s)
        if process_time > 1.0:
            logger.warning(
                f"Slow request: {request.method} {request.url.path} took {process_time:.2f}s"
            )
        
        return response

# In app/main.py
from app.middleware.timing import TimingMiddleware

app.add_middleware(TimingMiddleware)
```

---

## Health Check Monitoring

### Uptime Monitoring

Use services like:
- **UptimeRobot** (free tier available)
- **Pingdom**
- **Better Uptime**

Monitor these endpoints:
- Frontend: `http://yourdomain.com/health`
- Backend: `http://yourdomain.com/api/health`

Set up alerts for:
- HTTP 500 errors
- Response time > 5s
- Downtime > 2 minutes

### Service Health Checks

Monitor health with curl or a script:
```bash
curl http://localhost:8000/health  # Backend
curl http://localhost:3000/health  # Frontend (nginx)
```

---

## Logging

### Structured Logging

Use structured logging for better searchability:

```python
# app/core/logging.py
import logging
import json
from datetime import datetime

class JSONFormatter(logging.Formatter):
    def format(self, record):
        log_data = {
            "timestamp": datetime.utcnow().isoformat(),
            "level": record.levelname,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
        }
        
        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)
        
        return json.dumps(log_data)

# Configure in app/main.py
import logging
from app.core.logging import JSONFormatter

handler = logging.StreamHandler()
handler.setFormatter(JSONFormatter())
logging.basicConfig(level=logging.INFO, handlers=[handler])
```

### Log Aggregation

Use a log aggregation service:

**Option 1: ELK Stack (Self-hosted)**
- Elasticsearch: Store logs
- Logstash: Process logs
- Kibana: Visualize logs

**Option 2: Cloud Services**
- **Datadog Logs**
- **Loggly**
- **Papertrail**

For log rotation when running with uvicorn, use `--log-config` or pipe to a log manager (logrotate, journald).

---

## Performance Metrics Tracking

### Key Performance Indicators (KPIs)

Track these metrics:

**Backend:**
- Request latency (p50, p95, p99)
- Error rate (5xx responses)
- Requests per second
- Database query time
- MCP call duration

**Frontend:**
- Page load time (initial + interactive)
- Time to First Byte (TTFB)
- First Contentful Paint (FCP)
- Largest Contentful Paint (LCP)
- Cumulative Layout Shift (CLS)
- Bundle size

### Lighthouse CI

Add Lighthouse CI for automated performance monitoring:

```bash
npm install -g @lhci/cli

# Create lighthouserc.json
cat > lighthouserc.json << 'EOF'
{
  "ci": {
    "collect": {
      "startServerCommand": "npm run preview",
      "url": ["http://localhost:3000"],
      "numberOfRuns": 3
    },
    "assert": {
      "preset": "lighthouse:recommended",
      "assertions": {
        "categories:performance": ["error", {"minScore": 0.9}],
        "categories:accessibility": ["error", {"minScore": 0.9}],
        "categories:best-practices": ["error", {"minScore": 0.9}],
        "categories:seo": ["error", {"minScore": 0.9}]
      }
    }
  }
}
EOF

# Run Lighthouse CI
lhci autorun
```

Add to CI/CD pipeline:
```yaml
# .github/workflows/lighthouse.yml
name: Lighthouse CI
on: [push]
jobs:
  lighthouse:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - uses: actions/setup-node@v3
      - run: npm ci
      - run: npm run build
      - run: npx @lhci/cli@latest autorun
```

---

## Alerting

### Alert Rules

Set up alerts for:

**Critical (Page immediately):**
- API down (health check fails)
- Error rate > 10%
- Database connection lost

**Warning (Notify in Slack):**
- Response time > 2s (p95)
- Error rate > 5%
- CPU usage > 80%
- Memory usage > 90%

**Info (Email):**
- New deployment
- Unusual traffic pattern

### Alert Channels

Configure multiple channels:
- **Email**: For non-urgent notifications
- **Slack/Discord**: For team notifications
- **PagerDuty/OpsGenie**: For critical alerts
- **SMS**: For production-down alerts

---

## Dashboard Examples

### Backend Health Dashboard

```
┌─────────────────────────────────────────┐
│ AdvanDEB Backend Health                  │
├─────────────────────────────────────────┤
│ Status: ● Healthy                        │
│ Uptime: 99.98%                          │
│ Requests/min: 1,234                      │
│ Avg Response: 145ms                      │
│ Error Rate: 0.1%                         │
├─────────────────────────────────────────┤
│ MongoDB: ● Connected                     │
│ MCP Gateway: ● Connected                 │
│ Memory: 1.2GB / 2GB (60%)               │
│ CPU: 35%                                 │
└─────────────────────────────────────────┘
```

### Frontend Performance Dashboard

```
┌─────────────────────────────────────────┐
│ AdvanDEB Frontend Performance            │
├─────────────────────────────────────────┤
│ Lighthouse Score: 95/100                 │
│ FCP: 0.8s                                │
│ LCP: 1.2s                                │
│ CLS: 0.05                                │
├─────────────────────────────────────────┤
│ Bundle Size: 645KB (gzipped)             │
│ Initial Load: 2.1s                       │
│ Active Users: 42                         │
│ Error Rate: 0.05%                        │
└─────────────────────────────────────────┘
```

---

## Checklist

### Initial Setup
- [ ] Create Sentry account and project
- [ ] Configure Sentry DSN in backend
- [ ] Configure Sentry DSN in frontend
- [ ] Set up Prometheus metrics endpoint
- [ ] Configure structured logging
- [ ] Set up uptime monitoring

### Production Monitoring
- [ ] Verify health checks are passing
- [ ] Set up Grafana dashboard
- [ ] Configure alert rules
- [ ] Test alert delivery
- [ ] Document on-call procedures
- [ ] Run Lighthouse CI baseline

### Ongoing
- [ ] Review error reports weekly
- [ ] Analyze performance metrics monthly
- [ ] Update alert thresholds quarterly
- [ ] Review and optimize slow endpoints

---

## References

- [Sentry FastAPI Integration](https://docs.sentry.io/platforms/python/guides/fastapi/)
- [Sentry Vue Integration](https://docs.sentry.io/platforms/javascript/guides/vue/)
- [Prometheus FastAPI](https://github.com/trallnag/prometheus-fastapi-instrumentator)
- [Lighthouse CI](https://github.com/GoogleChrome/lighthouse-ci)
- [FastAPI Monitoring Best Practices](https://fastapi.tiangolo.com/advanced/monitoring/)
