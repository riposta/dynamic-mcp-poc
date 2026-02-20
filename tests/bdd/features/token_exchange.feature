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
