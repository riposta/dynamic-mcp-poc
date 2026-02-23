# Implementation Guide

This document describes how to implement the authenticated dynamic MCP gateway described in [ARCHITECTURE.md](ARCHITECTURE.md). It covers every component: technology choices, Keycloak configuration, code structure, key APIs, and wiring between layers.

## Technology Stack

| Component | Technology | Version | Role |
|-----------|-----------|---------|------|
| Identity Provider | Keycloak | 26.2+ | OIDC / token exchange |
| MCP Gateway | FastMCP (Python) | 2.14+ | MCP server with JWT auth |
| MCP Servers | FastMCP (Python) | 2.14+ | Standalone tool servers |
| AI Agent | Google ADK | latest | Agent runtime + web UI |
| LLM Router | LiteLLM | latest | Multi-provider LLM access |
| Web Layer | FastAPI | latest | Login flow, session management |
| HTTP Client | httpx | latest | Token exchange, server calls |
| Container Runtime | Docker Compose | v2 | Keycloak hosting |

### Python Dependencies

```
fastmcp           # MCP protocol, JWTVerifier, Client
google-adk        # Agent framework, McpToolset, web UI
google-genai      # Google AI SDK (ADK dependency)
litellm           # LLM provider abstraction
python-dotenv     # .env file loading
httpx             # Async HTTP client
uvicorn           # ASGI server
pyyaml            # YAML config parsing
itsdangerous      # Session cookie signing
jinja2            # Template engine (Starlette dependency)
```

## 1. Keycloak Setup

### Container

Run Keycloak in dev mode via Docker Compose. Mount a realm export JSON for automatic import on first startup. The `--features=token-exchange,admin-fine-grained-authz` flags are required to enable RFC 8693 token exchange and V1 fine-grained authorization (used for per-user token exchange permissions).

```yaml
services:
  keycloak:
    image: quay.io/keycloak/keycloak:26.2
    environment:
      KEYCLOAK_ADMIN: admin
      KEYCLOAK_ADMIN_PASSWORD: admin
    ports:
      - "8080:8080"
    volumes:
      - ./keycloak:/opt/keycloak/data/import
    command: start-dev --import-realm --features=token-exchange,admin-fine-grained-authz
```

Keycloak will auto-import all JSON files from `/opt/keycloak/data/import` on first boot.

### Realm Configuration

Create a realm named `mcp-poc`. All clients, scopes, mappers, and users are defined in a single JSON file for import.

#### Realm-Level Settings

```json
{
  "realm": "mcp-poc",
  "enabled": true,
  "sslRequired": "external",
  "accessTokenLifespan": 3600,
  "accessCodeLifespan": 60,
  "ssoSessionIdleTimeout": 1800,
  "ssoSessionMaxLifespan": 36000
}
```

The `accessTokenLifespan` of 3600 seconds (1 hour) provides a comfortable demo window. In production this should be much shorter (e.g. 300 seconds) with refresh token rotation.

#### Clients

Four OIDC clients are needed. Each serves a different role in the token flow.

**1. `adk-web-client` -- Public client for user login**

```json
{
  "clientId": "adk-web-client",
  "publicClient": true,
  "standardFlowEnabled": true,
  "redirectUris": ["http://localhost:8000/callback"],
  "webOrigins": ["http://localhost:8000"],
  "attributes": {
    "pkce.code.challenge.method": "S256"
  },
  "defaultClientScopes": ["openid", "profile", "email", "mcp-gateway-audience"]
}
```

Key points:
- `publicClient: true` -- no client secret, PKCE required
- `pkce.code.challenge.method: S256` -- enforces SHA-256 PKCE challenges
- `directAccessGrantsEnabled: true` -- enables Resource Owner Password Credentials grant, required by BDD tests to obtain tokens programmatically without a browser
- `mcp-gateway-audience` scope -- injects `mcp-gateway` into the `aud` claim of issued tokens, which is required for the gateway to later exchange them

**2. `mcp-gateway` -- Confidential client for token exchange**

```json
{
  "clientId": "mcp-gateway",
  "publicClient": false,
  "clientAuthenticatorType": "client-secret",
  "secret": "mcp-gateway-secret",
  "serviceAccountsEnabled": true,
  "defaultClientScopes": ["openid", "profile", "email",
                          "mcp-weather-audience", "mcp-calculator-audience"]
}
```

