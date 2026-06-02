"""
MCPTool - Production-grade MCP tool server with LangChain integration.

This package provides a Model Context Protocol (MCP) compatible server that exposes
callable tools to LLM clients through standardized JSON-RPC 2.0 interfaces.

Key features:
- Lifecycle negotiation (initialize, version, capabilities)
- Typed input/output schemas using JSON Schema 2020-12
- Structured outputs with structuredContent and isError support
- Progress notifications, cancellation, and logging
- OAuth 2.1 authorization for remote HTTP servers
- Observability with OpenTelemetry traces and Prometheus metrics
- LangChain integration for seamless agent workflows
"""

from mcptool.server import MCPServer, ToolContext
from mcptool.tool import ToolResult, ToolError, ToolDefinition
from mcptool.langchain_integration import MCPToolLangChain
from mcptool.config import ServerConfig
from mcptool.logging_config import setup_logging, get_logger

__version__ = "1.0.0"
__all__ = [
    "MCPServer",
    "ToolContext",
    "ToolResult",
    "ToolError",
    "ToolDefinition",
    "MCPToolLangChain",
    "ServerConfig",
    "setup_logging",
    "get_logger",
]
