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
