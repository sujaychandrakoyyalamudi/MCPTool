"""MCP Server implementation with lifecycle management and tool routing."""

import asyncio
import json
import time
import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Type

from pydantic import BaseModel

from mcptool.config import ServerConfig
from mcptool.logging_config import get_logger, AuditLogger, setup_logging
from mcptool.tool import ToolDefinition, ToolResult, ToolError, hash_arguments


@dataclass
class ToolContext:
    """Context passed to tool handlers during execution.
    
    Attributes:
        request_id: JSON-RPC request ID
        trace_id: W3C trace context ID
        client_info: Client metadata (name, version)
        auth_subject: Authenticated subject (if any)
        auth_scopes: Authorized scopes (if any)
        progress_callback: Async callback for sending progress updates
        cancellation_token: Token to check for cancellation
        config: Server configuration
        logger: Structured logger instance
        audit_logger: Audit logger instance
    """
    
    request_id: Any
    trace_id: str
    client_info: Dict[str, str] = field(default_factory=dict)
    auth_subject: Optional[str] = None
    auth_scopes: List[str] = field(default_factory=list)
    progress_callback: Optional[Callable] = None
    cancellation_token: Optional[asyncio.Event] = None
    config: ServerConfig = field(default_factory=ServerConfig)
    logger: Any = None
    audit_logger: Optional[AuditLogger] = None
    
    def is_cancelled(self) -> bool:
        """Check if the request has been cancelled.
        
        Returns:
            True if cancellation was requested
        """
        return self.cancellation_token is not None and self.cancellation_token.is_set()
    
    async def report_progress(self, progress: float, message: Optional[str] = None) -> None:
        """Report progress for long-running operations.
        
        Args:
            progress: Progress percentage (0-100)
            message: Optional progress message
        """
        if self.progress_callback:
            await self.progress_callback(progress, message)


