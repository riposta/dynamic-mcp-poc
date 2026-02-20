# BDD Test Implementation Guide

This document describes the BDD test suite for the MCP Gateway, covering all Gherkin scenarios and the Cucumber.js implementation. The approach mirrors the conventions established in the [mcp-orchestrator BDD suite](../../../IdeaProjects/mcp-orchestrator/tests/bdd).

## Framework & Stack

| Component | Technology | Purpose |
|-----------|-----------|---------|
| BDD Framework | Cucumber.js 10.x | Gherkin parser + runner |
| Language | TypeScript 5.x | Step definitions, support code |
| MCP Client | @modelcontextprotocol/sdk | MCP protocol communication |
| HTTP Client | Native fetch | Raw HTTP tests (auth validation) |
| Assertions | Node.js assert | Test assertions |
| Config | dotenv | Environment variables |

The tests are **external black-box tests** -- they connect to a running gateway over HTTP and exercise the MCP protocol. They do not import any application code.

## Project Structure

```
tests/bdd/
├── cucumber.cjs                    # Cucumber configuration + profiles
├── package.json                    # npm dependencies + scripts
├── tsconfig.json                   # TypeScript config
├── .env                            # JWT tokens, server URLs (not committed)
├── .env.example                    # Template
├── features/                       # Gherkin feature files
│   ├── discover_servers.feature    # Server discovery
│   ├── activate_server.feature     # Server activation + error handling
│   ├── aggregated_tools.feature    # Dynamic tools/list behavior
│   ├── tool_forwarding.feature     # Proxy tool calls to real servers
│   ├── security.feature            # JWT validation, auth enforcement
│   ├── token_exchange.feature      # RFC 8693 token exchange behavior
│   ├── end_to_end.feature          # Full login-to-tool-call flow
│   └── authorization.feature       # Per-user token exchange authorization
├── steps/
│   └── gateway.steps.ts            # All step definitions
└── support/
    └── world.ts                    # Custom World class (shared context)
```

## Configuration

### cucumber.cjs

```javascript
module.exports = {
  default: {
    import: ['dist/support/**/*.js', 'dist/steps/**/*.js'],
    features: ['features/**/*.feature'],
    format: ['progress', 'html:cucumber-report.html'],
    formatOptions: { snippetInterface: 'async-await' },
    timeout: 30000,
    parallel: 1,
    tags: 'not @pending and not @pending-mcp-sdk-behavior'
  },
  all: {
    import: ['dist/support/**/*.js', 'dist/steps/**/*.js'],
    features: ['features/**/*.feature'],
    format: ['progress', 'html:cucumber-report.html'],
    formatOptions: { snippetInterface: 'async-await' },
    timeout: 30000,
    parallel: 1
  }
};
```

**Profiles:**
- `default` -- skips known limitations, used for CI
- `all` -- runs everything including pending

### package.json

```json
{
  "name": "mcp-gateway-bdd",
  "version": "1.0.0",
  "type": "module",
  "scripts": {
    "build": "tsc",
    "test": "npm run build && cucumber-js",
    "test:only": "cucumber-js",
    "test:smoke": "npm run build && cucumber-js --tags @smoke"
  },
  "devDependencies": {
    "@cucumber/cucumber": "^10.0.1",
    "@modelcontextprotocol/sdk": "^1.26.0",
    "@types/node": "^20.10.6",
    "typescript": "^5.3.3",
    "dotenv": "^16.3.1",
    "assert": "^2.1.0"
  }
}
```

### tsconfig.json

```json
{
  "compilerOptions": {
    "target": "ES2022",
    "module": "NodeNext",
    "moduleResolution": "NodeNext",
    "outDir": "dist",
    "rootDir": ".",
    "strict": true,
    "esModuleInterop": true,
    "declaration": false,
    "sourceMap": true,
    "resolveJsonModule": true
  },
  "include": ["support/**/*.ts", "steps/**/*.ts"]
}
```

### .env.example

```bash
# Gateway URL (MCP streamable HTTP endpoint)
GATEWAY_URL=http://localhost:8010/mcp

# Keycloak token endpoint
KEYCLOAK_TOKEN_URL=http://localhost:8080/realms/mcp-poc/protocol/openid-connect/token

# Test user credentials (used to obtain JWT tokens at test startup)
TEST_USER=testuser
TEST_PASSWORD=testpass
KEYCLOAK_CLIENT_ID=adk-web-client

# Limited-access user credentials (for authorization tests)
LIMITED_USER=limiteduser
LIMITED_PASSWORD=limitedpass

# Pre-generated JWT tokens (alternative to live Keycloak login)
# JWT_TOKEN=<valid-access-token>
# JWT_TOKEN_EXPIRED=<expired-access-token>
```

## Tag System

