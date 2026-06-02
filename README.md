# MCPTool - Production-Grade MCP Tool Server with LangChain Integration

A production-ready Model Context Protocol (MCP) server implementation that exposes callable tools to LLM clients through standardized JSON-RPC 2.0 interfaces, with seamless LangChain integration.

## Features

### Core Protocol Support
- **Lifecycle Management**: Full `initialize`/`initialized` handshake with version negotiation
- **Transport Support**: stdio for local development, Streamable HTTP for remote deployments
- **Tool Discovery**: `tools/list` with pagination and change notifications
- **Typed Schemas**: JSON Schema 2020-12 for input validation and output structure
- **Structured Outputs**: `structuredContent`, text fallback, and `isError` support
- **Progress & Cancellation**: Long-running operation support with progress reporting

### Security & Compliance
- **OAuth 2.1 Authorization**: RFC 8414, RFC 9728, RFC 8707 compliant for remote servers
- **PKCE Support**: Secure authorization code flows
- **Audit Logging**: Immutable audit trails for mutating operations
- **Risk Tiers**: Tool classification (read_only, mutating, sensitive)
- **Input Validation**: Strict JSON Schema validation at the edge

### Observability
- **Structured Logging**: JSON logs with severity levels via structlog
- **OpenTelemetry**: Distributed tracing with W3C Trace Context
- **Prometheus Metrics**: Ready-to-use metrics endpoint
- **Health Checks**: Kubernetes-compatible liveness/readiness probes

### LangChain Integration
- **Tool Wrappers**: Automatic conversion of MCP tools to LangChain Tools
- **Async Support**: Full async/await support for modern LangChain agents
- **Schema Generation**: Automatic Pydantic schema generation from JSON Schema

## Installation

```bash
pip install mcptool

# With LangChain support
pip install mcptool[langchain]

# For development
pip install mcptool[dev]
```

## Quick Start

### Creating an MCP Server

```python
from mcptool import MCPServer, ToolContext, ToolResult

server = MCPServer(name="my-tools", version="1.0.0")

@server.tool(description="Search for issues in a GitHub repository")
async def search_issues(
    ctx: ToolContext,
    repo: str,
    query: str,
    state: str = "open",
    limit: int = 20,
) -> ToolResult:
    """Search for issues matching the query."""
    # Your implementation here
    issues = [...]  # Fetch from API
    
    return ToolResult.success(
        structured_content={"items": issues, "total": len(issues)},
        text_fallback=f"Found {len(issues)} issues"
    )

# Run with stdio transport
if __name__ == "__main__":
    import asyncio
    asyncio.run(server.run_stdio())
```

### Using with LangChain

```python
from langchain_openai import ChatOpenAI
from langchain.agents import create_tool_calling_agent, AgentExecutor
from mcptool.langchain_integration import LangChainMCPClient

# Connect to MCP server
client = LangChainMCPClient("http://localhost:8080/mcp")
await client.connect()

# Get LangChain-compatible tools
tools = client.get_tools()

# Create agent
llm = ChatOpenAI(model="gpt-4")
agent = create_tool_calling_agent(llm, tools, prompt)
executor = AgentExecutor(agent=agent, tools=tools)

# Run agent
result = executor.invoke({"input": "Find open bugs in repo acme/api"})
print(result)
```

### Example Server

Run the included example server:

```bash
python -m mcptool.examples
```

This provides sample tools including:
- `search_issues`: Search GitHub issues
- `get_issue`: Get issue details
- `add_issue_comment`: Add comments (mutating, requires approval)
- `calculate`: Safe math expression evaluation
- `get_weather`: Weather lookup (mock data)

## Configuration

Configure via environment variables:

```bash
export MCPTOOL_NAME=my-server
export MCPTOOL_VERSION=1.0.0
export MCPTOOL_TRANSPORT=http  # or 'stdio'
export MCPTOOL_PORT=8080
export MCPTOOL_LOG_LEVEL=INFO
export MCPTOOL_ENABLE_AUTH=true
export MCPTOOL_AUTH_ISSUER=https://auth.example.com
export MCPTOOL_AUTH_CLIENT_ID=your-client-id
export MCPTOOL_ENABLE_TRACING=true
export MCPTOOL_OTLP_ENDPOINT=http://localhost:4317
export MCPTOOL_ENABLE_METRICS=true
export MCPTOOL_ENABLE_AUDIT_LOGGING=true
```

Or programmatically:

```python
from mcptool import ServerConfig, MCPServer

config = ServerConfig(
    name="my-server",
    transport="http",
    port=8080,
    enable_auth=True,
    auth_issuer="https://auth.example.com",
    enable_tracing=True,
)

server = MCPServer(config=config)
```

## Architecture

```
┌─────────────┐     ┌──────────────┐     ┌─────────────┐
│   LLM Host  │────▶│  MCP Client  │────▶│ Policy Gate │
│  (LangChain)│     │  (Runtime)   │     │ (Auth/AuthZ)│
└─────────────┘     └──────────────┘     └─────────────┘
                                              │
                                              ▼
┌─────────────────────────────────────────────────────┐
│                  MCP Server                          │
│  ┌─────────┐  ┌─────────┐  ┌─────────┐  ┌────────┐ │
│  │ Read    │  │Mutating │  │Long-run │  │ Audit  │ │
│  │ Tools   │  │ Tools   │  │ Jobs    │  │ Logger │ │
│  └─────────┘  └─────────┘  └─────────┘  └────────┘ │
└─────────────────────────────────────────────────────┘
```

## Testing

```bash
# Run tests
pytest tests/ -v

# With coverage
pytest tests/ --cov=mcptool --cov-report=html

# Run specific test class
pytest tests/test_server.py::TestToolExecution -v
```

## Project Structure

```
mcptool/
├── __init__.py           # Package exports
├── config.py             # Server configuration
├── logging_config.py     # Structured logging & audit
├── tool.py               # Tool definitions & results
├── server.py             # MCP server implementation
├── langchain_integration.py  # LangChain wrappers
└── examples.py           # Example tools

tests/
└── test_server.py        # Unit tests
```

## License

MIT License - see LICENSE file for details.

## Contributing

1. Fork the repository
2. Create a feature branch
3. Run tests: `pytest tests/ -v`
4. Submit a pull request

For more information on the Model Context Protocol, visit [modelcontextprotocol.io](https://modelcontextprotocol.io).