@dataclass
class ServerCapabilities:
    """MCP server capabilities declaration.
    
    Attributes:
        tools: Tool-related capabilities
        resources: Resource-related capabilities
        prompts: Prompt-related capabilities
        logging: Logging capabilities
        experimental: Experimental capabilities
    """
    
    tools: Optional[Dict[str, Any]] = None
    resources: Optional[Dict[str, Any]] = None
    prompts: Optional[Dict[str, Any]] = None
    logging: Optional[Dict[str, Any]] = None
    experimental: Optional[Dict[str, Any]] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to MCP capabilities format.
        
        Returns:
            Dictionary suitable for initialize response
        """
        result = {}
        if self.tools:
            result["tools"] = self.tools
        if self.resources:
            result["resources"] = self.resources
        if self.prompts:
            result["prompts"] = self.prompts
        if self.logging:
            result["logging"] = self.logging
        if self.experimental:
            result["experimental"] = self.experimental
        return result


class MCPServer:
    """MCP-compatible server implementation.
    
    This class implements the Model Context Protocol server surface, handling:
    - Lifecycle negotiation (initialize, initialized)
    - Tool discovery (tools/list)
    - Tool execution (tools/call)
    - Progress notifications
    - Cancellation
    - Structured logging
    
    The server supports both stdio and Streamable HTTP transports.
    
    Example usage:
        ```python
        from mcptool import MCPServer, ToolContext, ToolResult
        from pydantic import BaseModel
        
        server = MCPServer(name="my-server", version="1.0.0")
        
        @server.tool()
        async def search_issues(ctx: ToolContext, repo: str, query: str) -> ToolResult:
            # Implementation here
            return ToolResult.success({"items": [...]})
        
        # Run with stdio transport
        await server.run_stdio()
        ```
    """
    
    def __init__(
        self,
        name: str = "mcptool-server",
        version: str = "1.0.0",
        config: Optional[ServerConfig] = None,
    ):
        """Initialize MCP server.
        
        Args:
            name: Server name for discovery
            version: Server version
            config: Optional server configuration
        """
        self.name = name
        self.version = version
        self.config = config or ServerConfig.from_env()
        
        self._tools: Dict[str, ToolDefinition] = {}
        self._handlers: Dict[str, Callable] = {}
        self._initialized = False
        self._client_info: Dict[str, Any] = {}
        self._protocol_version: str = self.config.protocol_version
        
        self.logger = get_logger(name)
        self.audit_logger = AuditLogger(self.logger)
        
        # Capabilities
        self.capabilities = ServerCapabilities(
            tools={"listChanged": True},
            logging={"severityLevels": ["debug", "info", "notice", "warning", "error", "critical"]},
        )
    
    def tool(
        self,
        name: Optional[str] = None,
        title: Optional[str] = None,
        description: Optional[str] = None,
        risk_tier: str = "read_only",
        requires_approval: bool = False,
    ) -> Callable:
        """Decorator to register a tool handler.
        
        Args:
            name: Tool name (defaults to function name)
            title: Human-readable title (defaults to capitalized name)
            description: Tool description (defaults to docstring)
            risk_tier: Risk classification
            requires_approval: Whether human approval is needed
        
        Returns:
            Decorator function
        
        Example:
            ```python
            @server.tool(description="Search for issues")
            async def search_issues(ctx: ToolContext, repo: str, query: str) -> ToolResult:
                ...
            ```
        """
        def decorator(func: Callable) -> Callable:
            tool_name = name or func.__name__
            tool_title = title or tool_name.replace("_", " ").title()
            tool_description = description or (func.__doc__ or "").strip()
            
            # Extract parameter schema from function signature
            import inspect
            sig = inspect.signature(func)
            
            # Build input schema from parameters (excluding ctx)
            properties = {}
            required = []
            
            for param_name, param in sig.parameters.items():
                if param_name == "ctx" or param_name == "context":
                    continue
                
                # Determine type
                if param.annotation == inspect.Parameter.empty:
                    param_type = "string"
                elif param.annotation == str:
                    param_type = "string"
                elif param.annotation == int:
                    param_type = "integer"
                elif param.annotation == float:
                    param_type = "number"
                elif param.annotation == bool:
                    param_type = "boolean"
                elif param.annotation == list:
                    param_type = "array"
                else:
                    param_type = "string"
                
                prop_schema = {"type": param_type}
                if param.default != inspect.Parameter.empty:
                    prop_schema["default"] = param.default
                else:
                    required.append(param_name)
                
                properties[param_name] = prop_schema
            
            input_schema = {
                "$schema": "https://json-schema.org/draft/2020-12/schema",
                "type": "object",
                "properties": properties,
                "required": required,
                "additionalProperties": False,
            }
            
            tool_def = ToolDefinition(
                name=tool_name,
                title=tool_title,
                description=tool_description,
                input_schema=input_schema,
                risk_tier=risk_tier,
                requires_approval=requires_approval,
            )
            
            self._tools[tool_name] = tool_def
            self._handlers[tool_name] = func
            
            self.logger.info(
                "tool_registered",
                tool_name=tool_name,
                risk_tier=risk_tier,
            )
            
            return func
        
        return decorator
    
    def register_tool(
        self,
        definition: ToolDefinition,
        handler: Callable,
    ) -> None:
        """Register a tool programmatically.
        
        Args:
            definition: Tool definition
            handler: Async function to handle tool calls
        """
        self._tools[definition.name] = definition
        self._handlers[definition.name] = handler
        
        self.logger.info(
            "tool_registered",
            tool_name=definition.name,
            risk_tier=definition.risk_tier,
        )
    
    async def handle_initialize(
        self,
        params: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Handle initialize request.
        
        Args:
            params: Initialize parameters
        
        Returns:
            Initialize response with capabilities
        """
        self._client_info = params.get("clientInfo", {})
        requested_version = params.get("protocolVersion", self._protocol_version)
        
        # Version negotiation - use client's version if compatible
        self._protocol_version = requested_version
        
        response = {
            "protocolVersion": self._protocol_version,
            "capabilities": self.capabilities.to_dict(),
            "serverInfo": {
                "name": self.name,
                "version": self.version,
            },
        }
        
        self.logger.info(
            "initialize",
            client_info=self._client_info,
            protocol_version=self._protocol_version,
        )
        
        return response
    
    async def handle_initialized(self, params: Dict[str, Any]) -> None:
        """Handle initialized notification.
        
        Args:
            params: Initialized notification params
        """
        self._initialized = True
        self.logger.info("session_initialized", client_info=self._client_info)
    
    async def handle_tools_list(
        self,
        params: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Handle tools/list request.
        
        Args:
            params: List parameters (may include cursor for pagination)
        
        Returns:
            Tools list response
        """
        cursor = params.get("cursor")
        
        # Simple pagination - return all tools for now
        tools = [tool.to_dict() for tool in self._tools.values()]
        
        response = {"tools": tools}
        
        self.logger.debug(
            "tools_listed",
            count=len(tools),
            cursor=cursor,
        )
        
        return response
    
    async def handle_tools_call(
        self,
        params: Dict[str, Any],
        request_id: Any,
    ) -> Dict[str, Any]:
        """Handle tools/call request.
        
        Args:
            params: Call parameters (name, arguments)
            request_id: JSON-RPC request ID
        
        Returns:
            Tool call result
        
        Raises:
            ToolError: If tool execution fails
        """
        tool_name = params.get("name")
        arguments = params.get("arguments", {})
        
        start_time = time.time()
        trace_id = str(uuid.uuid4())
        
        if tool_name not in self._tools:
            return ToolResult.error(
                f"Unknown tool: {tool_name}",
                error_code="TOOL_NOT_FOUND",
            ).to_mcp_response()
        
        tool_def = self._tools[tool_name]
        handler = self._handlers[tool_name]
        
        # Validate arguments against schema
        from mcptool.tool import validate_against_schema
        is_valid, validation_error = validate_against_schema(arguments, tool_def.input_schema)
        if not is_valid:
            return ToolResult.error(
                f"Invalid arguments: {validation_error}",
                error_code="VALIDATION_ERROR",
            ).to_mcp_response()
        
        # Create tool context
        ctx = ToolContext(
            request_id=request_id,
            trace_id=trace_id,
            client_info=self._client_info,
            config=self.config,
            logger=self.logger,
            audit_logger=self.audit_logger,
        )
        
        try:
            # Execute tool
            self.logger.info(
                "tool_call_started",
                tool_name=tool_name,
                trace_id=trace_id,
            )
            
            result = await handler(ctx, **arguments)
            
            latency_ms = int((time.time() - start_time) * 1000)
            
            # Audit logging for mutating operations
            if self.config.enable_audit_logging and tool_def.risk_tier != "read_only":
                self.audit_logger.log_tool_call(
                    tool_name=tool_name,
                    request_id=request_id,
                    trace_id=trace_id,
                    client_info=self._client_info,
                    server_info={"name": self.name, "version": self.version},
                    args_hash=hash_arguments(arguments),
                    auth_subject=ctx.auth_subject or "anonymous",
                    auth_scopes=ctx.auth_scopes,
                    result_status="ok" if not result.is_error else "error",
                    latency_ms=latency_ms,
                    is_error=result.is_error,
                    risk_tier=tool_def.risk_tier,
                    approval_required=tool_def.requires_approval,
                )
            
            self.logger.info(
                "tool_call_completed",
                tool_name=tool_name,
                trace_id=trace_id,
                latency_ms=latency_ms,
                is_error=result.is_error,
            )
            
            return result.to_mcp_response()
        
        except ToolError as e:
            latency_ms = int((time.time() - start_time) * 1000)
            
            self.logger.error(
                "tool_call_failed",
                tool_name=tool_name,
                trace_id=trace_id,
                error=e.message,
                latency_ms=latency_ms,
            )
            
            return e.to_result().to_mcp_response()
        
        except asyncio.CancelledError:
            self.logger.warning(
                "tool_call_cancelled",
                tool_name=tool_name,
                trace_id=trace_id,
            )
            raise
        
        except Exception as e:
            latency_ms = int((time.time() - start_time) * 1000)
            
            self.logger.exception(
                "tool_call_unexpected_error",
                tool_name=tool_name,
                trace_id=trace_id,
                error=str(e),
                latency_ms=latency_ms,
            )
            
            return ToolResult.error(str(e), "INTERNAL_ERROR").to_mcp_response()
    
    async def run_stdio(self) -> None:
        """Run server using stdio transport.
        
        This reads JSON-RPC messages from stdin and writes responses to stdout.
        Suitable for local development and integration with MCP clients that
        spawn servers as subprocesses.
        """
        setup_logging(
            level=self.config.log_level,
            format_type="console",
            service_name=self.name,
        )
        
        self.logger.info("server_starting", transport="stdio")
        
        reader = asyncio.StreamReader()
        protocol = asyncio.StreamReaderProtocol(reader)
        loop = asyncio.get_event_loop()
        await loop.connect_read_pipe(lambda: protocol, sys.stdin)
        
        writer_transport, writer_protocol = await loop.connect_write_pipe(
            asyncio.streams.FlowControlMixin, sys.stdout
        )
        writer = asyncio.StreamWriter(writer_transport, writer_protocol, reader, loop)
        
        while True:
            line = await reader.readline()
            if not line:
                break
            
            try:
                message = json.loads(line.decode())
                response = await self._handle_message(message)
                
                if response is not None:
                    response_line = json.dumps(response) + "\n"
                    writer.write(response_line.encode())
                    await writer.drain()
            
            except json.JSONDecodeError as e:
                error_response = {
                    "jsonrpc": "2.0",
                    "id": None,
                    "error": {
                        "code": -32700,
                        "message": f"Parse error: {e}",
                    },
                }
                writer.write((json.dumps(error_response) + "\n").encode())
                await writer.drain()
        
        self.logger.info("server_stopped", transport="stdio")
    
    async def _handle_message(self, message: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Handle incoming JSON-RPC message.
        
        Args:
            message: Parsed JSON-RPC message
        
        Returns:
            Response message or None for notifications
        """
        jsonrpc = message.get("jsonrpc", "2.0")
        method = message.get("method")
        params = message.get("params", {})
        request_id = message.get("id")
        
        if jsonrpc != "2.0":
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "error": {
                    "code": -32600,
                    "message": "Invalid Request",
                },
            }
        
        try:
            # Handle requests
            if request_id is not None:
                if method == "initialize":
                    result = await self.handle_initialize(params)
                    return {
                        "jsonrpc": "2.0",
                        "id": request_id,
                        "result": result,
                    }
                
                elif method == "tools/list":
                    if not self._initialized:
                        raise ToolError("Session not initialized", "NOT_INITIALIZED")
                    
                    result = await self.handle_tools_list(params)
                    return {
                        "jsonrpc": "2.0",
                        "id": request_id,
                        "result": result,
                    }
                
                elif method == "tools/call":
                    if not self._initialized:
                        raise ToolError("Session not initialized", "NOT_INITIALIZED")
                    
                    result = await self.handle_tools_call(params, request_id)
                    return {
                        "jsonrpc": "2.0",
                        "id": request_id,
                        "result": result,
                    }
                
                else:
                    return {
                        "jsonrpc": "2.0",
                        "id": request_id,
                        "error": {
                            "code": -32601,
                            "message": f"Method not found: {method}",
                        },
                    }
            
            # Handle notifications
            else:
                if method == "notifications/initialized":
                    await self.handle_initialized(params)
                
                elif method == "notifications/cancelled":
                    # Handle cancellation
                    pass
                
                else:
                    self.logger.warning("unknown_notification", method=method)
                
                return None
        
        except ToolError as e:
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "error": {
                    "code": -32000,
                    "message": e.message,
                    "data": {"error_code": e.error_code},
                },
            }
        
        except Exception as e:
            self.logger.exception("unexpected_error", error=str(e))
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "error": {
                    "code": -32603,
                    "message": "Internal error",
                },
            }


# Import sys at module level for run_stdio
import sys
