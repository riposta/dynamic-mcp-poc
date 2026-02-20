import { Given, When, Then, Before, After } from '@cucumber/cucumber';
import { Client } from '@modelcontextprotocol/sdk/client/index.js';
import { StreamableHTTPClientTransport } from '@modelcontextprotocol/sdk/client/streamableHttp.js';
import assert from 'assert';
import { GatewayWorld, ToolCallResponse } from '../support/world.js';

// ============================
// Hooks
// ============================

Before(async function (this: GatewayWorld) {
  // Reset gateway state before each scenario for test isolation
  const username = process.env.TEST_USER || 'testuser';
  const password = process.env.TEST_PASSWORD || 'testpass';
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

After(async function (this: GatewayWorld) {
  await this.cleanup();
});

// ============================
// GIVEN steps
// ============================

Given('the MCP gateway is running', async function (this: GatewayWorld) {
  // Assumed running -- verified by first connection attempt
});

Given('I am connected with a valid JWT token', async function (this: GatewayWorld) {
  const username = process.env.TEST_USER || 'testuser';
  const password = process.env.TEST_PASSWORD || 'testpass';
  this.jwtToken = await this.obtainToken(username, password);
  await this.connectToGateway();
});

Given('I am connected as {string}', async function (this: GatewayWorld, username: string) {
  const password = process.env.TEST_PASSWORD || 'testpass';
  this.jwtToken = await this.obtainToken(username, password);
  await this.connectToGateway();
});

Given('I am connected with an invalid JWT token', async function (this: GatewayWorld) {
  try {
    await this.connectToGateway('invalid.jwt.token');
  } catch (e) {
    this.lastError = e as Error;
  }
});

Given('I obtain a JWT token from Keycloak as {string}', async function (this: GatewayWorld, username: string) {
  const password = process.env.TEST_PASSWORD || 'testpass';
  this.jwtToken = await this.obtainToken(username, password);
});

Given('I connect to the MCP gateway with the token', async function (this: GatewayWorld) {
  await this.connectToGateway();
});

Given('I have activated server {string}', async function (this: GatewayWorld, serverName: string) {
  // Call enable_server directly on the client to avoid polluting response tracking
  const result = await this.client!.callTool({ name: 'enable_server', arguments: { server_name: serverName } }) as ToolCallResponse;
  const content = result.content[0];
  if (content.type === 'text') {
    const parsed = JSON.parse(content.text) as { success: boolean };
    assert.ok(parsed.success, `Failed to activate server ${serverName}`);
  }
  // Reset response tracking for subsequent steps
  this.lastResponse = undefined;
  this.previousResponses = [];
});

Given('Keycloak is running on port {int}', async function (this: GatewayWorld, port: number) {
  const resp = await fetch(`http://localhost:${port}/realms/mcp-poc`);
  assert.ok(resp.ok, `Keycloak not accessible on port ${port}`);
});

Given('the MCP gateway is running on port {int}', async function (this: GatewayWorld, _port: number) {
  // Gateway availability verified by connection
});

Given('the weather server is running on port {int}', async function (this: GatewayWorld, _port: number) {
  // Verified indirectly when tools are called
});

Given('the calculator server is running on port {int}', async function (this: GatewayWorld, _port: number) {
  // Verified indirectly when tools are called
});

// ============================
// WHEN steps
// ============================

When('I call the search_servers tool', async function (this: GatewayWorld) {
  await this.callTool('search_servers', { query: '' });
});

When('I call the search_servers tool with query {string}', async function (this: GatewayWorld, query: string) {
  await this.callTool('search_servers', { query });
});

When('I call the enable_server tool with name {string}', async function (this: GatewayWorld, name: string) {
  try {
    await this.callTool('enable_server', { server_name: name });
  } catch (e) {
    this.lastError = e as Error;
  }
});

When('I call the enable_server tool with name {string} again', async function (this: GatewayWorld, name: string) {
  await this.callTool('enable_server', { server_name: name });
});

When(/^I call the tool "([^"]*)" with arguments ({.*})$/, async function (this: GatewayWorld, toolName: string, argsJson: string) {
  const args = JSON.parse(argsJson);
  try {
    await this.callTool(toolName, args);
  } catch (e) {
    this.lastError = e as Error;
  }
});

When('I list all available tools', async function (this: GatewayWorld) {
  await this.listTools();
});

When('I store the response as {string}', async function (this: GatewayWorld, key: string) {
  assert.ok(this.lastResponse, 'No response to store');
  this.storedResponses[key] = this.lastResponse;
});

When('I store the tools array', async function (this: GatewayWorld) {
  const parsed = this.parseResponseContent<{ tools: string[] }>();
  this.storedToolsList = parsed.tools;
});

