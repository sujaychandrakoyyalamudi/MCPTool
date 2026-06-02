"""LangChain integration for MCPTool.

This module provides LangChain-compatible tool wrappers that allow
MCP tools to be used with LangChain agents and chains.
"""

import asyncio
import json
from typing import Any, Dict, List, Optional, Type

from pydantic import BaseModel, Field


class MCPToolLangChain:
    """LangChain wrapper for MCP tools.
    
    This class provides a bridge between MCP tool definitions and LangChain's
    tool interface, allowing MCP servers to expose tools that can be used
    with LangChain agents.
    
    Example usage:
        ```python
        from langchain.agents import AgentExecutor, create_openai_functions_agent
        from langchain_openai import ChatOpenAI
        from mcptool.langchain_integration import MCPToolLangChain
        
        # Create LangChain-compatible tools from MCP server
        mcp_tools = MCPToolLangChain.from_server_url(
            "http://localhost:8080/mcp",
            auth_token="your_token_here"
        )
        
        # Use with LangChain agent
        llm = ChatOpenAI(model="gpt-4")
        agent = create_openai_functions_agent(llm, mcp_tools.tools, prompt)
        executor = AgentExecutor(agent=agent, tools=mcp_tools.tools)
        
        result = executor.invoke({"input": "Search for issues in repo acme/api"})
        ```
    """
    
    def __init__(self):
        """Initialize MCPTool LangChain wrapper."""
        self._tools: List[Any] = []
        self._tool_definitions: List[Dict[str, Any]] = []
    
    @classmethod
    def from_server(
        cls,
        server: Any,
    ) -> "MCPToolLangChain":
        """Create LangChain wrapper from MCPServer instance.
        
        Args:
            server: MCPServer instance
        
        Returns:
            Configured MCPToolLangChain instance
        """
        wrapper = cls()
        wrapper._tool_definitions = [
            tool.to_dict() for tool in server._tools.values()
        ]
        
        # Create LangChain Tool objects
        for tool_def in server._tools.values():
            langchain_tool = _create_langchain_tool(tool_def, server)
            wrapper._tools.append(langchain_tool)
        
        return wrapper
    
    @classmethod
    async def from_server_url(
        cls,
        url: str,
        auth_token: Optional[str] = None,
        timeout: int = 30,
    ) -> "MCPToolLangChain":
        """Create LangChain wrapper from remote MCP server URL.
        
        Args:
            url: MCP server URL (Streamable HTTP endpoint)
            auth_token: Optional Bearer token for authorization
            timeout: Request timeout in seconds
        
        Returns:
            Configured MCPToolLangChain instance
        """
        import httpx
        
        wrapper = cls()
        headers = {}
        if auth_token:
            headers["Authorization"] = f"Bearer {auth_token}"
        
        async with httpx.AsyncClient(timeout=timeout, headers=headers) as client:
            # Initialize session
            init_response = await client.post(
                url,
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {
                        "protocolVersion": "2025-11-25",
                        "capabilities": {},
                        "clientInfo": {
                            "name": "langchain-agent",
                            "version": "1.0.0",
                        },
                    },
                },
            )
            init_response.raise_for_status()
            
            # Send initialized notification
            await client.post(
                url,
                json={
                    "jsonrpc": "2.0",
                    "method": "notifications/initialized",
                    "params": {},
                },
            )
            
            # Get tools list
            tools_response = await client.post(
                url,
                json={
                    "jsonrpc": "2.0",
                    "id": 2,
                    "method": "tools/list",
                    "params": {},
                },
            )
            tools_response.raise_for_status()
            tools_data = tools_response.json()
            
            wrapper._tool_definitions = tools_data.get("result", {}).get("tools", [])
        
        return wrapper
    
    @property
    def tools(self) -> List[Any]:
        """Get list of LangChain Tool objects.
        
        Returns:
            List of LangChain-compatible Tool instances
        """
        return self._tools
    
    @property
    def tool_definitions(self) -> List[Dict[str, Any]]:
        """Get raw tool definitions.
        
        Returns:
            List of tool definition dictionaries
        """
        return self._tool_definitions
    
    def add_tool(
        self,
        name: str,
        description: str,
        func: Any,
        args_schema: Optional[Type[BaseModel]] = None,
    ) -> None:
        """Manually add a LangChain-compatible tool.
        
        Args:
            name: Tool name
            description: Tool description
            func: Function to execute (sync or async)
            args_schema: Optional Pydantic schema for arguments
        """
        try:
            from langchain_core.tools import Tool
            
            tool = Tool(
                name=name,
                description=description,
                func=func if not asyncio.iscoroutinefunction(func) else None,
                coroutine=func if asyncio.iscoroutinefunction(func) else None,
                args_schema=args_schema,
            )
            self._tools.append(tool)
        
        except ImportError:
            raise ImportError(
                "langchain-core is required. Install with: pip install langchain-core"
            )


