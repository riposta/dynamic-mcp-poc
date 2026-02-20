# MCP Gateway -- Authenticated Dynamic Tool Discovery

A Proof of Concept demonstrating an authenticated MCP (Model Context Protocol) gateway with Keycloak, RFC 8693 token exchange, and dynamic per-session tool discovery.

## What This Does

An AI agent connects to a single MCP gateway. The gateway lets the agent discover and activate tool servers on demand. Every hop is authenticated -- the user logs in via Keycloak, the gateway exchanges their token for server-specific tokens, and each MCP server validates its own scoped token.

```
User (browser)
  │
  │  Keycloak OIDC login (PKCE)
  ▼
Web Frontend + ADK Agent (:8000)
  │
  │  Bearer token (aud: mcp-gateway)
  ▼
MCP Gateway (:8010)
  │
  │  Token exchange (RFC 8693)
  ▼
MCP Servers (:8011, :8012)
  Each validates its own scoped token (aud: mcp-weather, mcp-calculator)
```

Key features:

- **Dynamic tool discovery** -- agent calls `search_servers` / `enable_server` at runtime
- **Per-session isolation** -- servers activated in one session are not visible in another
- **Token exchange** -- gateway swaps user tokens for server-specific tokens via Keycloak
- **Per-user access control** -- Keycloak roles determine which servers each user can access
- **No code changes to add servers** -- just add a YAML entry and a Keycloak client

## Prerequisites

- Python 3.13+
- Docker (for Keycloak)
- Node.js 18+ (for BDD tests)
- An LLM API key (Vertex AI, Google AI Studio, or OpenAI)

## Quick Start

### 1. Clone and set up Python environment

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Configure environment

```bash
cp .env.example .env
```

Edit `.env` -- the key setting is `MODEL_NAME`:

```bash
# Vertex AI (default, requires gcloud auth)
MODEL_NAME=vertex_ai/gemini-2.5-flash

# Or Google AI Studio (requires API key)
MODEL_NAME=gemini/gemini-2.0-flash
GOOGLE_API_KEY=your-key-here
```

### 3. Start everything

```bash
make up
```

This starts all services in order: Keycloak, configures token exchange permissions, MCP servers, gateway, and the web UI. It waits for each component to be ready before starting the next.

### 4. Open the web UI

Go to **http://localhost:8000** and click **Login with Keycloak**.

Test users:

| User | Password | Access |
|------|----------|--------|
| `testuser` | `testpass` | Weather + Calculator |
| `limiteduser` | `testpass` | Weather only |

After login you'll be redirected to the ADK chat UI. Ask the agent to find and use available tools.

## Make Commands

| Command | Description |
|---------|-------------|
| `make up` | Start all services (Keycloak, servers, gateway, web UI) |
| `make down` | Stop everything |
| `make status` | Check which services are running |
| `make logs` | Tail all service logs |
| `make test` | Run BDD test suite |
| `make test-smoke` | Run smoke tests only |
| `make test-install` | Install BDD test dependencies |

## Running Services Individually

If you prefer to start components in separate terminals:

```bash
# Terminal 1: Keycloak
docker compose up -d
# Wait for Keycloak to be ready (~30s), then configure permissions:
bash keycloak/setup-permissions.sh

# Terminal 2: Weather server
source .venv/bin/activate
python servers/weather_server.py

# Terminal 3: Calculator server
source .venv/bin/activate
python servers/calculator_server.py

# Terminal 4: Gateway
source .venv/bin/activate
python gateway/server.py

# Terminal 5: Web UI
source .venv/bin/activate
python agent/web.py
```

## Port Map

| Port | Component |
|------|-----------|
| 8080 | Keycloak (admin: `admin` / `admin`) |
| 8010 | MCP Gateway |
| 8011 | Weather MCP Server |
| 8012 | Calculator MCP Server |
| 8000 | Web Frontend + ADK Agent UI |

## How It Works

1. User logs in via Keycloak (Authorization Code + PKCE)
2. The access token (audience: `mcp-gateway`) is injected into the agent's MCP calls
3. Agent calls `search_servers()` to discover available servers
4. Agent calls `enable_server("weather")` -- the gateway:
   - Checks the user's role (`access:weather`)
   - Exchanges the token for one scoped to `mcp-weather`
   - Connects to the weather server, discovers its tools
   - Registers proxy tools on the gateway
5. Agent calls `get_weather("Warsaw")` -- the gateway:
   - Verifies the server is enabled in this session
   - Exchanges the token again for a fresh server-scoped token
   - Forwards the call to the weather server
   - Returns the result

Each MCP session has its own set of enabled servers. Tools activated in one browser tab don't appear in another.

## Running BDD Tests

The project uses Cucumber.js with TypeScript for black-box BDD testing against the running services.

```bash
# Install test dependencies (once)
make test-install

# Start all services
make up

# Run tests
make test
```

## Project Structure

```
MCPTest/
├── gateway/
│   ├── server.py              # MCP gateway with auth + token exchange + per-session state
│   └── servers.yaml           # Server registry (name, URL, audience, role)
├── servers/
│   ├── weather_server.py      # Weather MCP server (JWT auth)
│   └── calculator_server.py   # Calculator MCP server (JWT auth)
├── agent/
│   ├── __init__.py            # Exports root_agent
│   ├── main.py                # ADK agent with MCP toolset + header_provider
│   └── web.py                 # FastAPI: Keycloak login + ADK Web UI
├── keycloak/
│   ├── mcp-poc-realm.json     # Realm config (clients, scopes, mappers, users)
│   └── setup-permissions.sh   # Configures V1 fine-grained token exchange permissions
├── tests/bdd/                 # Cucumber.js BDD test suite
│   ├── features/              # Gherkin scenarios
│   ├── steps/                 # TypeScript step definitions
│   └── support/               # World class
├── doc/
│   ├── ARCHITECTURE.md        # Architecture overview
│   ├── IMPLEMENTATION.md      # Implementation details
│   └── IMPLEMENTATION-BDD.md  # BDD test approach
├── docker-compose.yml         # Keycloak container
├── Makefile                   # Service orchestration
├── requirements.txt           # Python dependencies
└── .env.example               # Environment template
```

## Adding a New MCP Server

1. **Keycloak** -- add a bearer-only client (`mcp-<name>`), an audience scope, and assign it to `mcp-gateway`
2. **Server code** -- create `servers/<name>_server.py` with `JWTVerifier(audience="mcp-<name>")`
3. **Gateway config** -- add an entry to `gateway/servers.yaml`
4. **Restart** the gateway -- no code changes needed in the gateway or agent

See `doc/IMPLEMENTATION.md` section 10 for full details.

## Documentation

- [Architecture](doc/ARCHITECTURE.md) -- component design, trust boundaries, token flow
- [Implementation](doc/IMPLEMENTATION.md) -- code structure, Keycloak setup, key APIs
- [BDD Testing](doc/IMPLEMENTATION-BDD.md) -- test approach, scenario catalog

## Limitations (PoC)

- In-memory state only -- lost on restart
- No token refresh -- user must re-login after token expires (1h)
- Single-user web session via global variable
- No TLS -- all traffic is plaintext HTTP
