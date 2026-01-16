# MCP Gateway - Dynamic Tool Discovery PoC

A Proof of Concept demonstrating dynamic MCP (Model Context Protocol) tool discovery using Google Agent Development Kit (ADK) and FastMCP.

## Overview

This project implements a dynamic MCP gateway system where:

1. **MCP Gateway** starts with minimal tools (search and enable)
2. **ADK Agent** can discover available MCP servers
3. **Dynamic Loading** - when a server is enabled, its tools become immediately available
4. **No restart required** - tools appear in the gateway automatically

## Architecture

```
┌─────────────────┐
│  ADK Agent      │
│  (Google ADK)   │
└────────┬────────┘
         │
         │ HTTP/SSE (port 8010)
         │ MCP Protocol
         ▼
┌─────────────────┐
│  MCP Gateway    │
│  (FastMCP/SSE)  │
│                 │
│  Initial Tools: │
│  - search_servers
│  - enable_server
└────────┬────────┘
         │
         │ Dynamic Loading
         ▼
┌─────────────────────────────┐
│  Simulated MCP Servers:     │
│  - weather (2 tools)        │
│  - database (2 tools)       │
│  - calculator (1 tool)      │
└─────────────────────────────┘
```

## Setup

### 1. Activate Virtual Environment

```bash
source .venv/bin/activate
```

### 2. Install Dependencies

```bash
pip install -r requirements.txt
```

### 3. Configure Environment Variables

Copy the example environment file and configure it:

```bash
cp .env.example .env
```

Edit `.env` to set your configuration:
```bash
# Model configuration (using Vertex AI / Gemini)
MODEL_NAME=vertex_ai/gemini-2.0-flash

# Or use Google AI Studio with API key
# MODEL_NAME=gemini/gemini-2.0-flash
# GOOGLE_API_KEY=your-api-key-here
```

Get your API key from: https://aistudio.google.com/apikey

## Usage

### Option 1: Run with ADK Web Interface (Recommended)

The agent uses Google ADK's web interface and connects to the MCP Gateway via HTTP/SSE:

```bash
# First, start the MCP Gateway in a separate terminal (runs on port 8010)
python gateway/server.py

# Then run the agent with adk-web
adk-web agent.main:root_agent
```

The MCP Gateway will start on `http://localhost:8010` by default.

This will open a web interface where you can interact with the agent. The agent will automatically:
1. Connect to the MCP Gateway over HTTP
2. Discover available MCP servers
3. Enable servers as needed
4. Use tools from enabled servers dynamically

### Option 2: Test Gateway Directly

You can test the MCP gateway server directly:

```bash
# Run with default port (8010)
python gateway/server.py

# Or specify a custom port
MCP_PORT=8080 python gateway/server.py
```

The gateway exposes its tools via HTTP/SSE on the specified port.

## Available Simulated Servers

### Weather Server
- `get_weather(location)` - Get current weather
- `get_forecast(location, days)` - Get weather forecast

### Database Server
- `query_db(query)` - Execute SQL query
- `list_tables()` - List all tables

### Calculator Server
- `calculate(expression)` - Perform math calculations

## How It Works

### Gateway Startup

When the gateway starts:
- Runs an HTTP server with SSE (Server-Sent Events) on port 8010
- Exposes MCP protocol over HTTP/SSE
- Only exposes two initial tools:
  - `search_servers` - Find available MCP servers
  - `enable_server` - Enable a specific server

### Dynamic Tool Discovery Workflow

1. **Agent queries available tools** → Gets `search_servers` and `enable_server`

2. **Agent calls `search_servers()`** → Discovers weather, database, calculator servers

3. **Agent calls `enable_server("weather")`** → Gateway loads weather server tools

4. **Agent queries tools again** → Now sees `search_servers`, `enable_server`, `get_weather`, `get_forecast`

5. **Agent can now use weather tools** → Calls `get_weather("San Francisco")`

### Key Features

- **HTTP/SSE Transport** - MCP protocol over HTTP with Server-Sent Events
- **No restart needed** - Tools appear immediately after enabling
- **Simulated servers** - Uses hardcoded server definitions for PoC
- **Simple implementation** - Minimal code, no over-engineering
- **FastMCP dynamic registration** - Tools registered at runtime
- **ADK Integration** - Works seamlessly with Google Agent Development Kit

## Project Structure

```
MCPTest/
├── gateway/
│   └── server.py           # FastMCP gateway with dynamic tools
├── agent/
│   ├── __init__.py         # Package exports
│   ├── main.py             # Google ADK agent (root_agent)
│   └── tools.py            # MCP gateway tools (search, enable)
├── requirements.txt        # Python dependencies
├── .env.example           # Environment variables template
└── README.md              # This file
```

## Limitations (PoC)

- Simulated MCP servers (not real server connections)
- Hardcoded server definitions
- No persistence (state lost on restart)
- Minimal error handling
- No authentication/authorization
