"""Standalone Calculator MCP Server with JWT auth via Keycloak"""
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
    audience="mcp-calculator",
    algorithm="RS256",
)

mcp = FastMCP("Calculator Server", auth=verifier)


@mcp.tool()
def calculate(expression: str) -> dict:
    """Perform mathematical calculations"""
    token = get_access_token()
    user = token.claims.get("preferred_username", "unknown") if token else "anonymous"
    print(f"calculate called by {user}: {expression}")

    # Simple simulated calculation for PoC
    return {
        "expression": expression,
        "result": f"Simulated result of: {expression}",
        "requested_by": user,
    }


if __name__ == "__main__":
    port = int(os.getenv("CALCULATOR_PORT", "8012"))
    print(f"Starting Calculator MCP Server on http://localhost:{port}")
    mcp.run(transport="streamable-http", port=port)
