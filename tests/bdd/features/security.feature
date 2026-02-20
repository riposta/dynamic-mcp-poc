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
