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
