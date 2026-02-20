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
