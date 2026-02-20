# Architecture: Authenticated Dynamic MCP Gateway

## Problem Statement

AI agents need access to many tool-providing services, but granting broad access upfront is both a security risk and a usability burden. We need a system where:

- An agent discovers and activates tool providers on demand
- Each tool invocation carries the identity of the end user
- Each tool provider receives only the minimum credentials it needs
- No component trusts another implicitly -- every hop is authenticated
- Tool activations are isolated per session -- one user's choices don't affect another

## System Overview

Four logical components interact through authenticated channels:

```
                          ┌──────────────────┐
                          │  Identity Provider│
                          │  (OIDC/OAuth2)    │
                          └──┬─────┬─────┬───┘
                  login/     │     │     │   token
                  tokens     │     │     │   exchange
         ┌───────────────────┘     │     └──────────────────┐
         │              JWKS ──────┼─────── JWKS            │
         ▼                         ▼                        ▼
┌─────────────────┐     ┌──────────────────┐     ┌──────────────────┐
│   Web Frontend  │────▶│   MCP Gateway    │────▶│  MCP Server (N)  │
│   + AI Agent    │     │                  │     │                  │
└─────────────────┘     └──────────────────┘     └──────────────────┘
   user token              validates user          validates scoped
   in every request        token, exchanges        token offline
                           for scoped token
```

## Components

### 1. Identity Provider

An OpenID Connect / OAuth2 authorization server. It is the single source of truth for identity, credentials, and access policies. All other components defer to it for authentication and authorization decisions.

**Responsibilities:**

- **User authentication** -- login via browser using Authorization Code Flow with PKCE
- **Token issuance** -- access tokens with audience claims (`aud`) that identify the intended recipient
- **Token exchange** -- RFC 8693 endpoint that lets an authorized client swap a user's token for a narrower-scoped token targeting a different audience
- **Public key distribution** -- JWKS endpoint so all other components can validate token signatures offline, without calling back to the identity provider on every request
- **Access policy enforcement** -- role-based policies that control which users can exchange tokens for which target audiences

#### Clients Registered

The identity provider maintains a registry of clients (applications). Each client has a type and role in the system:

| Client | Type | Role |
|--------|------|------|
| Web Frontend | Public (PKCE) | User-facing login. No client secret -- security relies on PKCE challenge. |
| MCP Gateway | Confidential | Authenticates with client ID + secret. Performs token exchange on behalf of users. |
| MCP Server (per server) | Bearer-only resource server | Never initiates login flows. Exists solely as an audience target -- tokens exchanged for its audience are validated by the server itself. |

#### Audience Scopes and Mappers

Each audience target requires a **client scope** containing an **audience mapper**. The mapper injects the target client ID into the `aud` claim of issued tokens. Scopes are assigned to clients to control which audiences their tokens can contain:

- The web frontend client gets a scope that adds the gateway to the `aud` claim of user tokens
- The gateway client gets scopes for each MCP server, enabling it to request exchanged tokens with those audiences

This means the identity provider controls the full audience chain through configuration -- no code changes are needed to add or remove audience targets.

#### Realm Roles and Per-User Access Control

The identity provider defines **realm-level roles** (e.g. `access:weather`, `access:calculator`). These roles are assigned to individual users and serve as the basis for access control during token exchange.

Each MCP server's client has a **token-exchange permission** backed by a **role-based policy**. The policy checks whether the user whose token is being exchanged holds the required role. If the user lacks the role, the identity provider denies the exchange with an HTTP 403 response.

This design keeps access control entirely within the identity provider -- the gateway does not need to maintain access control lists or make authorization decisions.

### 2. Web Frontend + AI Agent

A web application serving two purposes:

**Authentication layer:**

1. User visits the application and clicks "Login"
2. Application generates a random `state` parameter and a PKCE pair (code verifier + code challenge)
3. Application stores the code verifier server-side, keyed by `state`
4. Application redirects the browser to the identity provider's authorization endpoint with:
   - `response_type=code`
   - `code_challenge` (SHA-256 hash of verifier, base64url-encoded)
   - `code_challenge_method=S256`
   - `state` (for CSRF protection and verifier lookup)
