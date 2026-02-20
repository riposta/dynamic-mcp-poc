"""MCP Gateway Server with auth, token exchange, and dynamic tool discovery"""
import os
import yaml
import httpx
from dotenv import load_dotenv
from fastmcp import FastMCP, Client
from fastmcp.server.auth.providers.jwt import JWTVerifier
from fastmcp.server.dependencies import get_access_token
from fastmcp.server.context import Context

load_dotenv()

# Keycloak config
KEYCLOAK_URL = os.getenv("KEYCLOAK_URL", "http://localhost:8080")
KEYCLOAK_REALM = os.getenv("KEYCLOAK_REALM", "mcp-poc")
GATEWAY_CLIENT_ID = os.getenv("KEYCLOAK_GATEWAY_CLIENT_ID", "mcp-gateway")
GATEWAY_CLIENT_SECRET = os.getenv("KEYCLOAK_GATEWAY_CLIENT_SECRET", "mcp-gateway-secret")
TOKEN_ENDPOINT = f"{KEYCLOAK_URL}/realms/{KEYCLOAK_REALM}/protocol/openid-connect/token"

# Load server config from YAML
config_path = os.path.join(os.path.dirname(__file__), "servers.yaml")
with open(config_path) as f:
    config = yaml.safe_load(f)
AVAILABLE_SERVERS = config["servers"]

# State: per-session enabled servers {session_id: {server_name: [tool_names]}}
enabled_servers = {}
# Tools already registered globally on mcp (prevent double-registration across sessions)
_registered_tools = set()

# JWT verification for incoming user tokens
verifier = JWTVerifier(
    jwks_uri=f"{KEYCLOAK_URL}/realms/{KEYCLOAK_REALM}/protocol/openid-connect/certs",
    issuer=f"{KEYCLOAK_URL}/realms/{KEYCLOAK_REALM}",
    audience="mcp-gateway",
    algorithm="RS256",
)

mcp = FastMCP("MCP Gateway", auth=verifier)


def check_user_role(access_token, required_role: str) -> bool:
    """Check if user's JWT contains the required realm role"""
    claims = access_token.claims or {}
    realm_access = claims.get("realm_access", {})
    roles = realm_access.get("roles", [])
    return required_role in roles


async def exchange_token(user_token: str, target_audience: str) -> str:
    """Exchange user token for a server-specific token via RFC 8693"""
    async with httpx.AsyncClient() as http:
        resp = await http.post(TOKEN_ENDPOINT, data={
            "grant_type": "urn:ietf:params:oauth:grant-type:token-exchange",
            "client_id": GATEWAY_CLIENT_ID,
            "client_secret": GATEWAY_CLIENT_SECRET,
            "subject_token": user_token,
            "subject_token_type": "urn:ietf:params:oauth:token-type:access_token",
            "audience": target_audience,
        })
        if resp.status_code == 403:
            raise PermissionError(f"Token exchange denied for audience '{target_audience}'. User lacks required access role.")
        resp.raise_for_status()
        data = resp.json()
        print(f"Token exchanged for audience={target_audience}")
        return data["access_token"]


async def call_mcp_server(server_url: str, tool_name: str, arguments: dict, token: str):
    """Call a tool on a remote MCP server with the exchanged token"""
    async with Client(f"{server_url}/mcp", auth=token) as client:
        result = await client.call_tool(tool_name, arguments)
        if result.content:
            return result.content[0].text
        return str(result.data)


@mcp.tool()
def search_servers(query: str = "", ctx: Context = None) -> dict:
    """Search for available MCP servers"""
    session = enabled_servers.get(ctx.session_id, {}) if ctx else {}
    results = []
    for name, info in AVAILABLE_SERVERS.items():
        if query == "" or query.lower() in name.lower() or query.lower() in info["description"].lower():
            results.append({
                "name": name,
                "description": info["description"],
                "enabled": name in session,
            })
    return {"servers": results, "total": len(results)}