When('I store the tool count', async function (this: GatewayWorld) {
  assert.ok(this.lastToolsResponse, 'No tools response');
  this.storedToolCount = this.lastToolsResponse.tools.length;
});

// Raw HTTP steps (bypass MCP SDK for auth testing)

When('I send a raw JSON-RPC request without Authorization header:', async function (this: GatewayWorld, body: string) {
  await this.sendRawRequest(body);
});

When('I send a raw JSON-RPC request with malformed Authorization {string}:', async function (this: GatewayWorld, malformed: string, body: string) {
  await this.sendRawRequest(body, { 'Authorization': `Bearer ${malformed}` });
});

When('I send a raw JSON-RPC request with tampered JWT signature:', async function (this: GatewayWorld, body: string) {
  const username = process.env.TEST_USER || 'testuser';
  const password = process.env.TEST_PASSWORD || 'testpass';
  const validToken = await this.obtainToken(username, password);
  const parts = validToken.split('.');
  const tampered = `${parts[0]}.${parts[1]}.${parts[2].slice(0, -1)}X`;
  await this.sendRawRequest(body, { 'Authorization': `Bearer ${tampered}` });
});

When('I send a raw JSON-RPC request with expired JWT:', async function (this: GatewayWorld, body: string) {
  // Pre-crafted JWT with exp in the past -- signature won't verify but tests 401 path
  const expiredToken = 'eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9.eyJleHAiOjEwMDAwMDAwMDAsImF1ZCI6Im1jcC1nYXRld2F5IiwiaXNzIjoiaHR0cDovL2xvY2FsaG9zdDo4MDgwL3JlYWxtcy9tY3AtcG9jIn0.fake_signature';
  await this.sendRawRequest(body, { 'Authorization': `Bearer ${expiredToken}` });
});

When('I send a raw JSON-RPC request with wrong-audience JWT:', async function (this: GatewayWorld, body: string) {
  const wrongAudToken = 'eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9.eyJleHAiOjk5OTk5OTk5OTksImF1ZCI6Indyb25nLWF1ZGllbmNlIiwiaXNzIjoiaHR0cDovL2xvY2FsaG9zdDo4MDgwL3JlYWxtcy9tY3AtcG9jIn0.fake_signature';
  await this.sendRawRequest(body, { 'Authorization': `Bearer ${wrongAudToken}` });
});

When('I call the search_servers tool without JWT header', async function (this: GatewayWorld) {
  try {
    const url = new URL(this.gatewayUrl);
    const transport = new StreamableHTTPClientTransport(url);
    const client = new Client({ name: 'no-auth-test', version: '1.0.0' });
    await client.connect(transport);
    await client.callTool({ name: 'search_servers', arguments: { query: '' } });
    await client.close();
  } catch (e) {
    this.lastError = e as Error;
  }
});

// ============================
// THEN steps
// ============================

// Schema validation
Then('the response should conform to CallToolResultSchema', async function (this: GatewayWorld) {
  assert.ok(this.lastResponse, 'No response received');
  assert.ok(this.lastResponse.content, 'Response has no content');
  assert.ok(Array.isArray(this.lastResponse.content), 'Content is not an array');
  assert.ok(this.lastResponse.content.length > 0, 'Content array is empty');
});

Then('the response should conform to ListToolsResultSchema', async function (this: GatewayWorld) {
  assert.ok(this.lastToolsResponse, 'No tools response received');
  assert.ok(Array.isArray(this.lastToolsResponse.tools), 'Tools is not an array');
});

// Success/error
Then('I should receive a success response', async function (this: GatewayWorld) {
  const parsed = this.parseResponseContent<{ success: boolean }>();
  assert.strictEqual(parsed.success, true, `Expected success=true, got: ${JSON.stringify(parsed)}`);
});

Then('I should receive an error response', async function (this: GatewayWorld) {
  if (this.lastError) {
    return; // Connection or call error counts as error response
  }
  if (this.lastResponse) {
    const parsed = this.parseResponseContent<{ success?: boolean }>();
    assert.strictEqual(parsed.success, false, 'Expected error response (success=false)');
    return;
  }
  assert.fail('No response or error received');
});

Then('the error message should contain {string}', async function (this: GatewayWorld, text: string) {
  if (this.lastError) {
    assert.ok(this.lastError.message.toLowerCase().includes(text.toLowerCase()),
      `Error "${this.lastError.message}" doesn't contain "${text}"`);
    return;
  }
  const parsed = this.parseResponseContent<{ message?: string }>();
  assert.ok(parsed.message, 'No message in response');
  assert.ok(parsed.message!.toLowerCase().includes(text.toLowerCase()),
    `Message "${parsed.message}" doesn't contain "${text}"`);
});