5. User authenticates at the identity provider (username/password form)
6. Identity provider redirects back to the application's callback URL with an authorization code
7. Application exchanges the code + code verifier for an access token at the token endpoint
8. Application creates a server-side session (session ID in a signed HTTP-only cookie, maps to the access token)

**PKCE** (Proof Key for Code Exchange, RFC 7636) protects against authorization code interception. Since the web frontend is a public client (no client secret), PKCE is the only mechanism preventing a stolen authorization code from being exchanged for tokens.

**Agent runtime:**

- Hosts the AI agent's conversational interface
- When the agent makes MCP tool calls, the user's access token is attached as an `Authorization: Bearer` header
- The agent itself is unaware of authentication -- a **header provider** function transparently injects the token from the current session
- The agent connects to the gateway over MCP Streamable HTTP transport

### 3. MCP Gateway

The central routing and authorization layer. It is the only MCP endpoint the agent connects to. It exposes the MCP protocol over Streamable HTTP and manages dynamic tool discovery with per-session isolation.

#### Request Authentication

Every incoming MCP request carries a JWT in the `Authorization: Bearer` header. The gateway validates it:

1. **Signature verification** -- the token's signature is checked against the identity provider's public keys (fetched from the JWKS endpoint and cached)
2. **Issuer check** -- the `iss` claim must match the identity provider's realm URL
3. **Audience check** -- the `aud` claim must include the gateway's client ID
4. **Expiration check** -- the `exp` claim must be in the future

If any check fails, the request is rejected. No tool execution occurs.

This validation is **offline** -- the gateway never calls back to the identity provider for per-request authorization. It only fetches public keys periodically from the JWKS endpoint.

#### Built-in Tools

Three tools are always available, regardless of session state:

| Tool | Purpose |
|------|---------|
| `search_servers` | List available MCP servers from the configuration file. Reports which servers are enabled in the calling session. |
| `enable_server` | Activate an MCP server for the calling session. Performs token exchange, discovers tools, registers proxies. |
| `_reset_gateway` | Clear the calling session's state (for test isolation). |

#### Per-Session Tool State

The gateway maintains a **per-session activation map**: a mapping from MCP session ID to the set of servers enabled in that session, along with their discovered tool names.

```
session-abc → {weather: [get_weather, get_forecast]}
session-xyz → {calculator: [calculate]}
session-abc → (has weather tools, not calculator)
session-xyz → (has calculator tools, not weather)
```

**MCP session ID** is a protocol-level identifier assigned during the MCP `initialize` handshake. It is carried as an HTTP header (`Mcp-Session-Id`) on every subsequent request in that session. Each MCP client connection (each agent conversation) gets its own session ID.

This means:
- Server activation in session A has no effect on session B
- `search_servers` reports `enabled: true/false` relative to the calling session
- Dynamic tools check the calling session before executing

#### Dynamic Tool Registration

When `enable_server(name)` is called:

```
┌─────┐          ┌─────────┐          ┌────────┐          ┌──────────┐
│Agent│          │ Gateway │          │Identity│          │MCP Server│
└──┬──┘          └────┬────┘          └───┬────┘          └────┬─────┘
   │                  │                   │                    │
   │ enable_server(X) │                   │                    │
   │─────────────────▶│                   │                    │
   │                  │                   │                    │
   │                  │ 1. Check user role │                    │
   │                  │   (from JWT claims)│                    │
   │                  │                   │                    │
   │                  │ 2. Token exchange  │                    │
   │                  │   (RFC 8693)       │                    │
   │                  │──────────────────▶│                    │
   │                  │   scoped token    │                    │
   │                  │◀──────────────────│                    │
   │                  │                   │                    │
   │                  │ 3. Tool discovery  │                    │
   │                  │   (MCP tools/list) │                    │
   │                  │──────────────────────────────────────▶│
   │                  │                   │   tool definitions │
   │                  │◀──────────────────────────────────────│
   │                  │                   │                    │
   │                  │ 4. Register proxy tools               │
   │                  │    (global, idempotent)                │
   │                  │                   │                    │
   │                  │ 5. Record activation                   │
   │                  │    in session state                    │
   │                  │                   │                    │
   │ {tools: [...]}   │                   │                    │
   │◀─────────────────│                   │                    │
```