def _create_langchain_tool(
    tool_definition: Any,
    server: Any,
) -> Any:
    """Create a LangChain Tool from MCP tool definition.
    
    Args:
        tool_definition: MCP ToolDefinition instance
        server: MCPServer instance
    
    Returns:
        LangChain Tool instance
    """
    try:
        from langchain_core.tools import Tool, BaseTool
        from pydantic import BaseModel, create_model
        
    except ImportError:
        raise ImportError(
            "langchain-core is required. Install with: pip install langchain-core"
        )
    
    name = tool_definition.name
    description = tool_definition.description
    input_schema = tool_definition.input_schema
    
    # Create Pydantic schema from JSON Schema
    fields = {}
    properties = input_schema.get("properties", {})
    required = input_schema.get("required", [])
    
    for param_name, param_schema in properties.items():
        param_type = param_schema.get("type", "string")
        has_default = "default" in param_schema
        default_value = param_schema.get("default")
        
        # Map JSON Schema types to Python types
        type_map = {
            "string": str,
            "integer": int,
            "number": float,
            "boolean": bool,
            "array": list,
            "object": dict,
        }
        
        python_type = type_map.get(param_type, str)
        
        if has_default:
            fields[param_name] = (python_type, Field(default=default_value))
        elif param_name in required:
            fields[param_name] = (python_type, Field(...))
        else:
            fields[param_name] = (python_type, Field(default=None))
    
    # Create dynamic Pydantic model
    args_schema = create_model(f"{name.title()}Args", **fields)
    
    # Create async function to call the tool
    async def call_tool(**kwargs):
        """Call the MCP tool with given arguments."""
        from mcptool.tool import ToolResult
        
        result = await server.handle_tools_call(
            params={"name": name, "arguments": kwargs},
            request_id=id(kwargs),
        )
        
        # Extract text from result
        if result.get("structuredContent"):
            return json.dumps(result["structuredContent"])
        elif result.get("content"):
            texts = []
            for item in result["content"]:
                if item.get("type") == "text":
                    texts.append(item.get("text", ""))
            return "\n".join(texts)
        else:
            return str(result)
    
    # Create LangChain Tool
    tool = Tool(
        name=name,
        description=description,
        coroutine=call_tool,
        args_schema=args_schema,
    )
    
    return tool


class LangChainMCPClient:
    """High-level LangChain client for MCP servers.
    
    This class simplifies using MCP tools with LangChain by providing
    a unified interface for server connection and tool execution.
    
    Example:
        ```python
        from mcptool.langchain_integration import LangChainMCPClient
        from langchain_openai import ChatOpenAI
        from langchain.agents import create_tool_calling_agent, AgentExecutor
        
        # Connect to MCP server
        client = LangChainMCPClient("http://localhost:8080/mcp")
        await client.connect()
        
        # Get tools
        tools = client.get_tools()
        
        # Create agent
        llm = ChatOpenAI(model="gpt-4")
        agent = create_tool_calling_agent(llm, tools, prompt)
        executor = AgentExecutor(agent=agent, tools=tools)
        
        # Run agent
        result = executor.invoke({"input": "What issues are open in repo acme/api?"})
        ```
    """
    
    def __init__(
        self,
        server_url: str,
        auth_token: Optional[str] = None,
        timeout: int = 30,
    ):
        """Initialize LangChain MCP client.
        
        Args:
            server_url: MCP server URL
            auth_token: Optional Bearer token
            timeout: Request timeout in seconds
        """
        self.server_url = server_url
        self.auth_token = auth_token
        self.timeout = timeout
        self._connected = False
        self._wrapper: Optional[MCPToolLangChain] = None
    
    async def connect(self) -> None:
        """Connect to MCP server and fetch tools.
        
        Raises:
            ConnectionError: If connection fails
        """
        self._wrapper = await MCPToolLangChain.from_server_url(
            self.server_url,
            self.auth_token,
            self.timeout,
        )
        self._connected = True
    
    def get_tools(self) -> List[Any]:
        """Get LangChain Tool objects.
        
        Returns:
            List of LangChain Tool instances
        
        Raises:
            RuntimeError: If not connected
        """
        if not self._connected:
            raise RuntimeError("Not connected. Call connect() first.")
        return self._wrapper.tools
    
    def get_tool_definitions(self) -> List[Dict[str, Any]]:
        """Get raw tool definitions.
        
        Returns:
            List of tool definition dictionaries
        
        Raises:
            RuntimeError: If not connected
        """
        if not self._connected:
            raise RuntimeError("Not connected. Call connect() first.")
        return self._wrapper.tool_definitions
    
    async def call_tool(
        self,
        tool_name: str,
        **arguments,
    ) -> Dict[str, Any]:
        """Call a tool directly.
        
        Args:
            tool_name: Name of tool to call
            **arguments: Tool arguments
        
        Returns:
            Tool result dictionary
        
        Raises:
            RuntimeError: If not connected
        """
        if not self._connected:
            raise RuntimeError("Not connected. Call connect() first.")
        
        import httpx
        
        headers = {}
        if self.auth_token:
            headers["Authorization"] = f"Bearer {self.auth_token}"
        
        async with httpx.AsyncClient(timeout=self.timeout, headers=headers) as client:
            response = await client.post(
                self.server_url,
                json={
                    "jsonrpc": "2.0",
                    "id": id(arguments),
                    "method": "tools/call",
                    "params": {
                        "name": tool_name,
                        "arguments": arguments,
                    },
                },
            )
            response.raise_for_status()
            return response.json().get("result", {})