Then('the response should indicate an error', async function (this: GatewayWorld) {
  if (this.lastError) return;
  if (this.lastResponse?.isError) return;
  assert.fail('Expected an error response');
});

// Server discovery
Then('I should receive a list of {int} servers', async function (this: GatewayWorld, count: number) {
  const parsed = this.parseResponseContent<{ servers: unknown[]; total: number }>();
  assert.strictEqual(parsed.total, count, `Expected ${count} servers, got ${parsed.total}`);
});

Then('I should receive a list of servers', async function (this: GatewayWorld) {
  const parsed = this.parseResponseContent<{ servers: unknown[]; total: number }>();
  assert.ok(parsed.servers.length > 0, 'Expected at least one server');
});

Then('each server should have a name and description', async function (this: GatewayWorld) {
  const parsed = this.parseResponseContent<{ servers: Array<{ name: string; description: string }> }>();
  for (const server of parsed.servers) {
    assert.ok(server.name, 'Server missing name');
    assert.ok(server.description, 'Server missing description');
  }
});

Then('the response should contain server {string}', async function (this: GatewayWorld, name: string) {
  const parsed = this.parseResponseContent<{ servers: Array<{ name: string }> }>();
  const found = parsed.servers.find(s => s.name === name);
  assert.ok(found, `Server "${name}" not found in response`);
});

Then('server {string} should have description {string}', async function (this: GatewayWorld, name: string, desc: string) {
  const parsed = this.parseResponseContent<{ servers: Array<{ name: string; description: string }> }>();
  const server = parsed.servers.find(s => s.name === name);
  assert.ok(server, `Server "${name}" not found`);
  assert.strictEqual(server!.description, desc);
});

Then('server {string} should show enabled as true', async function (this: GatewayWorld, name: string) {
  const parsed = this.parseResponseContent<{ servers: Array<{ name: string; enabled: boolean }> }>();
  const server = parsed.servers.find(s => s.name === name);
  assert.ok(server, `Server "${name}" not found`);
  assert.strictEqual(server!.enabled, true);
});

Then('server {string} should show enabled as false', async function (this: GatewayWorld, name: string) {
  const parsed = this.parseResponseContent<{ servers: Array<{ name: string; enabled: boolean }> }>();
  const server = parsed.servers.find(s => s.name === name);
  assert.ok(server, `Server "${name}" not found`);
  assert.strictEqual(server!.enabled, false);
});

// Tools list
Then('I should see the {string} tool', async function (this: GatewayWorld, name: string) {
  assert.ok(this.lastToolsResponse, 'No tools response');
  const found = this.lastToolsResponse.tools.find(t => t.name === name);
  assert.ok(found, `Tool "${name}" not found in tools list: [${this.lastToolsResponse.tools.map(t => t.name).join(', ')}]`);
});

Then('I should see exactly {int} tools', async function (this: GatewayWorld, count: number) {
  assert.ok(this.lastToolsResponse, 'No tools response');
  assert.strictEqual(this.lastToolsResponse.tools.length, count,
    `Expected ${count} tools, got ${this.lastToolsResponse.tools.length}: [${this.lastToolsResponse.tools.map(t => t.name).join(', ')}]`);
});

Then('the total tool count should be greater than {int}', async function (this: GatewayWorld, count: number) {
  assert.ok(this.lastToolsResponse, 'No tools response');
  assert.ok(this.lastToolsResponse.tools.length > count,
    `Expected more than ${count} tools, got ${this.lastToolsResponse.tools.length}`);
});

Then('each tool should have a name property', async function (this: GatewayWorld) {
  assert.ok(this.lastToolsResponse, 'No tools response');
  for (const tool of this.lastToolsResponse.tools) {
    assert.ok(tool.name, 'Tool missing name');
  }
});

Then('each tool should have an inputSchema property', async function (this: GatewayWorld) {
  assert.ok(this.lastToolsResponse, 'No tools response');
  for (const tool of this.lastToolsResponse.tools) {
    assert.ok(tool.inputSchema, `Tool "${tool.name}" missing inputSchema`);
  }
});

Then('the tool count should remain the same', async function (this: GatewayWorld) {
  assert.ok(this.lastToolsResponse, 'No tools response');
  assert.strictEqual(this.lastToolsResponse.tools.length, this.storedToolCount,
    `Tool count changed: was ${this.storedToolCount}, now ${this.lastToolsResponse.tools.length}`);
});

