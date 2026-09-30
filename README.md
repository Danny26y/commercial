# FastAPI Multi-Provider AI Router Boilerplate

[![Python](https://img.shields.io/badge/Python-3.11%20%7C%203.12-blue.svg)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-009688.svg)](https://fastapi.tiangolo.com)
[![Pydantic](https://img.shields.io/badge/Pydantic-v2-E92063.svg)](https://docs.pydantic.dev/)
[![Docker](https://img.shields.io/badge/Docker-Ready-2496ED.svg)](https://www.docker.com/)
[![License](https://img.shields.io/badge/License-Commercial%20Starter%20Kit-green.svg)](#license)

> **Zero-downtime, production-ready AI routing gateway for indie hackers and developers.**
> Drop-in replacement for OpenAI endpoints with automated multi-provider failover, circuit breaker resilience, latency observability, and header security.

---

## ⚡ The Problem It Solves

If your AI SaaS relies on a single provider (like OpenAI or Anthropic), your app **crashes or hangs** whenever:
1. The provider throws a **`429 Too Many Requests` (Rate Limit)** during traffic spikes.
2. The provider suffers a **`500 / 502 / 503` Internal Outage**.
3. Upstream network queries **time out**.

The **FastAPI Multi-Provider AI Router Boilerplate** sits between your frontend/backend and multiple AI providers. If your primary provider fails or hits a rate limit, the router **instantly and transparently cascades** to your fallback providers (Groq, Anthropic, OpenRouter) in milliseconds—with **zero dropped requests** and **zero downtime** for your end users.

---

## 🏛 Architecture Overview

```
                      +---------------------------------------+
                      |          Client / Application         |
                      +---------------------------------------+
                                          |
                               [POST /v1/chat/completions]
                                          |
                                          v
                      +---------------------------------------+
                      |         FastAPI Gateway Layer         |
                      |  * API Key Auth (X-API-Key)           |
                      |  * Observability & Latency Logger     |
                      |  * Connection-Pooled httpx.AsyncClient|
                      +---------------------------------------+
                                          |
                                          v
                      +---------------------------------------+
                      |        Resilient Router Engine        |
                      |  * Circuit Breaker State Evaluator    |
                      |  * Model Schema Translation Adapter   |
                      +---------------------------------------+
                               /          |          \
                 (Try Primary)/           |           \(Cascading Fallback)
                             v            v            v
                 +---------------+ +---------------+ +---------------+
                 |    OpenAI     | |     Groq      | |   Anthropic   |
                 |  (gpt-4o)     | |  (llama-3.3)  | |  (claude-3.5) |
                 +---------------+ +---------------+ +---------------+
                        |                 |                 |
                   429/5xx Error      200 Success           -
                        |                 |
                        +---> [CASCADE] --+---> [Unified Response + _router_meta]
```

---

## 🚀 3-Minute Quickstart

### 1. Prerequisites
- Python 3.11+ or 3.12+
- `pip` and `virtualenv`

### 2. Setup Virtual Environment & Install Dependencies
```bash
# Create and activate virtual environment
python -m venv .venv

# On Linux / macOS:
source .venv/bin/activate

# On Windows:
.venv\Scripts\activate

# Install modern pinned dependencies
pip install -r requirements.txt
```

### 3. Configure Environment Variables
Copy the template configuration file:
```bash
cp .env.example .env
```
Open `.env` and fill in your client API keys and LLM provider credentials:
```ini
API_KEYS=sk-live-router-key-demo-123
OPENAI_API_KEY=sk-proj-...
GROQ_API_KEY=gsk_...
ANTHROPIC_API_KEY=sk-ant-...
DEFAULT_PROVIDER=openai
PROVIDER_FALLBACK_ORDER=openai,groq,anthropic,openrouter
```

### 4. Start the Application Server
```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```
The API is live at `http://localhost:8000`!
- Interactive OpenAPI Docs: `http://localhost:8000/docs`
- Health & Circuit Breaker Dashboard: `http://localhost:8000/health`

---

## 🧪 cURL Testing Examples

### 1. Standard OpenAI-Compatible Chat Completion
```bash
curl -X POST http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "X-API-Key: sk-live-router-key-demo-123" \
  -d '{
    "model": "default",
    "messages": [
      {"role": "system", "content": "You are a helpful coding assistant."},
      {"role": "user", "content": "Explain circuit breakers in 2 sentences."}
    ],
    "temperature": 0.7
  }'
```

#### Example Output (With Diagnostic Router Metadata)
```json
{
  "id": "chatcmpl-a1b2c3d4",
  "object": "chat.completion",
  "created": 1727638400,
  "model": "gpt-4o",
  "choices": [
    {
      "index": 0,
      "message": {
        "role": "assistant",
        "content": "A circuit breaker monitors external service calls and trips to an open state when repeated failures occur, preventing system strain. Once cooldown expires, it probes the service and automatically resumes traffic upon recovery."
      },
      "finish_reason": "stop"
    }
  ],
  "usage": {
    "prompt_tokens": 28,
    "completion_tokens": 42,
    "total_tokens": 70
  },
  "_router_meta": {
    "provider_used": "openai",
    "model_used": "gpt-4o",
    "latency_ms": 421.15,
    "fallback_chain": [],
    "retries_attempted": 0
  }
}
```

---

### 2. Observing Intelligent Fallback in Real-Time
If OpenAI returns a `429 Rate Limit` or is unreachable, the router seamlessly fails over to Groq or Anthropic without crashing your user's request. The `_router_meta` reveals the failover history:

```json
{
  "id": "chatcmpl-groq-987123",
  "object": "chat.completion",
  "created": 1727638405,
  "model": "llama-3.3-70b-versatile",
  "choices": [
    {
      "index": 0,
      "message": {
        "role": "assistant",
        "content": "A circuit breaker prevents systemic collapse by pausing calls to failing services."
      },
      "finish_reason": "stop"
    }
  ],
  "usage": {
    "prompt_tokens": 28,
    "completion_tokens": 18,
    "total_tokens": 46
  },
  "_router_meta": {
    "provider_used": "groq",
    "model_used": "llama-3.3-70b-versatile",
    "latency_ms": 218.40,
    "fallback_chain": [
      "openai (attempt 1): HTTP 429 - Rate limit exceeded: TPM limit reached"
    ],
    "retries_attempted": 1
  }
}
```

---

### 3. Explicit Provider Override
You can force a request to use a specific provider by passing the optional `"provider"` field:
```bash
curl -X POST http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "X-API-Key: sk-live-router-key-demo-123" \
  -d '{
    "provider": "anthropic",
    "model": "claude-3-5-sonnet-20241022",
    "messages": [
      {"role": "user", "content": "Hello Claude!"}
    ]
  }'
```

---

### 4. Live Health Check & Circuit Status
```bash
curl -X GET http://localhost:8000/health
```

#### Response
```json
{
  "status": "healthy",
  "app_name": "FastAPI Multi-Provider AI Router",
  "version": "1.0.0",
  "environment": "production",
  "uptime_seconds": 12842.50,
  "configured_providers": [
    "openai",
    "anthropic",
    "groq",
    "openrouter"
  ],
  "default_provider": "openai",
  "fallback_order": [
    "openai",
    "groq",
    "anthropic",
    "openrouter"
  ],
  "circuit_breakers": {
    "openai": {
      "state": "CLOSED",
      "consecutive_failures": 0,
      "last_failure_timestamp": null
    },
    "groq": {
      "state": "CLOSED",
      "consecutive_failures": 0,
      "last_failure_timestamp": null
    }
  }
}
```

---

## 🛡 Security Architecture

1. **Header Authentication (`X-API-Key`)**:
   Incoming calls must contain a configured key. Verified with constant-time string comparison (`secrets.compare_digest`) to protect against timing attacks.
2. **Secret Masking**:
   All upstream provider API keys are typed as Pydantic `SecretStr`, preventing accidental leakage in application logs or stack traces.
3. **CORS Hardening**:
   Restricts cross-origin requests to configured domains in production.
4. **Structured Error Format**:
   All 4xx/5xx exceptions follow the standard OpenAI JSON error contract:
   ```json
   {
     "error": {
       "message": "Detailed error message",
       "type": "authentication_error",
       "param": null,
       "code": "invalid_api_key"
     }
   }
   ```

---

## ⚡ Circuit Breaker & Fallback Logic

- **CLOSED State**: Healthy. All requests are sent to the primary provider.
- **OPEN State**: If a provider triggers `CIRCUIT_BREAKER_FAILURE_THRESHOLD` consecutive failures (429 or 5xx), the circuit breaker **trips to OPEN**. All subsequent requests skip this provider immediately to save latency.
- **HALF-OPEN State**: After `CIRCUIT_BREAKER_RECOVERY_TIME_SECONDS` (default: 60s), the router sends a single probe request to check if the provider has recovered. If successful, the circuit resets to **CLOSED**.

---

## 🐳 Production Deployment

### 1. Docker & Docker Compose
```bash
# Build and run containerized stack in detached mode
docker compose up -d --build

# Inspect logs
docker compose logs -f

# Verify container health
docker ps
```

### 2. Deploying to Railway
1. Push this repository to GitHub or upload the package archive.
2. Create a **New Project** on [Railway](https://railway.app/).
3. Select **Deploy from GitHub repo**.
4. In the Railway dashboard under **Variables**, set:
   - `ENVIRONMENT=production`
   - `API_KEYS=your-secret-client-key`
   - `OPENAI_API_KEY=...`
   - `GROQ_API_KEY=...`
   - `ANTHROPIC_API_KEY=...`
5. Railway will automatically detect the `Dockerfile` and spin up your high-performance service.

### 3. Deploying to Render
1. Create a **New Web Service** on [Render](https://render.com/).
2. Select **Docker** environment.
3. Configure your Environment Variables in the Render dashboard.
4. Set Health Check path to `/health`.
5. Deploy.

---

## 📦 Packaging for Commercial Distribution

To bundle this starter kit into a clean `.zip` archive ready to sell on Paystack, Gumroad, or LemonSqueezy:

```bash
chmod +x package.sh
./package.sh
```

The script automatically:
- Validates all necessary production files.
- Purges `__pycache__`, `.pytest_cache`, `.venv`, and `.git`.
- **Excludes your private `.env` file** to ensure no secrets are packaged.
- Compiles a sanitized `fastapi-ai-router-starter-kit.zip` archive.

---

## 📄 License & Commercial Rights

This starter kit is licensed for **commercial and personal use**. You may build, modify, and host proprietary applications on top of this boilerplate. You may not resell or redistribute this template as an un-modified competing starter kit.