| Tag | Meaning |
|-----|---------|
| `@smoke` | Core scenarios, run in CI |
| `@security` | JWT validation, auth enforcement |
| `@token-exchange` | Token exchange behavior |
| `@activation` | Server activation flow |
| `@tools` | tools/list assertions |
| `@tool-forwarding` | Proxy tool calls |
| `@e2e` | End-to-end flows |
| `@raw-http` | Tests using raw HTTP (bypassing MCP SDK) |
| `@authorization` | Per-user access control |
| `@pending` | Known failures, skipped in CI |
| `@pending-mcp-sdk-behavior` | MCP SDK hides 401 errors via silent reconnect |

## Custom World Class

The World class holds shared state across steps within a single scenario. It provides helper methods for connection management, tool calls, and response parsing.

### Key Properties

```typescript
interface GatewayWorld {
  // Connection
  gatewayUrl: string
  keycloakTokenUrl: string
  client?: Client
  transport?: StreamableHTTPClientTransport
  jwtToken?: string

  // Responses
  lastResponse?: unknown
  lastError?: Error
  storedResponses: Record<string, unknown>
  storedToolsArray: Tool[]
  storedToolCount: number

  // Raw HTTP
  httpStatus?: number
  httpResponseBody?: unknown
  httpResponseHeaders?: Headers

  // Multi-session (for future use)
  sessions: Record<string, { client: Client; transport: StreamableHTTPClientTransport; jwtToken?: string }>
}
```

### Key Methods

```typescript
// Obtain a JWT token from Keycloak using Resource Owner Password Grant
async obtainToken(username: string, password: string): Promise<string>

// Connect to the gateway with a Bearer token
async connectToGateway(jwtToken?: string): Promise<void>

// MCP operations
async listTools(): Promise<Tool[]>
async callTool(name: string, args: Record<string, unknown>): Promise<unknown>

// Response parsing (MCP responses wrap JSON in content[0].text)
parseResponseContent<T>(): T

// Raw HTTP (bypass MCP SDK for auth testing)
async sendRawRequest(body: string, headers?: Record<string, string>): Promise<void>

// Cleanup
async cleanup(): Promise<void>
```

### Token Acquisition

The World class obtains tokens from Keycloak at test startup using the Resource Owner Password Credentials grant (direct access). This avoids browser-based PKCE flow in tests:

```typescript
async obtainToken(username: string, password: string): Promise<string> {
  const resp = await fetch(this.keycloakTokenUrl, {
    method: 'POST',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    body: new URLSearchParams({
      grant_type: 'password',
      client_id: 'adk-web-client',
      username,
      password,
      scope: 'openid',
    }),
  })
  const data = await resp.json()
  return data.access_token
}
```

**Important Keycloak prerequisite:** The `adk-web-client` must have `directAccessGrantsEnabled: true` in the realm config for BDD tests to obtain tokens without a browser. This should be enabled only for the test realm.

### MCP Connection Pattern

```typescript
async connectToGateway(jwtToken?: string): Promise<void> {
  const token = jwtToken || this.jwtToken
  const url = new URL(this.gatewayUrl)

  this.transport = new StreamableHTTPClientTransport(url, {
    requestInit: {
      headers: { 'Authorization': `Bearer ${token}` }
    }
  })

  this.client = new Client({ name: 'bdd-test', version: '1.0.0' })
  await this.client.connect(this.transport)
}
```

### Response Parsing Pattern

MCP tool responses wrap JSON inside `content[0].text`. Every assertion that inspects response data must parse this:

```typescript
parseResponseContent<T>(): T {
  const response = this.lastResponse as { content: Array<{ type: string; text: string }> }
  return JSON.parse(response.content[0].text) as T
}
```

### Test Isolation: Before Hook + `_reset_gateway`

The gateway is a stateful process -- `enabled_servers` and dynamically registered tools persist across MCP client connections. Without cleanup, a scenario that enables the weather server would leave those tools registered for the next scenario, causing incorrect tool counts.

Solution: a `Before` hook calls the gateway's `_reset_gateway` tool before each scenario:

```typescript
Before(async function (this: GatewayWorld) {
  const token = await this.obtainToken(username, password);
  const url = new URL(this.gatewayUrl);
  const transport = new StreamableHTTPClientTransport(url, {
    requestInit: { headers: { 'Authorization': `Bearer ${token}` } },
  });
  const client = new Client({ name: 'bdd-reset', version: '1.0.0' });
  try {
    await client.connect(transport);
    await client.callTool({ name: '_reset_gateway', arguments: {} });
    await client.close();
  } catch {
    // Gateway might not be running yet for some scenarios
  }
});
```