Key points:
- Token exchange is authorized via **V1 fine-grained permissions** (not the V2 `standard.token.exchange.enabled` attribute). This requires the `admin-fine-grained-authz` feature flag and permissions configured per target client in Keycloak.
- V1 fine-grained permissions allow **per-user access control**: role-based policies determine which users can exchange tokens for which target audiences. For example, a user with the `access:weather` role can exchange tokens targeting `mcp-weather`, but a user without `access:calculator` cannot exchange tokens targeting `mcp-calculator`.
- Permissions are configured via the Keycloak Admin REST API using `keycloak/setup-permissions.sh`, which runs after realm import to set up token-exchange permissions on each target client with role-based policies.
- `serviceAccountsEnabled: true` -- required for client credentials flow
- Server audience scopes (`mcp-weather-audience`, `mcp-calculator-audience`) -- ensure exchanged tokens can contain these audiences

**3. `mcp-weather` / `mcp-calculator` -- Bearer-only resource servers**

```json
{
  "clientId": "mcp-weather",
  "publicClient": false,
  "secret": "mcp-weather-secret",
  "bearerOnly": true,
  "standardFlowEnabled": false,
  "serviceAccountsEnabled": false
}
```

These clients exist solely as audience targets. `bearerOnly: true` means they never initiate login flows -- they only validate incoming tokens.

#### Client Scopes and Audience Mappers

Each audience target needs a client scope containing an `oidc-audience-mapper`. This mapper injects the target client ID into the `aud` claim of tokens.

```json
{
  "name": "mcp-weather-audience",
  "protocol": "openid-connect",
  "attributes": {
    "include.in.token.scope": "false",
    "display.on.consent.screen": "false"
  },
  "protocolMappers": [{
    "name": "mcp-weather-audience-mapper",
    "protocolMapper": "oidc-audience-mapper",
    "config": {
      "included.client.audience": "mcp-weather",
      "id.token.claim": "false",
      "access.token.claim": "true"
    }
  }]
}
```

Four scopes total:
- `profile` -- built-in OIDC scope containing a `preferred_username` mapper (`oidc-usermodel-attribute-mapper`). Must be explicitly defined in the realm import because Keycloak does not auto-create built-in scopes with their protocol mappers during realm import. Without this, tokens lack the `preferred_username` claim used by MCP servers to identify the caller.
- `mcp-gateway-audience` -- assigned to `adk-web-client`, adds `mcp-gateway` to user tokens
- `mcp-weather-audience` -- assigned to `mcp-gateway`, enables exchange with audience `mcp-weather`
- `mcp-calculator-audience` -- assigned to `mcp-gateway`, enables exchange with audience `mcp-calculator`

The assignment chain is: `adk-web-client` gets `mcp-gateway-audience`, `mcp-gateway` gets both server audience scopes. The `profile` scope is assigned to all clients that need `preferred_username` in their tokens.

#### Test User

```json
{
  "username": "testuser",
  "enabled": true,
  "emailVerified": true,
  "email": "testuser@mcp-poc.local",
  "realmRoles": ["default-roles-mcp-poc", "access:weather", "access:calculator"],
  "credentials": [{
    "type": "password",
    "value": "testpass",
    "temporary": false
  }]
}
```

`testuser` has both `access:weather` and `access:calculator` roles, granting full access to all MCP servers via token exchange.

A second user with limited access is also defined:

```json
{
  "username": "limiteduser",
  "enabled": true,
  "emailVerified": true,
  "email": "limiteduser@mcp-poc.local",
  "realmRoles": ["default-roles-mcp-poc", "access:weather"],
  "credentials": [{
    "type": "password",
    "value": "testpass",
    "temporary": false
  }]
}
```

`limiteduser` only has the `access:weather` role. Token exchange requests targeting `mcp-calculator` will be denied by Keycloak with a 403 response.

Keycloak hashes the plaintext password on import. `temporary: false` prevents forced password change on first login.

### Keycloak Endpoints Used at Runtime

| Endpoint | Used By | Purpose |
|----------|---------|---------|
| `GET /realms/{realm}/protocol/openid-connect/auth` | Web frontend | Authorization Code redirect |
| `POST /realms/{realm}/protocol/openid-connect/token` | Web frontend | Code-for-token exchange |
| `POST /realms/{realm}/protocol/openid-connect/token` | Gateway | RFC 8693 token exchange |
| `GET /realms/{realm}/protocol/openid-connect/certs` | Gateway + servers | JWKS public keys |

