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
      And the error message should contain "Access denied"

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