This creates a separate MCP connection (independent from the scenario's connection) to reset state. The `_reset_gateway` tool uses `mcp._tool_manager.remove_tool()` to unregister all dynamic tools and clears `enabled_servers`.

**Important:** The gateway exposes 3 built-in tools (not 2): `search_servers`, `enable_server`, and `_reset_gateway`. All tool count assertions in feature files account for this.

### MCP SDK Union Return Type

The `@modelcontextprotocol/sdk` v1.26 `callTool()` returns a union type: `CallToolResult | CompatibilityCallToolResult`. The `CompatibilityCallToolResult` variant has a `toolResult` property instead of `content`. To avoid type assertion complexity, the World class defines a custom `ToolCallResponse` interface:

```typescript
export interface ToolCallResponse {
  content: Array<{ type: string; text: string; [key: string]: unknown }>;
  isError?: boolean;
  [key: string]: unknown;
}
```

Tool call results are cast to this interface via `as ToolCallResponse`.

---

## Feature Files

### 1. discover_servers.feature

```gherkin
@tools
Feature: Discover Available Servers
  As an MCP client
  I want to discover available MCP servers
  So that I can see what servers exist in the gateway

  Downstream servers (from servers.yaml):
  - weather: Weather information service (port 8011)
  - calculator: Mathematical calculator service (port 8012)

  Background:
    Given the MCP gateway is running
    And I am connected with a valid JWT token

  @smoke
  Scenario: Successfully discover all available servers
    When I call the search_servers tool
    Then the response should conform to CallToolResultSchema
    And I should receive a list of 2 servers
    And each server should have a name and description

  Scenario: Discover servers returns weather server details
    When I call the search_servers tool
    Then the response should contain server "weather"
    And server "weather" should have description "Weather information service"

  Scenario: Discover servers returns calculator server details
    When I call the search_servers tool
    Then the response should contain server "calculator"
    And server "calculator" should have description "Mathematical calculator service"

  Scenario: Search servers with query filters results
    When I call the search_servers tool with query "weather"
    Then I should receive a list of 1 servers
    And the response should contain server "weather"

  Scenario: Search servers with empty query returns all servers
    When I call the search_servers tool with query ""
    Then I should receive a list of 2 servers

  Scenario: Search servers with non-matching query returns empty
    When I call the search_servers tool with query "nonexistent"
    Then I should receive a list of 0 servers

  Scenario: Discover servers shows enabled status
    When I call the enable_server tool with name "weather"
    And I call the search_servers tool
    Then server "weather" should show enabled as true
    And server "calculator" should show enabled as false
```

### 2. activate_server.feature

```gherkin
@activation
Feature: Activate Downstream MCP Server
  As a user of the MCP gateway
  I want to activate downstream MCP servers
  So that I can use their tools through the gateway

  Server activation connects to a real downstream FastMCP server,
  discovers its tools via MCP tools/list, and registers them
  as proxy tools on the gateway.

  Background:
    Given the MCP gateway is running
    And I am connected with a valid JWT token

  Rule: Successful server activation

    @smoke
    Scenario: Activate weather server returns success with tool names
      When I call the enable_server tool with name "weather"
      Then the response should conform to CallToolResultSchema
      And I should receive a success response
      And the response should include tools array
      And the tools array should contain "get_weather"
      And the tools array should contain "get_forecast"

    Scenario: Activate calculator server returns success
      When I call the enable_server tool with name "calculator"
      Then the response should conform to CallToolResultSchema
      And I should receive a success response
      And the tools array should contain "calculate"

    Scenario: Activate multiple servers sequentially
      When I call the enable_server tool with name "weather"
      Then I should receive a success response
      When I call the enable_server tool with name "calculator"
      Then I should receive a success response

    Scenario: Activated server tools are immediately usable
      When I call the enable_server tool with name "weather"
      And I call the tool "get_weather" with arguments {"location": "Paris"}
      Then the response should conform to CallToolResultSchema
      And the response content should contain "Paris"

  Rule: Invalid activation requests

    Scenario: Activate non-existent server returns error
      When I call the enable_server tool with name "nonexistent"
      Then the response should conform to CallToolResultSchema
      And I should receive an error response
      And the error message should contain "not found"

  Rule: Re-activation is idempotent

    Scenario: Re-activating same server succeeds
      When I call the enable_server tool with name "weather"
      And I store the response as "first_activation"
      And I call the enable_server tool with name "weather" again
      Then both responses should indicate success

    Scenario: Re-activation returns same tools
      When I call the enable_server tool with name "weather"
      And I store the tools array
      And I call the enable_server tool with name "weather" again
      Then the tools array should match the stored tools

  Rule: Activation performs token exchange

    Scenario: Activation fails when token exchange is rejected
      Given I am connected with an invalid JWT token
      When I call the enable_server tool with name "weather"
      Then I should receive an error response
```

### 3. aggregated_tools.feature

```gherkin
@tools @aggregated
Feature: Aggregated Tools List
  As an MCP client
  I want to see all available tools including those from activated servers
  So that I can discover what capabilities are available

  Background:
    Given the MCP gateway is running
    And I am connected with a valid JWT token

  Rule: Gateway tools always present

    @smoke
    Scenario: Tools list includes gateway tools before activation
      When I list all available tools
      Then the response should conform to ListToolsResultSchema
      And I should see the "search_servers" tool
      And I should see the "enable_server" tool
      And I should see exactly 3 tools

  Rule: Activated server tools appear in tools list

    Scenario: Activated weather server tools appear in tools list
      When I call the enable_server tool with name "weather"
      And I list all available tools
      Then the response should conform to ListToolsResultSchema
      And I should see the "get_weather" tool
      And I should see the "get_forecast" tool
      And the total tool count should be greater than 2

    Scenario: Each tool has required MCP schema properties
      When I call the enable_server tool with name "weather"
      And I list all available tools
      Then the response should conform to ListToolsResultSchema
      And each tool should have a name property
      And each tool should have an inputSchema property

    Scenario: Multiple server activations aggregate all tools
      When I call the enable_server tool with name "weather"
      And I call the enable_server tool with name "calculator"
      And I list all available tools
      Then the response should conform to ListToolsResultSchema
      And I should see the "get_weather" tool
      And I should see the "get_forecast" tool
      And I should see the "calculate" tool
      And I should see the "search_servers" tool
      And I should see the "enable_server" tool
      And I should see exactly 6 tools

    Scenario: Re-activation does not duplicate tools in list
      When I call the enable_server tool with name "weather"
      And I list all available tools
      And I store the tool count
      And I call the enable_server tool with name "weather" again
      And I list all available tools
      Then the tool count should remain the same

  Rule: Tools list updates reflect current state

    Scenario: Tools list grows with each server activation
      When I list all available tools
      Then I should see exactly 3 tools
      When I call the enable_server tool with name "weather"
      And I list all available tools
      Then I should see exactly 5 tools
      When I call the enable_server tool with name "calculator"
      And I list all available tools
      Then I should see exactly 6 tools
```

### 4. tool_forwarding.feature

```gherkin
@tool-forwarding
Feature: Tool Call Forwarding to Downstream Servers
  As an MCP client
  I want to call tools on activated downstream servers
  So that I can use their capabilities through the gateway

  Tool calls are proxied: the gateway exchanges the user's token
  for a server-scoped token, then forwards the MCP call to
  the real downstream server.

  Background:
    Given the MCP gateway is running
    And I am connected with a valid JWT token

  Rule: Activated tools route to downstream servers

    @smoke
    Scenario: Call get_weather returns weather data
      Given I have activated server "weather"
      When I call the tool "get_weather" with arguments {"location": "London"}
      Then the response should conform to CallToolResultSchema
      And the response content should contain "London"
      And the response content should contain "temperature"

    Scenario: Call get_forecast returns forecast data
      Given I have activated server "weather"
      When I call the tool "get_forecast" with arguments {"location": "Tokyo", "days": 3}
      Then the response should conform to CallToolResultSchema
      And the response content should contain "Tokyo"
      And the response content should contain "forecast"

    Scenario: Call calculate returns calculation result
      Given I have activated server "calculator"
      When I call the tool "calculate" with arguments {"expression": "2 + 2"}
      Then the response should conform to CallToolResultSchema
      And the response content should contain "2 + 2"

    Scenario: Call tools on different activated servers
      Given I have activated server "weather"
      And I have activated server "calculator"
      When I call the tool "get_weather" with arguments {"location": "Berlin"}
      And I call the tool "calculate" with arguments {"expression": "10 * 5"}
      Then both responses should conform to CallToolResultSchema

    Scenario: Sequential tool calls on same server succeed
      Given I have activated server "weather"
      When I call the tool "get_weather" with arguments {"location": "Paris"}
      And I call the tool "get_weather" with arguments {"location": "Rome"}
      And I call the tool "get_weather" with arguments {"location": "Madrid"}
      Then all three responses should succeed

  Rule: Errors are propagated correctly

    Scenario: Call tool on non-activated server returns error
      When I call the tool "get_weather" with arguments {"location": "Paris"}
      Then the response should indicate an error

  Rule: Gateway tools are not forwarded

    Scenario: search_servers handled by gateway after activation
      Given I have activated server "weather"
      When I call the search_servers tool
      Then the response should conform to CallToolResultSchema
      And I should receive a list of servers

    Scenario: enable_server handled by gateway
      When I call the enable_server tool with name "weather"
      Then the response should conform to CallToolResultSchema
      And I should receive a success response
```

### 5. security.feature

```gherkin
@security
Feature: Security and JWT Validation
  As a security-conscious API consumer
  I want proper JWT validation on all MCP requests
  So that unauthenticated or unauthorized users are rejected

  NOTE: Tests marked @pending-mcp-sdk-behavior require raw HTTP testing
  because the MCP SDK client reconnects silently when auth fails,
  hiding the 401 error from test assertions.

  Rule: JWT tokens are required and validated

    @jwt @pending-mcp-sdk-behavior
    Scenario: Request without Authorization header is rejected
      When I call the search_servers tool without JWT header
      Then I should receive 401 Unauthorized response

    @jwt @raw-http @smoke
    Scenario: Raw HTTP - Missing Authorization header returns 401
      When I send a raw JSON-RPC request without Authorization header:
        """
        {"jsonrpc": "2.0", "method": "initialize", "params": {"protocolVersion": "2024-11-05", "capabilities": {}, "clientInfo": {"name": "test", "version": "1.0.0"}}, "id": 1}
        """
      Then I should receive HTTP status 401

    @jwt @raw-http
    Scenario: Raw HTTP - Malformed JWT returns 401
      When I send a raw JSON-RPC request with malformed Authorization "not.valid.jwt":
        """
        {"jsonrpc": "2.0", "method": "initialize", "params": {"protocolVersion": "2024-11-05", "capabilities": {}, "clientInfo": {"name": "test", "version": "1.0.0"}}, "id": 1}
        """
      Then I should receive HTTP status 401

    @jwt @raw-http
    Scenario: Raw HTTP - Tampered JWT signature returns 401
      When I send a raw JSON-RPC request with tampered JWT signature:
        """
        {"jsonrpc": "2.0", "method": "initialize", "params": {"protocolVersion": "2024-11-05", "capabilities": {}, "clientInfo": {"name": "test", "version": "1.0.0"}}, "id": 1}
        """
      Then I should receive HTTP status 401

    @jwt @raw-http
    Scenario: Raw HTTP - Expired JWT returns 401
      When I send a raw JSON-RPC request with expired JWT:
        """
        {"jsonrpc": "2.0", "method": "initialize", "params": {"protocolVersion": "2024-11-05", "capabilities": {}, "clientInfo": {"name": "test", "version": "1.0.0"}}, "id": 1}
        """
      Then I should receive HTTP status 401

    @jwt @raw-http
    Scenario: Raw HTTP - JWT with wrong audience returns 401
      When I send a raw JSON-RPC request with wrong-audience JWT:
        """
        {"jsonrpc": "2.0", "method": "initialize", "params": {"protocolVersion": "2024-11-05", "capabilities": {}, "clientInfo": {"name": "test", "version": "1.0.0"}}, "id": 1}
        """
      Then I should receive HTTP status 401

  Rule: Valid JWT grants access

    @jwt @smoke
    Scenario: Valid JWT token allows MCP operations
      Given I am connected with a valid JWT token
      When I call the search_servers tool
      Then the response should conform to CallToolResultSchema
      And I should receive a list of servers
```

### 6. token_exchange.feature

```gherkin
@token-exchange @security
Feature: Token Exchange for Downstream Server Access
  As an MCP gateway
  I want to exchange user tokens for server-scoped tokens
  So that downstream servers receive minimum-privilege credentials

  Token exchange (RFC 8693) happens internally during server activation
  and on every proxied tool call. These tests verify observable behavior
  rather than internal implementation.

  Background:
    Given the MCP gateway is running
    And I am connected with a valid JWT token

  Rule: Server activation performs token exchange transparently

    @smoke
    Scenario: Activation succeeds with valid JWT (token exchange happens internally)
      When I call the enable_server tool with name "weather"
      Then the response should conform to CallToolResultSchema
      And I should receive a success response
      And the response should include tools array with count greater than 0

    Scenario: Activated server tools are callable (proves token exchange worked)
      When I call the enable_server tool with name "weather"
      And I call the tool "get_weather" with arguments {"location": "Oslo"}
      Then the response should conform to CallToolResultSchema
      And the response content should contain "Oslo"

    Scenario: Multiple tool calls on activated server succeed (proves repeated exchange)
      When I call the enable_server tool with name "weather"
      And I call the tool "get_weather" with arguments {"location": "Stockholm"}
      And I call the tool "get_forecast" with arguments {"location": "Helsinki", "days": 5}
      Then both tool calls should succeed

  Rule: Token exchange targets correct audience per server

    Scenario: Weather server receives token with weather audience
      When I call the enable_server tool with name "weather"
      And I call the tool "get_weather" with arguments {"location": "test"}
      Then the response should conform to CallToolResultSchema
      And the response content should contain "requested_by"

    Scenario: Calculator server receives token with calculator audience
      When I call the enable_server tool with name "calculator"
      And I call the tool "calculate" with arguments {"expression": "1+1"}
      Then the response should conform to CallToolResultSchema
      And the response content should contain "requested_by"

    Scenario: Tools on different servers use different exchanged tokens
      When I call the enable_server tool with name "weather"
      And I call the enable_server tool with name "calculator"
      And I call the tool "get_weather" with arguments {"location": "test"}
      And I call the tool "calculate" with arguments {"expression": "test"}
      Then both tool calls should succeed
      And both responses should contain "requested_by"

  Rule: Re-activation does not break token exchange

    Scenario: Re-activating server preserves tool call capability
      When I call the enable_server tool with name "weather"
      And I call the enable_server tool with name "weather" again
      And I call the tool "get_weather" with arguments {"location": "test"}
      Then the response should conform to CallToolResultSchema
      And the response content should contain "test"

  Rule: User identity propagates through token exchange

    Scenario: Downstream server sees the original user identity
      When I call the enable_server tool with name "weather"
      And I call the tool "get_weather" with arguments {"location": "identity-test"}
      Then the response content should contain "requested_by"
      And the requested_by field should be "testuser"
```

### 7. end_to_end.feature

```gherkin
@e2e
Feature: End-to-End Flow
  As a user of the MCP gateway system
  I want the complete flow from authentication through tool execution to work
  So that the system delivers value as an integrated whole

  Background:
    Given Keycloak is running on port 8080
    And the MCP gateway is running on port 8010
    And the weather server is running on port 8011
    And the calculator server is running on port 8012

  @smoke
  Scenario: Full discovery-activation-usage flow
    Given I obtain a JWT token from Keycloak as "testuser"
    And I connect to the MCP gateway with the token
    When I list all available tools
    Then I should see exactly 3 tools
    When I call the search_servers tool
    Then I should receive a list of 2 servers
    When I call the enable_server tool with name "weather"
    Then I should receive a success response
    When I list all available tools
    Then I should see the "get_weather" tool
    And I should see the "get_forecast" tool
    When I call the tool "get_weather" with arguments {"location": "Warsaw"}
    Then the response content should contain "Warsaw"
    And the response content should contain "temperature"

  Scenario: Activate all servers and use all tools
    Given I obtain a JWT token from Keycloak as "testuser"
    And I connect to the MCP gateway with the token
    When I call the enable_server tool with name "weather"
    And I call the enable_server tool with name "calculator"
    And I list all available tools
    Then I should see exactly 6 tools
    When I call the tool "get_weather" with arguments {"location": "NYC"}
    Then the response content should contain "NYC"
    When I call the tool "calculate" with arguments {"expression": "42 * 2"}
    Then the response content should contain "42 * 2"
    When I call the tool "get_forecast" with arguments {"location": "LA", "days": 7}
    Then the response content should contain "LA"
```

### 8. authorization.feature

```gherkin
@authorization
Feature: Per-User Token Exchange Authorization
  As a security-conscious system
  I want to restrict which users can access which MCP servers
  So that users only get access to servers they are authorized for

  Keycloak V1 fine-grained permissions enforce per-user access control
  during token exchange. Role-based policies determine which users
  can exchange tokens for which server audiences.

  Test users:
  - testuser: has access:weather + access:calculator roles
  - limiteduser: has access:weather role only

  Rule: Full-access user can access all servers

    Scenario: testuser can activate weather server
      Given I am connected as "testuser"
      When I call the enable_server tool with name "weather"
      Then I should receive a success response

    Scenario: testuser can activate calculator server
      Given I am connected as "testuser"
      When I call the enable_server tool with name "calculator"
      Then I should receive a success response

    Scenario: testuser can use tools on both servers
      Given I am connected as "testuser"
      And I have activated server "weather"
      And I have activated server "calculator"
      When I call the tool "get_weather" with arguments {"location": "Berlin"}
      Then the response content should contain "Berlin"
      When I call the tool "calculate" with arguments {"expression": "1+1"}
      Then the response content should contain "1+1"

  Rule: Limited user can only access authorized servers

    @smoke
    Scenario: limiteduser can activate weather server
      Given I am connected as "limiteduser"
      When I call the enable_server tool with name "weather"
      Then I should receive a success response

    Scenario: limiteduser cannot activate calculator server
      Given I am connected as "limiteduser"
      When I call the enable_server tool with name "calculator"
      Then I should receive an error response
      And the error message should contain "denied"

    Scenario: limiteduser can use weather tools after activation
      Given I am connected as "limiteduser"
      And I have activated server "weather"
      When I call the tool "get_weather" with arguments {"location": "Oslo"}
      Then the response content should contain "Oslo"

    Scenario: limiteduser identity propagates through weather tools
      Given I am connected as "limiteduser"
      And I have activated server "weather"
      When I call the tool "get_weather" with arguments {"location": "test"}
      Then the requested_by field should be "limiteduser"
```

## Step Definitions

### Structure

All steps are in a single file `steps/gateway.steps.ts`, organized by step type:

```
GIVEN steps (~200 lines)  -- Setup: connections, tokens, pre-conditions
WHEN steps  (~300 lines)  -- Actions: tool calls, raw HTTP requests
THEN steps  (~400 lines)  -- Assertions: response validation
```

### GIVEN Steps

```typescript
// Connection & auth
Given('the MCP gateway is running', async function(this: GatewayWorld) { ... })
Given('I am connected with a valid JWT token', async function(this: GatewayWorld) { ... })
Given('I am connected with an invalid JWT token', async function(this: GatewayWorld) { ... })
Given('I am connected as {string}', async function(this: GatewayWorld, username: string) { ... })
Given('I obtain a JWT token from Keycloak as {string}', async function(this: GatewayWorld, username: string) { ... })
Given('I connect to the MCP gateway with the token', async function(this: GatewayWorld) { ... })

// Pre-conditions
Given('I have activated server {string}', async function(this: GatewayWorld, serverName: string) { ... })

// Infrastructure checks
Given('Keycloak is running on port {int}', async function(this: GatewayWorld, port: number) { ... })
Given('the MCP gateway is running on port {int}', async function(this: GatewayWorld, port: number) { ... })
Given('the weather server is running on port {int}', async function(this: GatewayWorld, port: number) { ... })
Given('the calculator server is running on port {int}', async function(this: GatewayWorld, port: number) { ... })
```

### WHEN Steps

```typescript
// Tool calls
When('I call the search_servers tool', async function(this: GatewayWorld) { ... })
When('I call the search_servers tool with query {string}', async function(this: GatewayWorld, query: string) { ... })
When('I call the enable_server tool with name {string}', async function(this: GatewayWorld, name: string) { ... })
When('I call the enable_server tool with name {string} again', async function(this: GatewayWorld, name: string) { ... })
When(/^I call the tool "([^"]*)" with arguments ({.*})$/, async function(this: GatewayWorld, toolName: string, argsJson: string) { ... })

// List operations
When('I list all available tools', async function(this: GatewayWorld) { ... })
When('I store the response as {string}', async function(this: GatewayWorld, key: string) { ... })
When('I store the tools array', async function(this: GatewayWorld) { ... })
When('I store the tool count', async function(this: GatewayWorld) { ... })

// Raw HTTP (bypassing MCP SDK for auth tests)
When('I send a raw JSON-RPC request without Authorization header:', async function(this: GatewayWorld, body: string) { ... })
When('I send a raw JSON-RPC request with malformed Authorization {string}:', async function(this: GatewayWorld, malformed: string, body: string) { ... })
When('I send a raw JSON-RPC request with tampered JWT signature:', async function(this: GatewayWorld, body: string) { ... })
When('I send a raw JSON-RPC request with expired JWT:', async function(this: GatewayWorld, body: string) { ... })
When('I send a raw JSON-RPC request with wrong-audience JWT:', async function(this: GatewayWorld, body: string) { ... })

// Auth edge cases
When('I call the search_servers tool without JWT header', async function(this: GatewayWorld) { ... })
```

### THEN Steps

```typescript
// Schema validation
Then('the response should conform to CallToolResultSchema', async function(this: GatewayWorld) { ... })
Then('the response should conform to ListToolsResultSchema', async function(this: GatewayWorld) { ... })

// Success/error
Then('I should receive a success response', async function(this: GatewayWorld) { ... })
Then('I should receive an error response', async function(this: GatewayWorld) { ... })
Then('the error message should contain {string}', async function(this: GatewayWorld, text: string) { ... })
Then('the response should indicate an error', async function(this: GatewayWorld) { ... })

// Server discovery
Then('I should receive a list of {int} servers', async function(this: GatewayWorld, count: number) { ... })
Then('I should receive a list of servers', async function(this: GatewayWorld) { ... })
Then('each server should have a name and description', async function(this: GatewayWorld) { ... })
Then('the response should contain server {string}', async function(this: GatewayWorld, name: string) { ... })
Then('server {string} should have description {string}', async function(this: GatewayWorld, name: string, desc: string) { ... })
Then('server {string} should show enabled as true', async function(this: GatewayWorld, name: string) { ... })
Then('server {string} should show enabled as false', async function(this: GatewayWorld, name: string) { ... })

// Tools list
Then('I should see the {string} tool', async function(this: GatewayWorld, name: string) { ... })
Then('I should see exactly {int} tools', async function(this: GatewayWorld, count: number) { ... })
Then('the total tool count should be greater than {int}', async function(this: GatewayWorld, count: number) { ... })
Then('each tool should have a name property', async function(this: GatewayWorld) { ... })
Then('each tool should have an inputSchema property', async function(this: GatewayWorld) { ... })
Then('the tool count should remain the same', async function(this: GatewayWorld) { ... })

// Activation
Then('the response should include tools array', async function(this: GatewayWorld) { ... })
Then('the tools array should contain {string}', async function(this: GatewayWorld, tool: string) { ... })
Then('the response should include tools array with count greater than {int}', async function(this: GatewayWorld, n: number) { ... })
Then('the tools array should match the stored tools', async function(this: GatewayWorld) { ... })
Then('both responses should indicate success', async function(this: GatewayWorld) { ... })

// Content assertions
Then('the response content should contain {string}', async function(this: GatewayWorld, text: string) { ... })
Then('both responses should conform to CallToolResultSchema', async function(this: GatewayWorld) { ... })
Then('both tool calls should succeed', async function(this: GatewayWorld) { ... })
Then('both responses should contain {string}', async function(this: GatewayWorld, text: string) { ... })
Then('all three responses should succeed', async function(this: GatewayWorld) { ... })
Then('the requested_by field should be {string}', async function(this: GatewayWorld, username: string) { ... })

// Raw HTTP
Then('I should receive HTTP status {int}', async function(this: GatewayWorld, status: number) { ... })
Then('I should receive 401 Unauthorized response', async function(this: GatewayWorld) { ... })
```

## Implementation Patterns

### Pattern 1: Tool Call + Response Parse

The most common pattern. Call a tool, then parse the JSON wrapped in `content[0].text`:

```typescript
When('I call the search_servers tool', async function(this: GatewayWorld) {
  this.lastResponse = await this.client!.request(
    { method: 'tools/call', params: { name: 'search_servers', arguments: { query: '' } } },
    CallToolResultSchema
  )
})

Then('I should receive a list of {int} servers', async function(this: GatewayWorld, count: number) {
  const parsed = this.parseResponseContent<{ servers: unknown[]; total: number }>()
  assert.strictEqual(parsed.total, count)
})
```

### Pattern 2: Raw HTTP for Auth Tests

The MCP SDK client silently reconnects when it receives a 401, hiding auth failures from tests. Raw HTTP requests test auth at the transport level:

```typescript
When('I send a raw JSON-RPC request without Authorization header:',
  async function(this: GatewayWorld, body: string) {
    const resp = await fetch(this.gatewayUrl, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'Accept': 'application/json, text/event-stream' },
      body,
    })
    this.httpStatus = resp.status
    this.httpResponseHeaders = resp.headers
    try { this.httpResponseBody = await resp.json() } catch { this.httpResponseBody = null }
  }
)
```

### Pattern 3: JWT Token Tampering

Generate invalid tokens for security tests:

```typescript
// Tampered signature
function tamperJwtSignature(token: string): string {
  const parts = token.split('.')
  return `${parts[0]}.${parts[1]}.${parts[2].slice(0, -1)}X`
}

// Wrong audience (re-sign with different aud -- requires crafting a custom JWT)
// For expired token -- obtain from Keycloak with very short lifespan, or pre-generate
```

### Pattern 4: Store and Compare

For idempotency tests -- store a result, repeat the action, compare:

```typescript
When('I store the tools array', async function(this: GatewayWorld) {
  const parsed = this.parseResponseContent<{ tools: string[] }>()
  this.storedToolsArray = parsed.tools
})

Then('the tools array should match the stored tools', async function(this: GatewayWorld) {
  const parsed = this.parseResponseContent<{ tools: string[] }>()
  assert.deepStrictEqual(parsed.tools.sort(), this.storedToolsArray.sort())
})
```

## Keycloak Realm Prerequisites

For BDD tests to work correctly, two realm configuration changes are required:

**1. Direct Access Grants on `adk-web-client`**

The `adk-web-client` client needs `directAccessGrantsEnabled: true` to allow the Resource Owner Password Credentials grant (`grant_type=password`), which the test World class uses to obtain tokens programmatically without a browser:

```json
{
  "clientId": "adk-web-client",
  "directAccessGrantsEnabled": true,
  ...
}
```

**2. Explicit `profile` client scope with `preferred_username` mapper**

Keycloak does not auto-create built-in scopes (like `profile`) with their protocol mappers during realm import. The `profile` scope must be explicitly defined in the realm JSON with an `oidc-usermodel-attribute-mapper` for `preferred_username`. Without this, MCP server responses will show `requested_by: "unknown"` instead of the actual username, causing the "Downstream server sees the original user identity" scenario to fail.

## Running the Tests

### Prerequisites

1. Keycloak running: `docker-compose up -d` (wait ~30s)
2. Weather server: `python servers/weather_server.py`
3. Calculator server: `python servers/calculator_server.py`
4. Gateway: `python gateway/server.py`

### Execute

```bash
cd tests/bdd
cp .env.example .env          # configure if needed
npm install
npm test                      # build + run all (excluding @pending)
npm run test:smoke            # smoke tests only
```

### Reports

Cucumber generates an HTML report at `tests/bdd/cucumber-report.html` after each run.

## Scenario Count Summary

| Feature | Scenarios | Smoke |
|---------|-----------|-------|
| discover_servers | 7 | 1 |
| activate_server | 8 | 1 |
| aggregated_tools | 6 | 1 |
| tool_forwarding | 8 | 1 |
| security | 7 | 2 |
| token_exchange | 9 | 1 |
| end_to_end | 2 | 1 |
| authorization | 7 | 1 |
| **Total** | **54** | **9** |

**Note:** The default Cucumber profile excludes 1 scenario tagged `@pending-mcp-sdk-behavior` (MCP SDK silently reconnects on 401, hiding auth failure) and 1 scenario tagged `@pending`. Effective runnable scenarios: **52**.