## 2. MCP Servers

Each MCP server is a standalone FastMCP process. It validates incoming JWTs offline using Keycloak's JWKS endpoint and exposes domain-specific tools.

### Server Pattern

Every server follows the same structure:

```python
from fastmcp import FastMCP
from fastmcp.server.auth.providers.jwt import JWTVerifier
from fastmcp.server.dependencies import get_access_token

verifier = JWTVerifier(
    jwks_uri=f"{KEYCLOAK_URL}/realms/{REALM}/protocol/openid-connect/certs",
    issuer=f"{KEYCLOAK_URL}/realms/{REALM}",
    audience="<this-server-client-id>",
    algorithm="RS256",
)

mcp = FastMCP("<Server Name>", auth=verifier)
```

Key FastMCP APIs:
- `JWTVerifier` -- validates JWT signature against cached JWKS keys, checks `iss`, `aud`, `exp`. Keys are fetched periodically from the JWKS URI (no per-request call).
- `get_access_token()` -- returns the `AccessToken` from the current request context. Available properties: `.token` (raw JWT string), `.claims` (decoded payload dict), `.scopes`, `.client_id`, `.expires_at`.
- `mcp.run(transport="streamable-http", port=N)` -- starts the server on an HTTP transport using the MCP Streamable HTTP protocol. The default endpoint path is `/mcp`.

### Tool Implementation

Tools are decorated with `@mcp.tool()` and can access the caller's identity via `get_access_token()`. The weather server uses the [Open-Meteo API](https://open-meteo.com/) (free, no API key) for real weather data:

```python
@mcp.tool()
async def get_weather(location: str) -> dict:
    """Get current weather for a location"""
    token = get_access_token()
    user = token.claims.get("preferred_username", "unknown") if token else "anonymous"
    geo = await geocode(location)  # Open-Meteo Geocoding API -> lat/lon
    # Open-Meteo Forecast API -> current weather
    resp = await http.get(FORECAST_URL, params={
        "latitude": geo["lat"], "longitude": geo["lon"],
        "current": "temperature_2m,relative_humidity_2m,weather_code,wind_speed_10m",
    })
    current = resp.json()["current"]
    return {"location": f"{geo['name']}, {geo['country']}", "temperature": current["temperature_2m"], ...}
```

Open-Meteo APIs used:
- **Geocoding**: `https://geocoding-api.open-meteo.com/v1/search?name={location}` -- resolves location name to lat/lon
- **Forecast**: `https://api.open-meteo.com/v1/forecast?latitude=...&longitude=...` -- returns current weather and daily forecasts
- WMO weather codes are mapped to human-readable conditions (e.g. code 3 = "Overcast")