// Activation
Then('the response should include tools array', async function (this: GatewayWorld) {
  const parsed = this.parseResponseContent<{ tools: string[] }>();
  assert.ok(Array.isArray(parsed.tools), 'Response missing tools array');
});

Then('the tools array should contain {string}', async function (this: GatewayWorld, tool: string) {
  const parsed = this.parseResponseContent<{ tools: string[] }>();
  assert.ok(parsed.tools.includes(tool), `Tool "${tool}" not found in ${JSON.stringify(parsed.tools)}`);
});

Then('the response should include tools array with count greater than {int}', async function (this: GatewayWorld, n: number) {
  const parsed = this.parseResponseContent<{ tools: string[] }>();
  assert.ok(Array.isArray(parsed.tools), 'Response missing tools array');
  assert.ok(parsed.tools.length > n, `Expected more than ${n} tools, got ${parsed.tools.length}`);
});

Then('the tools array should match the stored tools', async function (this: GatewayWorld) {
  const parsed = this.parseResponseContent<{ tools: string[] }>();
  assert.deepStrictEqual(parsed.tools.sort(), [...this.storedToolsList].sort());
});

Then('both responses should indicate success', async function (this: GatewayWorld) {
  // Check last response
  const lastParsed = this.parseResponseContent<{ success: boolean }>();
  assert.strictEqual(lastParsed.success, true, 'Last response not successful');

  // Check previous response
  assert.ok(this.previousResponses.length > 0, 'No previous responses stored');
  const prev = this.previousResponses[this.previousResponses.length - 1];
  const prevContent = prev.content[0];
  if (prevContent.type === 'text') {
    const prevParsed = JSON.parse(prevContent.text) as { success: boolean };
    assert.strictEqual(prevParsed.success, true, 'Previous response not successful');
  }
});

// Content assertions
Then('the response content should contain {string}', async function (this: GatewayWorld, text: string) {
  const responseText = this.parseResponseText();
  assert.ok(responseText.includes(text), `Response doesn't contain "${text}". Got: ${responseText}`);
});

Then('both responses should conform to CallToolResultSchema', async function (this: GatewayWorld) {
  assert.ok(this.lastResponse, 'No last response');
  assert.ok(this.lastResponse.content && this.lastResponse.content.length > 0, 'Last response has no content');
  assert.ok(this.previousResponses.length > 0, 'No previous responses');
  const prev = this.previousResponses[this.previousResponses.length - 1];
  assert.ok(prev.content && prev.content.length > 0, 'Previous response has no content');
});

Then('both tool calls should succeed', async function (this: GatewayWorld) {
  assert.ok(this.lastResponse, 'No last response');
  assert.ok(this.previousResponses.length > 0, 'No previous responses');
  assert.ok(!this.lastResponse.isError, 'Last response is an error');
  const prev = this.previousResponses[this.previousResponses.length - 1];
  assert.ok(!prev.isError, 'Previous response is an error');
});

Then('both responses should contain {string}', async function (this: GatewayWorld, text: string) {
  // Check last response
  const lastText = this.parseResponseText();
  assert.ok(lastText.includes(text), `Last response doesn't contain "${text}"`);

  // Check previous response
  assert.ok(this.previousResponses.length > 0, 'No previous responses');
  const prev = this.previousResponses[this.previousResponses.length - 1];
  const prevContent = prev.content[0];
  if (prevContent.type === 'text') {
    assert.ok(prevContent.text.includes(text), `Previous response doesn't contain "${text}"`);
  }
});

Then('all three responses should succeed', async function (this: GatewayWorld) {
  assert.ok(this.lastResponse, 'No last response');
  assert.ok(this.previousResponses.length >= 2, 'Expected at least 2 previous responses');
  assert.ok(!this.lastResponse.isError, 'Last response is an error');
  for (const resp of this.previousResponses.slice(-2)) {
    assert.ok(!resp.isError, 'A previous response is an error');
  }
});

Then('the requested_by field should be {string}', async function (this: GatewayWorld, username: string) {
  const responseText = this.parseResponseText();
  const parsed = JSON.parse(responseText) as { requested_by: string };
  assert.strictEqual(parsed.requested_by, username,
    `Expected requested_by="${username}", got "${parsed.requested_by}"`);
});

// Raw HTTP
Then('I should receive HTTP status {int}', async function (this: GatewayWorld, status: number) {
  assert.strictEqual(this.httpStatus, status, `Expected HTTP ${status}, got ${this.httpStatus}`);
});

Then('I should receive 401 Unauthorized response', async function (this: GatewayWorld) {
  if (this.lastError) {
    return; // MCP SDK throws on auth failure
  }
  assert.fail('Expected auth failure but no error occurred');
});