Step by step:

1. **Role check** -- the gateway reads the user's roles from the JWT claims and checks whether the user has the role required by the target server (e.g. `access:weather`). This is a fast pre-check before making a network call. If the user lacks the role, the request fails immediately with a descriptive error.

2. **Token exchange** -- the gateway sends an RFC 8693 request to the identity provider (see [Token Exchange](#token-exchange-rfc-8693) below). If the identity provider denies the exchange (e.g. the user lacks the role in Keycloak's fine-grained policy), the request fails with a permission error.

3. **Tool discovery** -- the gateway connects to the MCP server using the exchanged token and calls `tools/list`. This returns the server's tool definitions: names, descriptions, and JSON Schema parameter specifications.

4. **Proxy registration** -- for each discovered tool, the gateway registers a proxy function that the agent can call. Registration is **global** (the proxy is available to all sessions) but **idempotent** (if another session already registered the same tool, it is skipped). The proxy function has the same typed signature as the original tool, so the LLM sees correct parameter names and types.

5. **Session recording** -- the activation is recorded in the calling session's state. Only this session will be allowed to execute the tool.

#### Tool Proxying

When a dynamically registered tool is called by the agent:

```
Agent calls get_weather("Paris")
  │
  ▼
Gateway proxy function:
  1. Check session: is "weather" enabled for this session?
     NO  → return error: "Server 'weather' is not enabled in this session"
     YES → continue
  │
  ▼
  2. Extract user's JWT from request context
  │
  ▼
  3. Check user role (from JWT claims)
     FAIL → return error: "Access denied: user lacks role"
  │
  ▼
  4. Token exchange: swap user JWT for server-scoped JWT
     POST /token (grant_type=token-exchange, audience=mcp-weather)
     FAIL → return error from identity provider
  │
  ▼
  5. Forward MCP call to server with exchanged token
     Authorization: Bearer <exchanged-token>
  │
  ▼
  6. Return server's response to agent
```

Token exchange happens on **every tool call**, not just on `enable_server`. This ensures each call uses a fresh token and the identity provider can enforce access control at any point (e.g. if a role is revoked mid-session).

#### Server Configuration

The gateway's server registry is externalized to a configuration file:

```
servers:
  <name>:
    description: <human-readable description shown to the agent>
    url: <MCP server base URL>
    audience: <identity provider client ID for token exchange>
    required_role: <realm role the user must have>
```

Adding a new server is a configuration change -- no gateway or agent code changes are needed.

### 4. MCP Servers

Standalone MCP-protocol servers, each providing domain-specific tools (weather data, calculations, etc.).

**Authentication:**
- Each server validates incoming JWTs offline using the identity provider's JWKS public keys
- Each server checks three things: signature validity, issuer match, and that the `aud` claim contains **its own** client ID
- A token meant for the weather server will be rejected by the calculator server, and vice versa
- The server can extract user identity from token claims (e.g. `sub`, `preferred_username`) for audit logging or per-user behavior

**No direct user interaction:**
- MCP servers never see the user's original token (which has `aud: mcp-gateway`)
- They only receive tokens that were explicitly exchanged by the gateway for their specific audience
- A compromised or leaked server token cannot be used against a different server -- it only has the audience of the server it was exchanged for

## Token Exchange (RFC 8693)

The gateway performs **OAuth2 Token Exchange** as defined in [RFC 8693](https://datatracker.ietf.org/doc/html/rfc8693) -- specifically the **impersonation** semantics (the exchanged token represents the same user, with a narrower scope).

### Exchange Request

```
POST /token HTTP/1.1
Content-Type: application/x-www-form-urlencoded

grant_type=urn:ietf:params:oauth:grant-type:token-exchange
&client_id=<gateway-client-id>
&client_secret=<gateway-client-secret>
&subject_token=<user's access token>
&subject_token_type=urn:ietf:params:oauth:token-type:access_token
&audience=<target server's client ID>
```

Parameters:
- `grant_type` -- the RFC 8693 grant type URN, identifying this as a token exchange request
- `client_id` + `client_secret` -- the gateway authenticates itself as a confidential client
- `subject_token` -- the user's original access token (the one with `aud: mcp-gateway`)
- `subject_token_type` -- declares the subject token is an access token
- `audience` -- the target audience for the new token (e.g. `mcp-weather`)

### Exchange Validation

The identity provider performs a chain of validations before issuing the exchanged token:

1. **Gateway authentication** -- the gateway's client ID and secret must be valid
2. **Subject token validation** -- the user's token must not be expired, must have a valid signature, and must have the gateway in its `aud` claim
3. **Audience scope check** -- the gateway client must have a client scope that includes the requested audience (e.g. `mcp-weather-audience` scope)
4. **Fine-grained permission check** -- the target client (e.g. `mcp-weather`) must have a `token-exchange` permission with a role-based policy. The policy checks whether the subject user holds the required realm role (e.g. `access:weather`). If the user lacks the role, the identity provider returns **HTTP 403 Forbidden**.
5. **Token issuance** -- a new access token is issued with:
   - `aud` set to the target server's client ID
   - `sub` preserving the original user's identity
   - User claims (roles, username) carried over from the original token
   - A fresh `exp` timestamp

### Exchange Result

```
HTTP/1.1 200 OK
Content-Type: application/json

{
  "access_token": "<new JWT>",
  "token_type": "Bearer",
  "expires_in": 3600
}
```

Or, on permission denial:

```
HTTP/1.1 403 Forbidden
```

### Audience Narrowing

The token exchange implements **audience narrowing** -- each hop in the chain reduces the token's scope:

```
User login token                    Exchanged token
─────────────────                   ─────────────────
aud: [mcp-gateway]    ──exchange──▶ aud: [mcp-weather]
sub: user123                        sub: user123
roles: [access:weather, ...]        roles: [access:weather, ...]
exp: T+3600                         exp: T+3600
```

The exchanged token:
- Is only valid for one specific server (cannot be replayed against other servers)
- Preserves the user's identity (`sub`, `preferred_username`)
- Preserves the user's roles (so the server can perform additional authorization if needed)
- Is a completely new JWT with its own signature -- not a modified copy of the original

## Session and State Model

### Web Session (Browser to Frontend)

```
Browser                        Web Frontend (server-side)
──────                         ──────────────────────────
session cookie ──────────────▶ session store: {session_id → access_token}
(signed, httponly,              │
 samesite=lax)                  └──▶ header provider: injects Bearer token
                                     into agent's MCP requests
```

- The session cookie is **signed** (prevents tampering), **httponly** (no JavaScript access), and **samesite=lax** (CSRF protection)
- The access token is stored server-side, never exposed to the browser
- The agent uses a **header provider** function that reads the token from the session and injects it as `Authorization: Bearer <token>` into every outgoing MCP request

### MCP Session (Agent to Gateway)

```
Agent/MCP Client                    MCP Gateway
────────────────                    ───────────
                  ──initialize──▶   assigns Mcp-Session-Id
                  ◀──response───    returns session ID in header
                                    │
Mcp-Session-Id    ──tool call───▶   looks up session state:
(sent on every                      enabled_servers[session_id]
 subsequent request)                │
                                    └──▶ {weather: [get_weather, ...]}
```

- The MCP session ID is assigned during the MCP protocol `initialize` handshake
- The client sends it as an HTTP header (`Mcp-Session-Id`) on all subsequent requests
- The gateway uses this ID to look up the session's activation state
- Each MCP client connection (each browser tab, each test scenario) gets a unique session ID

### Tool Activation State

```
enabled_servers (in-memory):
  session-abc:
    weather:     [get_weather, get_forecast]
    calculator:  [calculate]
  session-xyz:
    weather:     [get_weather, get_forecast]

registered_tools (global set):
  {get_weather, get_forecast, calculate}
```

Two separate data structures:

1. **Per-session activation map** -- tracks which servers (and their tool names) are enabled in each session. Used by `search_servers` to report status and by proxy tools to check authorization.

2. **Global registered tools set** -- tracks which proxy functions have been registered on the gateway's MCP tool manager. Since the tool manager is global (shared across sessions), tools are registered once and reused. The set prevents double-registration when multiple sessions enable the same server.

The separation means:
- Tools appear in the gateway's `tools/list` response for all sessions (they are globally registered)
- But each tool checks the calling session's activation map before executing
- If a tool is called from a session that hasn't enabled its server, it returns an error directing the caller to use `enable_server` first

**State is in-memory only** -- lost on gateway restart. This is acceptable for a PoC.

## Security Model

### Trust Boundaries

```
┌─────────────────────────────────────────────────────┐
│ Trust Zone 1: User's browser                        │
│   - Holds signed session cookie                     │
│   - Never sees raw access tokens                    │
│   - Cannot forge or modify the session cookie       │
└───────────────────┬─────────────────────────────────┘
                    │ session cookie (signed, httponly)
┌───────────────────▼─────────────────────────────────┐
│ Trust Zone 2: Web frontend (server-side)            │
│   - Maps session → access token                     │
│   - Injects token into agent's MCP calls            │
│   - PKCE prevents authorization code interception   │
└───────────────────┬─────────────────────────────────┘
                    │ Bearer token (aud: mcp-gateway)
┌───────────────────▼─────────────────────────────────┐
│ Trust Zone 3: MCP Gateway                           │
│   - Validates JWT signature via JWKS (offline)      │
│   - Checks iss, aud, exp claims                     │
│   - Exchanges for scoped token (RFC 8693)           │
│   - Exchange subject to per-user role checks        │
│     enforced by the identity provider               │
│   - Per-session tool isolation                      │
│   - Holds gateway client credentials (client secret)│
└───────────────────┬─────────────────────────────────┘
                    │ Bearer token (aud: specific server)
┌───────────────────▼─────────────────────────────────┐
│ Trust Zone 4: MCP Server                            │
│   - Validates scoped token via JWKS (offline)       │
│   - Checks iss, aud (own client ID), exp claims     │
│   - Only accepts tokens for its own audience        │
│   - Never receives the user's original broad token  │
│   - Can extract user identity from claims (sub,     │
│     preferred_username) for audit or per-user logic  │
└─────────────────────────────────────────────────────┘
```

### JWT Verification (All Components)

Every component that receives a JWT performs the same verification:

1. **Fetch public keys** -- download the identity provider's JWKS (JSON Web Key Set) from its well-known endpoint. Keys are cached and refreshed periodically, not fetched per-request.
2. **Verify signature** -- check the JWT's signature against the JWKS public keys using RS256 (RSA + SHA-256). This proves the token was issued by the identity provider and has not been tampered with.
3. **Check issuer** -- the `iss` claim must match the identity provider's realm URL. Rejects tokens from other identity providers.
4. **Check audience** -- the `aud` claim must include the component's own client ID. The gateway requires `mcp-gateway`, the weather server requires `mcp-weather`, etc. Rejects tokens meant for other components.
5. **Check expiration** -- the `exp` claim must be in the future. Rejects expired tokens.

Since verification is offline (only public keys are needed, no callback to the identity provider), it scales independently and adds minimal latency.

### Principle of Least Privilege

- **The agent never holds credentials** -- tokens are injected transparently by the header provider
- **The gateway only holds its own client credentials** -- it cannot impersonate users without their token
- **Each MCP server only accepts tokens with its own audience** -- a token for the weather server cannot be used against the calculator server
- **A compromised server token cannot be replayed** -- it only has the audience of the server it was exchanged for
- **Token exchange is one-way** -- a server-scoped token cannot be exchanged back for a gateway-scoped token
- **Per-user access control** -- the identity provider restricts which servers each user can exchange tokens for, based on realm roles, without any gateway code changes
- **Per-session isolation** -- tool activations in one session do not affect other sessions

### Credential Exposure Matrix

| Component | Knows user password? | Holds access tokens? | Holds client secret? |
|-----------|---------------------|---------------------|---------------------|
| Browser | Entered, never stored | No (cookie only) | No |
| Web Frontend | No | Yes (server-side session store) | No (public client) |
| MCP Gateway | No | Yes (per-request, from Bearer header) | Yes (gateway secret) |
| MCP Server | No | Yes (per-request, from Bearer header) | No (bearer-only) |
| Identity Provider | Yes (hashed) | Issues them | Stores all client secrets |

## Complete Flow: End-to-End

```
1. User opens browser, visits web frontend
   │
   ▼
2. Web frontend redirects to identity provider
   GET /auth?response_type=code&code_challenge=...&state=...
   │
   ▼
3. User authenticates (username + password)
   │
   ▼
4. Identity provider redirects back with authorization code
   GET /callback?code=...&state=...
   │
   ▼
5. Web frontend exchanges code + PKCE verifier for access token
   POST /token (grant_type=authorization_code, code_verifier=...)
   → receives JWT with aud: [mcp-gateway]
   │
   ▼
6. Web frontend creates session, sets signed cookie
   │
   ▼
7. User chats with agent: "What's the weather in Warsaw?"
   │
   ▼
8. Agent calls MCP tools/list → [search_servers, enable_server]
   (Bearer token injected by header provider)
   │
   ▼
9. Agent calls search_servers() → [{name: weather, enabled: false}, ...]
   │
   ▼
10. Agent calls enable_server("weather")
    │
    ▼
11. Gateway: validates JWT (sig, iss, aud=mcp-gateway, exp)
    │
    ▼
12. Gateway: checks user has role "access:weather" (from JWT claims)
    │
    ▼
13. Gateway: POST /token (grant_type=token-exchange, audience=mcp-weather)
    → identity provider checks fine-grained permission + role
    → receives new JWT with aud: [mcp-weather]
    │
    ▼
14. Gateway: connects to weather server with exchanged token
    → calls tools/list → discovers [get_weather, get_forecast]
    │
    ▼
15. Gateway: registers proxy tools, records activation in session state
    → returns {success: true, tools: [get_weather, get_forecast]}
    │
    ▼
16. Agent calls get_weather("Warsaw")
    │
    ▼
17. Gateway proxy: checks session state (weather enabled? yes)
    │
    ▼
18. Gateway proxy: POST /token (grant_type=token-exchange, audience=mcp-weather)
    → fresh exchanged token
    │
    ▼
19. Gateway proxy: forwards call to weather server with exchanged token
    │
    ▼
20. Weather server: validates JWT (sig, iss, aud=mcp-weather, exp)
    → extracts user identity from claims
    → executes tool, returns result
    │
    ▼
21. Gateway returns result to agent → agent responds to user
```

## Extensibility

**Adding a new MCP server** requires only configuration changes:

1. **Identity provider** -- register a new bearer-only client (e.g. `mcp-email`), create an audience scope with mapper, assign the scope to the gateway client, create a token-exchange permission with a role-based policy
2. **Server deployment** -- deploy the MCP server with JWKS validation for its own audience
3. **Gateway configuration** -- add an entry to the server registry file (name, URL, audience, required role)
4. **Restart** the gateway to reload configuration

No code changes to the gateway or agent are needed. The agent discovers the new server at runtime via `search_servers` and activates it via `enable_server`.

## Key Design Decisions

| Decision | Rationale |
|----------|-----------|
| RFC 8693 token exchange (impersonation) | Principle of least privilege -- each server gets a token scoped only to itself, preserving user identity. The original broad token never leaves the gateway. |
| JWKS-based offline validation | No per-request calls to the identity provider -- every component validates tokens independently using cached public keys. Scales horizontally. |
| Token exchange on every tool call | Ensures freshness -- identity provider can revoke access mid-session by removing a role. Each call gets a new exchanged token. |
| Per-session tool activation | Isolation between concurrent users/conversations. One agent's choices don't affect another. Session ID comes from MCP protocol. |
| Global tool registration + session-scoped execution | Practical compromise -- MCP tool manager is shared, so tools are registered once globally. Session check before execution ensures access control. |
| Fine-grained permissions at identity provider | Access control is centralized. Adding/removing user access to a server is a role assignment change -- no gateway restarts or code changes. |
| PKCE for browser login | Secure for public clients -- no client secret in the browser. Prevents authorization code interception attacks. |
| Externalized server config (YAML) | Adding servers is an ops task, not a code change. Decouples gateway code from the set of available servers. |
| Gateway as the only token-exchange client | Single point of credential management for service-to-service auth. MCP servers don't need to know about the gateway's client secret. |
| In-memory state, no persistence | Acceptable for a PoC. State is lightweight and re-created quickly by re-enabling servers. |