The `get_access_token()` call is context-aware -- FastMCP sets up a contextvar per incoming request. The token available here is the exchanged token (scoped to this server's audience), not the user's original token.

### Port Assignments

| Server | Port | Audience |
|--------|------|----------|
| Weather | 8011 | `mcp-weather` |
| Calculator | 8012 | `mcp-calculator` |

Ports are configurable via environment variables (`WEATHER_PORT`, `CALCULATOR_PORT`).

## 3. MCP Gateway

The gateway is the central component. It validates user tokens, manages dynamic tool discovery, performs token exchange, and proxies tool calls to real MCP servers.

### JWT Validation

The gateway uses the same `JWTVerifier` pattern as the MCP servers, but with `audience="mcp-gateway"`:

```python
verifier = JWTVerifier(
    jwks_uri=f"{KEYCLOAK_URL}/realms/{REALM}/protocol/openid-connect/certs",
    issuer=f"{KEYCLOAK_URL}/realms/{REALM}",
    audience="mcp-gateway",
    algorithm="RS256",
)
mcp = FastMCP("MCP Gateway", auth=verifier)
```

This means the gateway will only accept tokens where `"mcp-gateway"` appears in the `aud` claim -- which is true for tokens issued to `adk-web-client` (because of the `mcp-gateway-audience` scope).

### Server Configuration (YAML)

Available MCP servers are defined in a YAML config file rather than hardcoded:

```yaml
servers:
  weather:
    description: "Weather information service"
    url: "http://localhost:8011"
    keycloak_audience: "mcp-weather"
    required_role: "access:weather"
  calculator:
    description: "Mathematical calculator service"
    url: "http://localhost:8012"
    keycloak_audience: "mcp-calculator"
    required_role: "access:calculator"
```

Each entry has four fields:
- `description` -- shown to the agent when it calls `search_servers`
- `url` -- the base URL of the MCP server (FastMCP appends `/mcp`)
- `keycloak_audience` -- the Keycloak client ID used as the `audience` parameter in token exchange
- `required_role` -- the realm role the user must have for Keycloak to approve the token exchange. This role is checked by the V1 fine-grained permission policy on the target client. The gateway can also use this field to provide early feedback before attempting the exchange.

The gateway loads this at startup:

```python
config_path = os.path.join(os.path.dirname(__file__), "servers.yaml")
with open(config_path) as f:
    AVAILABLE_SERVERS = yaml.safe_load(f)["servers"]
```

### Token Exchange

The gateway performs RFC 8693 token exchange by POSTing to Keycloak's token endpoint with the gateway's own client credentials:

```python
async def exchange_token(user_token: str, target_audience: str) -> str:
    async with httpx.AsyncClient() as http:
        resp = await http.post(TOKEN_ENDPOINT, data={
            "grant_type": "urn:ietf:params:oauth:grant-type:token-exchange",
            "client_id": GATEWAY_CLIENT_ID,
            "client_secret": GATEWAY_CLIENT_SECRET,
            "subject_token": user_token,
            "subject_token_type": "urn:ietf:params:oauth:token-type:access_token",
            "audience": target_audience,
        })
        resp.raise_for_status()
        return resp.json()["access_token"]
```

Keycloak validates:
1. The subject token is valid and not expired
2. The subject token's `aud` claim includes `mcp-gateway`
3. The `mcp-gateway` client's scopes include the requested audience
4. **V1 fine-grained permissions**: the target client (e.g. `mcp-weather`) has a `token-exchange` permission with a role-based policy that checks whether the subject user has the required role (e.g. `access:weather`). If the user lacks the role, Keycloak returns **403 Forbidden** and the exchange is denied.

It then issues a new access token with `aud` set to the target (e.g. `mcp-weather`).

The gateway handles the 403 case by raising a `PermissionError` with a descriptive message:

```python
if resp.status_code == 403:
    raise PermissionError(
        f"Token exchange denied for audience '{target_audience}'. "
        f"User lacks the required role."
    )
resp.raise_for_status()
```

This error propagates back through the dynamic tool proxy to the agent, which can inform the user that they lack permission to use the requested server.

### Calling Remote MCP Servers

The gateway uses FastMCP's `Client` to call tools on remote servers. The client connects via Streamable HTTP and passes the exchanged token as a Bearer header:

```python
async def call_mcp_server(server_url: str, tool_name: str, arguments: dict, token: str):
    async with Client(f"{server_url}/mcp", auth=token) as client:
        result = await client.call_tool(tool_name, arguments)
        if result.content:
            return result.content[0].text
        return str(result.data)
```

Key FastMCP Client APIs:
- `Client(url, auth=token)` -- creates a client that sends `Authorization: Bearer {token}` on every request. The `auth` parameter accepts a raw token string (without the `Bearer ` prefix).
- `await client.list_tools()` -- returns a list of tool definitions (name, description, inputSchema)
- `await client.call_tool(name, arguments)` -- calls a tool, returns a result object with `.content` (list of content blocks) and `.data` (deserialized Python value)

### Built-in Tools

**`search_servers(query: str = "", ctx: Context = None)`** -- returns a list of available servers from the YAML config, filtered by query. Only returns servers the user has access to -- servers whose `required_role` the user lacks are excluded from results. Indicates which are already enabled in the calling session.

**`enable_server(server_name: str, ctx: Context = None)`** -- activates a server for the calling session. Flow:
1. Look up server in `AVAILABLE_SERVERS`
2. Check if already enabled in this session's state
3. Get the user's token from `get_access_token()`
4. Exchange it for a server-specific token
5. Connect to the real MCP server and call `list_tools()` to discover its tools
6. Register each tool as a dynamic proxy function (idempotent -- skipped if already registered by another session)
7. Store the tool names in the session's `enabled_servers` entry
8. Subsequent `tools/list` calls will include the new tools

**`_reset_gateway(ctx: Context = None)`** -- resets gateway state for test isolation. Clears the calling session's enabled servers entry. Dynamic tools remain registered globally (other sessions may still use them). Called by BDD test `Before` hook before each scenario to ensure a clean slate.

### Dynamic Tool Registration

This is the most technically interesting part of the gateway. When a server is enabled, the gateway creates proxy functions that forward calls through token exchange to the real server.

The challenge: FastMCP requires tool functions with proper Python type signatures (the LLM needs to know parameter types). But the tool schemas are discovered at runtime from the remote server.

Solution: use `exec()` to generate typed async functions dynamically.

```python
def _register_dynamic_tool(server_name, tool_name, description, input_schema):
    properties = input_schema.get("properties", {})
    required = input_schema.get("required", [])

    # Map JSON Schema types to Python types
    type_map = {"string": "str", "integer": "int", "number": "float", "boolean": "bool"}

    # Build parameter list with types
    param_list = []
    for pname, pinfo in properties.items():
        ptype = type_map.get(pinfo.get("type", "string"), "str")
        if pname in required:
            param_list.append(f"{pname}: {ptype}")
        else:
            param_list.append(f"{pname}: {ptype} = None")

    params_str = ", ".join(param_list)
    param_names = list(properties.keys())

    # Generate async proxy function source code
    func_code = f"""
async def {tool_name}({params_str}):
    '''{description}'''
    arguments = {{{", ".join([f'"{p}": {p}' for p in param_names])}}}
    arguments = {{k: v for k, v in arguments.items() if v is not None}}
    token = _get_access_token()
    exchanged = await _exchange_token(token.token, "{audience}")
    return await _call_mcp_server("{server_url}", "{tool_name}", arguments, exchanged)
"""

    # Execute with helper functions in namespace
    namespace = {
        "_get_access_token": get_access_token,
        "_exchange_token": exchange_token,
        "_call_mcp_server": call_mcp_server,
    }
    exec(func_code, namespace)
    dynamic_func = namespace[tool_name]

    # Register with FastMCP
    mcp.tool()(dynamic_func)
```

What this produces for a tool like `get_weather(location: str)`:

```python
async def get_weather(location: str, ctx: _Context = None):
    '''Get current weather for a location'''
    session_id = ctx.session_id if ctx else "global"
    session = _enabled_servers.get(session_id, {})
    if "weather" not in session:
        return {"error": "Server 'weather' is not enabled in this session. Call enable_server('weather') first."}
    arguments = {"location": location}
    arguments = {k: v for k, v in arguments.items() if v is not None}
    token = _get_access_token()
    exchanged = await _exchange_token(token.token, "mcp-weather")
    return await _call_mcp_server("http://localhost:8011", "get_weather", arguments, exchanged)
```

The generated function:
1. Checks that the server is enabled in the calling session (returns error if not)
2. Collects the parameters into a dict
3. Gets the current user's token from FastMCP request context
4. Exchanges it for a server-scoped token
5. Calls the real server via FastMCP Client

Dynamic tools are registered globally on the FastMCP instance (since `_tool_manager` is shared), but each tool checks the calling session's `enabled_servers` before executing. This means tools show up in `tools/list` for all sessions, but return an error if the server hasn't been enabled in the calling session.

`mcp.tool()` registers it with the gateway. The next time the agent calls `tools/list`, this function appears alongside the built-in tools.

### Gateway State

```python
enabled_servers = {}  # {session_id: {server_name: [tool_names]}}
_registered_tools = set()  # tool names already registered globally on mcp
```

A per-session dict mapping MCP session IDs to their enabled servers. Each session (each MCP client connection) has its own set of enabled servers -- a tool activated in session A is not visible as enabled in session B. Session IDs come from FastMCP's `Context.session_id` (the `Mcp-Session-Id` header).

Dynamic tools are registered globally on the FastMCP instance (since `_tool_manager` is global), but each tool checks the calling session's enabled servers before executing. If the server isn't enabled in the caller's session, the tool returns an error. The `_registered_tools` set prevents double-registration when multiple sessions enable the same server.

In-memory only, lost on restart. This is acceptable for a PoC.

## 4. Web Frontend (Login + ADK Web UI)

The web frontend is a FastAPI application that:
1. Handles Keycloak OIDC login (Authorization Code + PKCE)
2. Manages sessions (cookie-based)
3. Mounts the ADK Web UI as a sub-application

### PKCE Implementation

PKCE (Proof Key for Code Exchange) prevents authorization code interception. It requires generating a random `code_verifier` and deriving a `code_challenge` (SHA-256 hash, base64url-encoded):

```python
def _generate_pkce():
    verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(verifier.encode()).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
    return verifier, challenge
```

The verifier is stored server-side (keyed by the `state` parameter) between the redirect and callback.

### Login Flow

**`GET /login`**

1. Generate a random `state` and PKCE pair
2. Store `_pkce_verifiers[state] = verifier`
3. Redirect to Keycloak's authorization endpoint:

```
GET /realms/mcp-poc/protocol/openid-connect/auth
  ?client_id=adk-web-client
  &response_type=code
  &redirect_uri=http://localhost:8000/callback
  &scope=openid profile email
  &state=<random>
  &code_challenge=<S256 hash>
  &code_challenge_method=S256
```

**`GET /callback?code=...&state=...`**

1. Pop the PKCE verifier for the received `state`
2. Exchange the authorization code for tokens:

```
POST /realms/mcp-poc/protocol/openid-connect/token
  grant_type=authorization_code
  client_id=adk-web-client
  code=<authorization_code>
  redirect_uri=http://localhost:8000/callback
  code_verifier=<verifier>
```

3. Extract `access_token` from the response
4. Generate a random session ID
5. Store `sessions[session_id] = access_token`
6. Set the global `current_token = access_token`
7. Set a signed session cookie and redirect to `/adk/dev-ui/`

### Session Management

Sessions are stored in-memory as a dict: `sessions = {session_id: access_token}`.

The session cookie is signed using `itsdangerous.URLSafeSerializer` to prevent tampering:

```python
serializer = URLSafeSerializer(SESSION_SECRET)

# Write
response.set_cookie(COOKIE_NAME, serializer.dumps(session_id), httponly=True, samesite="lax")

# Read
session_id = serializer.loads(request.cookies.get(COOKIE_NAME))
```

The cookie is `httponly` (no JavaScript access) and `samesite=lax` (CSRF protection).

### Token Propagation

The `current_token` global variable bridges the web session to the agent's MCP calls. This is the simplest possible approach for a single-user PoC.

```python
# In web.py
current_token = None  # set on login, cleared on logout

# In main.py
def _header_provider(readonly_context):
    from agent.web import current_token
    if current_token:
        return {"Authorization": f"Bearer {current_token}"}
    return {}
```

The import is deferred (inside the function body) to avoid circular imports at module load time.

### Mounting ADK Web UI

Google ADK provides `get_fast_api_app()` which returns a full FastAPI application with the agent API and Angular web UI:

```python
from google.adk.cli.fast_api import get_fast_api_app

adk_app = get_fast_api_app(
    agents_dir=str(Path(__file__).parent),  # directory containing __init__.py with root_agent
    allow_origins=["*"],
    web=True,                               # serve the Angular UI at /dev-ui/
    url_prefix="/adk",                      # tell the UI where the API lives
)
app.mount("/adk", adk_app)
```

Key parameters:
- `agents_dir` -- must point to the directory containing the agent package (with `__init__.py` exporting `root_agent`)
- `web=True` -- includes the Angular dev UI at `<prefix>/dev-ui/`
- `url_prefix="/adk"` -- since the app is mounted at `/adk`, the frontend needs to know to prefix API calls with `/adk`

After mounting, the web UI is accessible at `http://localhost:8000/adk/dev-ui/`.

## 5. Agent Configuration

The ADK agent connects to the MCP gateway via `McpToolset` with Streamable HTTP transport.

### McpToolset with header_provider

```python
from google.adk.tools.mcp_tool import StreamableHTTPConnectionParams, McpToolset

connection_params = StreamableHTTPConnectionParams(
    url="http://localhost:8010/mcp",
    timeout=60,
    sse_read_timeout=300,
)

mcp_toolset = McpToolset(
    connection_params=connection_params,
    header_provider=_header_provider,
)
```

The `header_provider` is a callable with signature `(ReadonlyContext) -> dict[str, str]`. It is called before every MCP request to inject custom headers. The returned dict is merged into the HTTP request headers.

The `StreamableHTTPConnectionParams.url` must include the `/mcp` path suffix -- this is FastMCP's default `streamable_http_path`.

### Agent Definition

```python
from google.adk.agents import Agent
from google.adk.models.lite_llm import LiteLlm

root_agent = Agent(
    name="mcp_gateway_agent",
    model=LiteLlm(model=MODEL_NAME),
    tools=[mcp_toolset],
    instruction="...",
)
```

The agent is exported from the package's `__init__.py`:

```python
from .main import root_agent
```

This is required for `get_fast_api_app(agents_dir=...)` to discover the agent.

## 6. Environment Variables

| Variable | Default | Used By | Purpose |
|----------|---------|---------|---------|
| `KEYCLOAK_URL` | `http://localhost:8080` | Gateway, servers, web | Keycloak base URL |
| `KEYCLOAK_REALM` | `mcp-poc` | Gateway, servers, web | Realm name |
| `KEYCLOAK_GATEWAY_CLIENT_ID` | `mcp-gateway` | Gateway | Client ID for token exchange |
| `KEYCLOAK_GATEWAY_CLIENT_SECRET` | `mcp-gateway-secret` | Gateway | Client secret for token exchange |
| `KEYCLOAK_ADK_CLIENT_ID` | `adk-web-client` | Web | Client ID for OIDC login |
| `MODEL_NAME` | `vertex_ai/gemini-2.5-flash` | Agent | LiteLLM model identifier |
| `MCP_PORT` | `8010` | Gateway | Gateway listen port |
| `MCP_URL` | `http://localhost:8010/mcp` | Agent | Gateway URL (with /mcp path) |
| `WEATHER_PORT` | `8011` | Weather server | Listen port |
| `CALCULATOR_PORT` | `8012` | Calculator server | Listen port |
| `ADK_PORT` | `8000` | Web | Web frontend listen port |
| `SESSION_SECRET` | random | Web | Cookie signing key |

## 7. Port Map

| Port | Component | Protocol |
|------|-----------|----------|
| 8080 | Keycloak | HTTP (OIDC, JWKS, token exchange) |
| 8010 | MCP Gateway | HTTP (MCP Streamable HTTP) |
| 8011 | Weather MCP Server | HTTP (MCP Streamable HTTP) |
| 8012 | Calculator MCP Server | HTTP (MCP Streamable HTTP) |
| 8000 | Web Frontend + ADK UI | HTTP (FastAPI) |

## 8. Project Structure

```
project/
├── docker-compose.yml              # Keycloak container
├── keycloak/
│   ├── mcp-poc-realm.json          # Realm with clients, scopes, mappers, user
│   └── setup-permissions.sh        # Configures V1 fine-grained token-exchange permissions
├── gateway/
│   ├── __init__.py
│   ├── server.py                   # Gateway: auth, token exchange, dynamic tools
│   └── servers.yaml                # Server registry config
├── servers/
│   ├── weather_server.py           # Weather MCP server (port 8011)
│   └── calculator_server.py        # Calculator MCP server (port 8012)
├── agent/
│   ├── __init__.py                 # Exports root_agent
│   ├── main.py                     # ADK agent + McpToolset with header_provider
│   └── web.py                      # FastAPI: login, session, mounts ADK UI
├── tests/
│   └── bdd/                        # Cucumber.js BDD test suite
│       ├── package.json            # npm deps: @cucumber/cucumber, @modelcontextprotocol/sdk
│       ├── tsconfig.json           # TypeScript config (ES2022, NodeNext)
│       ├── cucumber.cjs            # Cucumber profiles (default, all)
│       ├── .env / .env.example     # Test configuration
│       ├── features/               # 7 Gherkin feature files (45 scenarios)
│       │   ├── discover_servers.feature
│       │   ├── activate_server.feature
│       │   ├── aggregated_tools.feature
│       │   ├── tool_forwarding.feature
│       │   ├── security.feature
│       │   ├── token_exchange.feature
│       │   └── end_to_end.feature
│       ├── steps/
│       │   └── gateway.steps.ts    # All step definitions
│       └── support/
│           └── world.ts            # Custom World class
├── doc/
│   ├── ARCHITECTURE.md             # Architecture (implementation-agnostic)
│   ├── IMPLEMENTATION.md           # Implementation details
│   └── IMPLEMENTATION-BDD.md       # BDD test approach + scenarios
├── requirements.txt
├── .env                            # Runtime config (not committed)
└── .env.example                    # Template
```

## 9. Startup Sequence

The components must start in dependency order:

```
1. docker-compose up -d                    # Keycloak (wait ~30s for boot)
2. ./keycloak/setup-permissions.sh         # Configure V1 fine-grained permissions
3. python servers/weather_server.py        # Weather server on :8011
4. python servers/calculator_server.py     # Calculator server on :8012
5. python gateway/server.py               # Gateway on :8010
6. python agent/web.py                    # Web frontend on :8000
```

Step 2 (`setup-permissions.sh`) must run after Keycloak has fully started. It uses the Keycloak Admin REST API to configure token-exchange permissions with role-based policies on each target client. This only needs to run once after initial realm import (the permissions persist across Keycloak restarts).

The gateway does not need the MCP servers running at startup -- it only contacts them when `enable_server` is called. But Keycloak must be running for JWT validation (JWKS fetch).

## 10. Adding a New MCP Server

To add a new server (e.g. `email`):

**1. Keycloak** -- add to realm JSON (or via Admin Console):
  - New client: `mcp-email`, bearer-only
  - New client scope: `mcp-email-audience` with `oidc-audience-mapper` for `mcp-email`
  - Add `mcp-email-audience` to `mcp-gateway`'s default client scopes

**2. Server code** -- create `servers/email_server.py`:
  - `JWTVerifier(audience="mcp-email")`
  - Register tools with `@mcp.tool()`
  - Run on a new port (e.g. 8013)

**3. Gateway config** -- add entry to `servers.yaml`:
```yaml
  email:
    description: "Email service"
    url: "http://localhost:8013"
    keycloak_audience: "mcp-email"
```

**4. Restart** the gateway (to reload YAML). No code changes needed in the gateway or agent. The agent discovers the new server via `search_servers`.

## 11. Token Lifecycle

```
Time 0s    User clicks "Login with Keycloak"
           → PKCE challenge generated, redirect to Keycloak

Time ~5s   User authenticates, Keycloak redirects to /callback
           → Auth code exchanged for access_token (1h lifespan)
           → Token stored in session + global variable

Time ~10s  User chats with agent, agent calls search_servers
           → header_provider injects Bearer token
           → Gateway validates JWT (aud=mcp-gateway, exp not passed)

Time ~15s  Agent calls enable_server("weather")
           → Gateway: get_access_token() extracts user token
           → Gateway: POST /token (grant_type=token-exchange, audience=mcp-weather)
           → Keycloak returns new token (aud=mcp-weather)
           → Gateway: connect to weather server, discover tools

Time ~20s  Agent calls get_weather("Paris")
           → Gateway proxy: get_access_token() → exchange → call weather server
           → Weather server: validate token (aud=mcp-weather) → execute → respond

Time 3600s Token expires
           → All subsequent calls fail with 401
           → User must log in again (no refresh token in this PoC)
```

## 12. Key Implementation Details

### Why `exec()` for Dynamic Tools

FastMCP inspects function signatures (parameter names, types, defaults) to generate the JSON Schema exposed to the LLM. A generic `def proxy(**kwargs)` function would lose all type information and the LLM wouldn't know what parameters the tool accepts.

By generating source code with explicit typed parameters and executing it, we get proper function objects with correct `__annotations__`, `__defaults__`, and `__doc__` -- exactly what FastMCP needs.

### Why `get_access_token()` Works in Dynamic Tools

`get_access_token()` uses Python's `contextvars` internally. FastMCP sets the context variable for each incoming HTTP request before calling the tool handler. Since the dynamically registered functions are called by FastMCP as regular tool handlers, the context is always set correctly.

### Why Deferred Import in header_provider

```python
def _header_provider(readonly_context):
    from agent.web import current_token  # deferred
    ...
```

`agent/main.py` is imported by `agent/__init__.py`, which is imported by `agent/web.py` (via `get_fast_api_app(agents_dir=...)`). If `main.py` imported `web.py` at module level, it would create a circular import. The deferred import inside the function body avoids this -- by the time `_header_provider` is called, both modules are fully loaded.

### FastMCP Default MCP Path

FastMCP servers expose the MCP protocol at `/mcp` by default. Both the gateway URL and the server URLs must include this suffix:
- Agent connects to gateway: `http://localhost:8010/mcp`
- Gateway connects to servers: `http://localhost:8011/mcp`
