"""Tests for MCPTool server and tool functionality."""

import asyncio
import json
import pytest
from typing import Dict, Any

from mcptool.server import MCPServer, ToolContext
from mcptool.tool import ToolResult, ToolError, ToolDefinition
from mcptool.config import ServerConfig


@pytest.fixture
def server() -> MCPServer:
    """Create a test server instance."""
    config = ServerConfig(
        name="test-server",
        version="1.0.0",
        transport="stdio",
        enable_audit_logging=False,
    )
    return MCPServer(
        name="test-server",
        version="1.0.0",
        config=config,
    )


@pytest.fixture
def sample_tool_definition() -> ToolDefinition:
    """Create a sample tool definition for testing."""
    return ToolDefinition(
        name="echo",
        title="Echo Tool",
        description="Echoes back the input message",
        input_schema={
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": "object",
            "properties": {
                "message": {"type": "string"},
            },
            "required": ["message"],
            "additionalProperties": False,
        },
        risk_tier="read_only",
    )


class TestServerInitialization:
    """Test server initialization and lifecycle."""
    
    def test_server_creation(self, server: MCPServer) -> None:
        """Test basic server creation."""
        assert server.name == "test-server"
        assert server.version == "1.0.0"
        assert not server._initialized
    
    @pytest.mark.asyncio
    async def test_initialize_request(self, server: MCPServer) -> None:
        """Test initialize request handling."""
        params = {
            "protocolVersion": "2025-11-25",
            "capabilities": {},
            "clientInfo": {
                "name": "test-client",
                "version": "1.0.0",
            },
        }
        
        result = await server.handle_initialize(params)
        
        assert "protocolVersion" in result
        assert "capabilities" in result
        assert "serverInfo" in result
        assert result["serverInfo"]["name"] == "test-server"
        assert result["serverInfo"]["version"] == "1.0.0"
    
    @pytest.mark.asyncio
    async def test_initialized_notification(self, server: MCPServer) -> None:
        """Test initialized notification handling."""
        # First initialize
        await server.handle_initialize({
            "protocolVersion": "2025-11-25",
            "capabilities": {},
            "clientInfo": {"name": "test-client", "version": "1.0.0"},
        })
        
        # Then send initialized notification
        await server.handle_initialized({})
        
        assert server._initialized


class TestToolRegistration:
    """Test tool registration and discovery."""
    
    def test_register_tool_decorator(self, server: MCPServer) -> None:
        """Test tool registration via decorator."""
        
        @server.tool(description="Test tool")
        async def test_tool(ctx: ToolContext, param1: str) -> ToolResult:
            return ToolResult.success({"result": param1})
        
        assert "test_tool" in server._tools
        assert "test_tool" in server._handlers
        
        tool_def = server._tools["test_tool"]
        assert tool_def.name == "test_tool"
        assert tool_def.description == "Test tool"
    
    def test_register_tool_programmatic(self, server: MCPServer, sample_tool_definition: ToolDefinition) -> None:
        """Test programmatic tool registration."""
        
        async def handler(ctx: ToolContext, **kwargs) -> ToolResult:
            return ToolResult.success(kwargs)
        
        server.register_tool(sample_tool_definition, handler)
        
        assert "echo" in server._tools
        assert "echo" in server._handlers
    
    @pytest.mark.asyncio
    async def test_tools_list(self, server: MCPServer) -> None:
        """Test tools/list request."""
        # Initialize first
        await server.handle_initialize({
            "protocolVersion": "2025-11-25",
            "capabilities": {},
            "clientInfo": {"name": "test-client", "version": "1.0.0"},
        })
        await server.handle_initialized({})
        
        # Register a tool
        @server.tool(description="Test tool")
        async def test_tool(ctx: ToolContext, param1: str) -> ToolResult:
            return ToolResult.success({"result": param1})
        
        # List tools
        result = await server.handle_tools_list({})
        
        assert "tools" in result
        assert len(result["tools"]) == 1
        assert result["tools"][0]["name"] == "test_tool"


class TestToolExecution:
    """Test tool execution and result handling."""
    
    @pytest.mark.asyncio
    async def test_successful_tool_call(self, server: MCPServer) -> None:
        """Test successful tool execution."""
        # Initialize
        await server.handle_initialize({
            "protocolVersion": "2025-11-25",
            "capabilities": {},
            "clientInfo": {"name": "test-client", "version": "1.0.0"},
        })
        await server.handle_initialized({})
        
        # Register tool
        @server.tool(description="Echo tool")
        async def echo(ctx: ToolContext, message: str) -> ToolResult:
            return ToolResult.success({"echoed": message})
        
        # Call tool
        result = await server.handle_tools_call(
            params={
                "name": "echo",
                "arguments": {"message": "hello"},
            },
            request_id=1,
        )
        
        assert "content" in result
        assert "structuredContent" in result
        assert result["isError"] is False
        assert result["structuredContent"]["echoed"] == "hello"
    
    @pytest.mark.asyncio
    async def test_tool_not_found(self, server: MCPServer) -> None:
        """Test calling non-existent tool."""
        # Initialize
        await server.handle_initialize({
            "protocolVersion": "2025-11-25",
            "capabilities": {},
            "clientInfo": {"name": "test-client", "version": "1.0.0"},
        })
        await server.handle_initialized({})
        
        result = await server.handle_tools_call(
            params={
                "name": "nonexistent",
                "arguments": {},
            },
            request_id=1,
        )
        
        assert result["isError"] is True
        assert "Unknown tool" in result["content"][0]["text"]
    
    @pytest.mark.asyncio
    async def test_validation_error(self, server: MCPServer) -> None:
        """Test input validation error."""
        # Initialize
        await server.handle_initialize({
            "protocolVersion": "2025-11-25",
            "capabilities": {},
            "clientInfo": {"name": "test-client", "version": "1.0.0"},
        })
        await server.handle_initialized({})
        
        # Register tool with required parameter
        @server.tool(description="Test tool")
        async def required_param(ctx: ToolContext, required: str) -> ToolResult:
            return ToolResult.success({"result": required})
        
        # Call without required parameter - should return error result, not raise
        result = await server.handle_tools_call(
            params={
                "name": "required_param",
                "arguments": {},
            },
            request_id=1,
        )
        
        # The result should be an error response
        assert result["isError"] is True


