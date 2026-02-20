import { World, setWorldConstructor } from '@cucumber/cucumber';
import { Client } from '@modelcontextprotocol/sdk/client/index.js';
import { StreamableHTTPClientTransport } from '@modelcontextprotocol/sdk/client/streamableHttp.js';
import type { Tool } from '@modelcontextprotocol/sdk/types.js';
import * as dotenv from 'dotenv';

dotenv.config();

// Simplified response type for our assertions (avoids complex SDK union types)
export interface ToolCallResponse {
  content: Array<{ type: string; text: string; [key: string]: unknown }>;
  isError?: boolean;
  [key: string]: unknown;
}

export class GatewayWorld extends World {
  // Connection
  gatewayUrl: string;
  keycloakTokenUrl: string;
  client?: Client;
  transport?: StreamableHTTPClientTransport;
  jwtToken?: string;

  // Responses
  lastResponse?: ToolCallResponse;
  lastToolsResponse?: { tools: Tool[] };
  lastError?: Error;
  storedResponses: Record<string, ToolCallResponse> = {};
  storedToolsList: string[] = [];
  storedToolCount: number = 0;
  previousResponses: ToolCallResponse[] = [];

  // Raw HTTP
  httpStatus?: number;
  httpResponseBody?: unknown;
  httpResponseHeaders?: Headers;

  constructor(options: any) {
    super(options);
    this.gatewayUrl = process.env.GATEWAY_URL || 'http://localhost:8010/mcp';
    this.keycloakTokenUrl = process.env.KEYCLOAK_TOKEN_URL || 'http://localhost:8080/realms/mcp-poc/protocol/openid-connect/token';
  }

  async obtainToken(username: string, password: string): Promise<string> {
    const clientId = process.env.KEYCLOAK_CLIENT_ID || 'adk-web-client';
    const resp = await fetch(this.keycloakTokenUrl, {
      method: 'POST',
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
      body: new URLSearchParams({
        grant_type: 'password',
        client_id: clientId,
        username,
        password,
        scope: 'openid',
      }),
    });
    if (!resp.ok) {
      throw new Error(`Failed to obtain token: ${resp.status} ${await resp.text()}`);
    }
    const data = await resp.json() as { access_token: string };
    return data.access_token;
  }

  async connectToGateway(token?: string): Promise<void> {
    const jwt = token || this.jwtToken;
    if (!jwt) throw new Error('No JWT token available');

    const url = new URL(this.gatewayUrl);
    this.transport = new StreamableHTTPClientTransport(url, {
      requestInit: {
        headers: { 'Authorization': `Bearer ${jwt}` },
      },
    });
    this.client = new Client({ name: 'bdd-test', version: '1.0.0' });
    await this.client.connect(this.transport);
  }

  async callTool(name: string, args: Record<string, unknown> = {}): Promise<ToolCallResponse> {
    if (!this.client) throw new Error('Not connected to gateway');
    const result = await this.client.callTool({ name, arguments: args }) as ToolCallResponse;
    if (this.lastResponse) {
      this.previousResponses.push(this.lastResponse);
    }
    this.lastResponse = result;
    return result;
  }

  async listTools(): Promise<{ tools: Tool[] }> {
    if (!this.client) throw new Error('Not connected to gateway');
    const result = await this.client.listTools();
    this.lastToolsResponse = result;
    return result;
  }

  parseResponseContent<T>(): T {
    if (!this.lastResponse) throw new Error('No response to parse');
    const content = this.lastResponse.content;
    if (!content || content.length === 0) throw new Error('Empty response content');
    const item = content[0];
    if (item.type !== 'text') throw new Error(`Expected text content, got ${item.type}`);
    return JSON.parse(item.text) as T;
  }

  parseResponseText(): string {
    if (!this.lastResponse) throw new Error('No response to parse');
    const content = this.lastResponse.content;
    if (!content || content.length === 0) throw new Error('Empty response content');
    const item = content[0];
    if (item.type !== 'text') throw new Error(`Expected text content, got ${item.type}`);
    return item.text;
  }

  async sendRawRequest(body: string, headers?: Record<string, string>): Promise<void> {
    const defaultHeaders: Record<string, string> = {
      'Content-Type': 'application/json',
      'Accept': 'application/json, text/event-stream',
    };
    const resp = await fetch(this.gatewayUrl, {
      method: 'POST',
      headers: { ...defaultHeaders, ...headers },
      body,
    });
    this.httpStatus = resp.status;
    this.httpResponseHeaders = resp.headers;
    try {
      this.httpResponseBody = await resp.json();
    } catch {
      this.httpResponseBody = null;
    }
  }

  async cleanup(): Promise<void> {
    try {
      if (this.client) {
        await this.client.close();
      }
    } catch {
      // ignore cleanup errors
    }
    this.client = undefined;
    this.transport = undefined;
  }
}

setWorldConstructor(GatewayWorld);
