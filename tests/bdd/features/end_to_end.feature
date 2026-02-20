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
