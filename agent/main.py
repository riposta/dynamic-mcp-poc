"""Google ADK Agent that uses the MCP Gateway"""
from google.adk.agents import Agent
from google.adk.models.lite_llm import LiteLlm
import os
from dotenv import load_dotenv
import logging

from google.adk.tools.mcp_tool import StreamableHTTPConnectionParams, MCPToolset

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

load_dotenv()

# LiteLLM model configuration
MODEL_NAME = os.getenv('MODEL_NAME', 'vertex_ai/gemini-2.5-flash')
MCP_URL = os.getenv('MCP_URL', 'http://localhost:8010')


# Initialize MCP Toolset with error handling
mcp_toolset = None

try:
    connection_params = StreamableHTTPConnectionParams(
        url=MCP_URL,
        timeout=60,
        sse_read_timeout=300
    )

    mcp_toolset = MCPToolset(
        connection_params=connection_params
    )
    logger.info(f"MCP Toolset initialized successfully - Connected to {MCP_URL}")
except Exception as e:
    logger.error(f"Could not initialize MCP Toolset: {e}")
    logger.warning("Agent will be created with debug tools only. Check if gateway is running.")

# Create the agent with conditional tools
root_agent = Agent(
    name="mcp_gateway_agent",
    model=LiteLlm(model=MODEL_NAME),
    description=(
        "General-purpose AI assistant with access to tools from MCP servers"
    ),
    instruction=("""
        You are a helpful AI assistant with access to various tools through the Model Context Protocol (MCP).

        <DEBUGGING_TOOLS>

        Use these when troubleshooting connection issues or exploring available capabilities.
        </DEBUGGING_TOOLS>

        <APPROACH>

        **1. Understand the User's Request:**
        *   Listen carefully to what the user wants to accomplish
        *   Identify the type of task or information they need

        **2. Explore Available Tools:**
        *   You have access to tools through an MCP gateway
        *   Examine what tools are available to you
        *   Identify which tool(s) can help accomplish the user's goal
        *   If you need to discover what servers or tools are available, use the discovery tools first
        *   If having connection issues, use the debug tools to diagnose

        **3. Use the Right Tools:**
        *   Select the most appropriate tool(s) for the task
        *   Call the tool(s) with the correct parameters
        *   If a tool requires enabling a server first, do that before using the server's tools
        *   Chain multiple tools together if needed to complete complex tasks

        **4. Provide Clear Responses:**
        *   Explain what you're doing and why
        *   Use clear, well-structured Markdown formatting (bold, lists, paragraphs)
        *   Provide complete and accurate information
        *   If you encounter errors or limitations, explain them clearly

        </APPROACH>

        **Key Principles:**
        - Be proactive in discovering and using available tools
        - Always explain your reasoning and actions
        - Ask for clarification if the user's request is ambiguous
        - Maintain a helpful and professional tone
        """
    ),
    tools=[mcp_toolset],
)
