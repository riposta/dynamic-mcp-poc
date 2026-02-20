"""Standalone Weather MCP Server with JWT auth via Keycloak"""
import os
from dotenv import load_dotenv
from fastmcp import FastMCP
from fastmcp.server.auth.providers.jwt import JWTVerifier
from fastmcp.server.dependencies import get_access_token

load_dotenv()

KEYCLOAK_URL = os.getenv("KEYCLOAK_URL", "http://localhost:8080")
KEYCLOAK_REALM = os.getenv("KEYCLOAK_REALM", "mcp-poc")

verifier = JWTVerifier(
    jwks_uri=f"{KEYCLOAK_URL}/realms/{KEYCLOAK_REALM}/protocol/openid-connect/certs",
    issuer=f"{KEYCLOAK_URL}/realms/{KEYCLOAK_REALM}",
    audience="mcp-weather",
    algorithm="RS256",
)

mcp = FastMCP("Weather Server", auth=verifier)


@mcp.tool()
def get_weather(location: str) -> dict:
    """Get current weather for a location"""
    token = get_access_token()
    user = token.claims.get("preferred_username", "unknown") if token else "anonymous"
    print(f"get_weather called by {user} for {location}")

    return {
        "location": location,
        "temperature": 22,
        "unit": "celsius",
        "condition": "Partly cloudy",
        "humidity": 65,
        "requested_by": user,
    }


@mcp.tool()
def get_forecast(location: str, days: int) -> dict:
    """Get weather forecast for a location"""
    token = get_access_token()
    user = token.claims.get("preferred_username", "unknown") if token else "anonymous"
    print(f"get_forecast called by {user} for {location}, {days} days")

    forecast = []
    for i in range(days):
        forecast.append({
            "day": i + 1,
            "temperature": 20 + i,
            "condition": ["Sunny", "Cloudy", "Rainy"][i % 3],
        })

    return {
        "location": location,
        "days": days,
        "forecast": forecast,
        "requested_by": user,
    }


if __name__ == "__main__":
    port = int(os.getenv("WEATHER_PORT", "8011"))
    print(f"Starting Weather MCP Server on http://localhost:{port}")
    mcp.run(transport="streamable-http", port=port)