class TestToolResult:
    """Test ToolResult creation and formatting."""
    
    def test_success_result(self) -> None:
        """Test successful result creation."""
        result = ToolResult.success(
            structured_content={"key": "value"},
            text_fallback="Success",
        )
        
        assert result.is_error is False
        assert result.structured_content == {"key": "value"}
        assert len(result.content) == 1
        assert result.content[0]["text"] == "Success"
    
    def test_error_result(self) -> None:
        """Test error result creation."""
        result = ToolResult.error(
            message="Something went wrong",
            error_code="TEST_ERROR",
        )
        
        assert result.is_error is True
        assert "Something went wrong" in result.content[0]["text"]
        assert result.structured_content["error"] == "Something went wrong"
        assert result.structured_content["error_code"] == "TEST_ERROR"
    
    def test_to_mcp_response(self) -> None:
        """Test MCP response conversion."""
        result = ToolResult.success(
            structured_content={"data": [1, 2, 3]},
        )
        
        response = result.to_mcp_response()
        
        assert "content" in response
        assert "structuredContent" in response
        assert "isError" in response
        assert response["isError"] is False


class TestJSONRPCHandling:
    """Test JSON-RPC message handling."""
    
    @pytest.mark.asyncio
    async def test_invalid_jsonrpc_version(self, server: MCPServer) -> None:
        """Test handling of invalid JSON-RPC version."""
        message = {
            "jsonrpc": "1.0",
            "id": 1,
            "method": "initialize",
            "params": {},
        }
        
        response = await server._handle_message(message)
        
        assert response["error"]["code"] == -32600
        assert "Invalid Request" in response["error"]["message"]
    
    @pytest.mark.asyncio
    async def test_unknown_method(self, server: MCPServer) -> None:
        """Test handling of unknown method."""
        # Initialize first
        await server.handle_initialize({
            "protocolVersion": "2025-11-25",
            "capabilities": {},
            "clientInfo": {"name": "test-client", "version": "1.0.0"},
        })
        await server.handle_initialized({})
        
        message = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "unknown/method",
            "params": {},
        }
        
        response = await server._handle_message(message)
        
        assert response["error"]["code"] == -32601
        assert "Method not found" in response["error"]["message"]
    
    @pytest.mark.asyncio
    async def test_notification_handling(self, server: MCPServer) -> None:
        """Test notification (no ID) handling."""
        # Initialize first
        await server.handle_initialize({
            "protocolVersion": "2025-11-25",
            "capabilities": {},
            "clientInfo": {"name": "test-client", "version": "1.0.0"},
        })
        
        # Send initialized notification (no ID)
        message = {
            "jsonrpc": "2.0",
            "method": "notifications/initialized",
            "params": {},
        }
        
        response = await server._handle_message(message)
        
        assert response is None
        assert server._initialized


class TestServerConfig:
    """Test server configuration."""
    
    def test_default_config(self) -> None:
        """Test default configuration values."""
        config = ServerConfig()
        
        assert config.name == "mcptool-server"
        assert config.version == "1.0.0"
        assert config.transport == "stdio"
        assert config.protocol_version == "2025-11-25"
        assert config.enable_auth is False
    
    def test_config_from_env(self, monkeypatch) -> None:
        """Test configuration from environment variables."""
        monkeypatch.setenv("MCPTOOL_NAME", "custom-server")
        monkeypatch.setenv("MCPTOOL_PORT", "9000")
        monkeypatch.setenv("MCPTOOL_ENABLE_TRACING", "true")
        
        config = ServerConfig.from_env()
        
        assert config.name == "custom-server"
        assert config.port == 9000
        assert config.enable_tracing is True
    
    def test_config_validation(self) -> None:
        """Test configuration validation."""
        # Invalid transport
        config = ServerConfig(transport="invalid")
        with pytest.raises(ValueError, match="Invalid transport"):
            config.validate()
        
        # Invalid port
        config = ServerConfig(port=70000)
        with pytest.raises(ValueError, match="Invalid port"):
            config.validate()
        
        # Auth enabled without issuer
        config = ServerConfig(enable_auth=True)
        with pytest.raises(ValueError, match="auth_issuer is required"):
            config.validate()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