@mcp.tool()
async def enable_server(server_name: str, ctx: Context = None) -> dict:
    """Enable an MCP server and load its tools dynamically"""
    session_id = ctx.session_id if ctx else "global"

    if server_name not in AVAILABLE_SERVERS:
        return {
            "success": False,
            "message": f"Server '{server_name}' not found. Use search_servers to find available servers.",
        }

    session = enabled_servers.setdefault(session_id, {})
    if server_name in session:
        return {
            "success": True,
            "message": f"Server '{server_name}' is already enabled",
            "tools": session[server_name],
        }

    server_info = AVAILABLE_SERVERS[server_name]

    # Check user has required role before attempting exchange
    access_token = get_access_token()
    required_role = server_info.get("required_role")
    if required_role and not check_user_role(access_token, required_role):
        user = (access_token.claims or {}).get("preferred_username", "unknown")
        return {
            "success": False,
            "message": f"Access denied: user '{user}' lacks role '{required_role}' required for server '{server_name}'.",
        }

    # Exchange user token for server-specific token
    try:
        exchanged = await exchange_token(access_token.token, server_info["keycloak_audience"])
    except PermissionError as e:
        return {"success": False, "message": str(e)}

    # Connect to real server and discover its tools
    async with Client(f"{server_info['url']}/mcp", auth=exchanged) as client:
        tools = await client.list_tools()

    # Register each discovered tool globally (idempotent -- skip if already registered)
    tool_names = []
    for tool in tools:
        if tool.name not in _registered_tools:
            _register_dynamic_tool(server_name, tool.name, tool.description, tool.inputSchema)
            _registered_tools.add(tool.name)
        tool_names.append(tool.name)

    session[server_name] = tool_names

    return {
        "success": True,
        "message": f"Server '{server_name}' enabled successfully",
        "tools": tool_names,
    }


def _register_dynamic_tool(server_name: str, tool_name: str, description: str, input_schema: dict):
    """Register a proxy tool that forwards calls to the real MCP server via token exchange"""
    server_info = AVAILABLE_SERVERS[server_name]
    properties = input_schema.get("properties", {})
    required = input_schema.get("required", [])

    type_map = {"string": "str", "integer": "int", "number": "float", "boolean": "bool"}

    # Build typed parameter list
    param_list = []
    for pname, pinfo in properties.items():
        ptype = type_map.get(pinfo.get("type", "string"), "str")
        if pname in required:
            param_list.append(f"{pname}: {ptype}")
        else:
            param_list.append(f"{pname}: {ptype} = None")

    params_str = ", ".join(param_list)
    param_names = list(properties.keys())

    # Build the dynamic async function that proxies through token exchange
    required_role = server_info.get("required_role", "")
    func_code = f"""
async def {tool_name}({params_str}, ctx: _Context = None):
    '''{description}'''
    session_id = ctx.session_id if ctx else "global"
    session = _enabled_servers.get(session_id, {{}})
    if "{server_name}" not in session:
        return {{"error": "Server '{server_name}' is not enabled in this session. Call enable_server('{server_name}') first."}}
    arguments = {{{", ".join([f'"{p}": {p}' for p in param_names])}}}
    arguments = {{k: v for k, v in arguments.items() if v is not None}}
    token = _get_access_token()
    if "{required_role}" and not _check_user_role(token, "{required_role}"):
        return {{"error": "Access denied: user lacks role '{required_role}' required for this tool."}}
    try:
        exchanged = await _exchange_token(token.token, "{server_info['keycloak_audience']}")
    except PermissionError as e:
        return {{"error": str(e)}}
    return await _call_mcp_server("{server_info['url']}", "{tool_name}", arguments, exchanged)
"""

    namespace = {
        "_Context": Context,
        "_enabled_servers": enabled_servers,
        "_get_access_token": get_access_token,
        "_exchange_token": exchange_token,
        "_call_mcp_server": call_mcp_server,
        "_check_user_role": check_user_role,
    }
    exec(func_code, namespace)
    dynamic_func = namespace[tool_name]

    mcp.tool()(dynamic_func)
    print(f"Registered proxy tool: {tool_name} -> {server_name}")


@mcp.tool()
def _reset_gateway(ctx: Context = None) -> dict:
    """Reset gateway state -- removes all enabled servers and their tools (for testing)"""
    session_id = ctx.session_id if ctx else None
    if session_id and session_id in enabled_servers:
        del enabled_servers[session_id]
    else:
        enabled_servers.clear()
    return {"success": True, "message": "Gateway state reset"}


if __name__ == "__main__":
    port = int(os.getenv("MCP_PORT", "8010"))
    print(f"Starting MCP Gateway on http://localhost:{port}")
    print("Available tools: search_servers, enable_server, _reset_gateway")
    print("Use enable_server to dynamically load more tools")
    mcp.run(transport="streamable-http", port=port)
