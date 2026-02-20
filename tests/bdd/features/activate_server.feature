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
