"""MCP Gateway Server with dynamic tool discovery"""
from fastmcp import FastMCP

# Global registry of enabled servers and their tools
enabled_servers = {}

# Simulated available MCP servers with their tools
AVAILABLE_SERVERS = {
    "weather": {
        "description": "Weather information service",
        "tools": [
            {
                "name": "get_weather",
                "description": "Get current weather for a location",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "location": {"type": "string", "description": "City name"}
                    },
                    "required": ["location"]
                }
            },
            {
                "name": "get_forecast",
                "description": "Get weather forecast for a location",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "location": {"type": "string", "description": "City name"},
                        "days": {"type": "integer", "description": "Number of days"}
                    },
                    "required": ["location", "days"]
                }
            }
        ]
    },
    "database": {
        "description": "Database query service",
        "tools": [
            {
                "name": "query_db",
                "description": "Execute a database query",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "SQL query"}
                    },
                    "required": ["query"]
                }
            },
            {
                "name": "list_tables",
                "description": "List all database tables",
                "parameters": {
                    "type": "object",
                    "properties": {}
                }
            }
        ]
    },
    "calculator": {
        "description": "Mathematical calculator service",
        "tools": [
            {
                "name": "calculate",
                "description": "Perform mathematical calculations",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "expression": {"type": "string", "description": "Math expression"}
                    },
                    "required": ["expression"]
                }
            }
        ]
    }
}

# Initialize FastMCP
mcp = FastMCP("MCP Gateway")


@mcp.tool()
def search_servers(query: str = "") -> dict:
    """Search for available MCP servers"""
    results = []
    for name, info in AVAILABLE_SERVERS.items():
        if query.lower() in name.lower() or query.lower() in info["description"].lower() or query == "":
            results.append({
                "name": name,
                "description": info["description"],
                "enabled": name in enabled_servers,
                "tool_count": len(info["tools"])
            })

    return {
        "servers": results,
        "total": len(results)
    }


@mcp.tool()
def enable_server(server_name: str) -> dict:
    """Enable an MCP server and load its tools dynamically"""
    if server_name not in AVAILABLE_SERVERS:
        return {
            "success": False,
            "message": f"Server '{server_name}' not found. Use search_servers to find available servers."
        }

    if server_name in enabled_servers:
        return {
            "success": True,
            "message": f"Server '{server_name}' is already enabled",
            "tools": enabled_servers[server_name]
        }

    # Simulate loading the server and its tools
    server_tools = AVAILABLE_SERVERS[server_name]["tools"]
    enabled_servers[server_name] = server_tools

    # Dynamically register the tools from the enabled server
    for tool_def in server_tools:
        _register_dynamic_tool(server_name, tool_def)

    return {
        "success": True,
        "message": f"Server '{server_name}' enabled successfully",
        "tools": [t["name"] for t in server_tools]
    }


def _register_dynamic_tool(server_name: str, tool_def: dict):
    """Register a tool from an enabled server"""
    tool_name = tool_def["name"]
    tool_description = tool_def["description"]
    params = tool_def.get("parameters", {})
    properties = params.get("properties", {})
    required = params.get("required", [])

    # Map JSON Schema types to Python types
    type_map = {
        "string": "str",
        "integer": "int",
        "number": "float",
        "boolean": "bool"
    }

    # Create parameter string for function signature
    param_list = []
    for param_name, param_info in properties.items():
        param_type = type_map.get(param_info.get("type", "string"), "str")
        if param_name in required:
            param_list.append(f"{param_name}: {param_type}")
        else:
            param_list.append(f"{param_name}: {param_type} = None")

    params_str = ", ".join(param_list) if param_list else ""

    # Create function dynamically with proper signature
    func_code = f"""
def {tool_name}({params_str}):
    '''{tool_description}'''
    params_dict = {{{", ".join([f'"{p}": {p}' for p in properties.keys()])}}}
    return {{
        "server": "{server_name}",
        "tool": "{tool_name}",
        "executed": True,
        "params": params_dict,
        "result": f"Simulated execution of {tool_name} from {server_name} server with params: {{params_dict}}"
    }}
"""

    # Execute the function definition
    namespace = {}
    exec(func_code, namespace)
    dynamic_tool_func = namespace[tool_name]

    # Register the tool with FastMCP
    mcp.tool()(dynamic_tool_func)

    print(f"Registered dynamic tool: {tool_name} from {server_name} with params: {list(properties.keys())}")


if __name__ == "__main__":
    # Run the server with streamable HTTP transport (for ADK compatibility)
    import os
    port = int(os.getenv("MCP_PORT", "8010"))

    print(f"Starting MCP Gateway on http://localhost:{port}")
    print("Available tools: search_servers, enable_server")
    print("Use enable_server to dynamically load more tools")

    mcp.run(transport="streamable-http", port=port)
