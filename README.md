# MCPTool

MCPTool is a Python implementation of a [Model Context Protocol](https://modelcontextprotocol.io) (MCP) tool server that serves async Python functions to MCP clients as tools over stdio, using JSON-RPC 2.0.

Status: early-stage. Unit tests cover the request handlers, and one end-to-end test runs the example server over stdio with the `calculate` tool. The other example tools and the LangChain adapter are untested.

## What it does

You register async functions with the `@server.tool()` decorator. MCPTool builds a JSON Schema for each function's arguments, and `MCPServer.run_stdio()` reads one JSON-RPC message per line from stdin and writes responses to stdout. Logs go to stderr, so stdout carries only JSON-RPC messages.

| Message | Behavior |
| --- | --- |
| `initialize` | Returns `serverInfo`, capabilities, and the client's requested `protocolVersion` (default `2025-11-25`). |
| `notifications/initialized` | Marks the session ready. Before this, `tools/list` and `tools/call` get a `-32000` error. |
| `tools/list` | Returns every registered tool with its input schema. |
| `tools/call` | Validates the arguments, awaits the tool, and returns `content`, `structuredContent`, and `isError`. |
| `notifications/cancelled` | Accepted and ignored. |
| Anything else | Unknown requests get `-32601`, unknown notifications are logged, and invalid JSON gets `-32700`. |

## Features

- **Tool registration.** `@server.tool()` builds the input schema from the function signature: a draft 2020-12 `$schema`, JSON types for `str`, `int`, `float`, `bool`, and `list`, `required` for parameters without defaults, and `additionalProperties: false`. You can also pass a `ToolDefinition` to `server.register_tool()`, or build one from Pydantic models with `ToolDefinition.from_pydantic()`.
- **Argument validation.** `tools/call` checks arguments against the input schema before the tool runs and returns failures as `isError` results.
- **Structured results.** `ToolResult.success()` sets `structuredContent` plus a text block (your `text_fallback`, or the JSON-encoded data). `ToolResult.error()` and a raised `ToolError` produce `isError: true`.
- **Risk labels and audit events.** Each tool has a free-form `risk_tier` (default `read_only`) and a `requires_approval` flag. When a tool whose tier is not `read_only` returns, the server logs a `tool_call_audit` event with the tier, a SHA-256 hash of the arguments, the latency, and the result status.
- **Structured logging.** `setup_logging()` configures structlog for JSON or console output on stderr, with ISO timestamps. `run_stdio()` uses the console format.
- **Example server.** `mcptool/examples.py` defines five demo tools (see below).

## Install

Requires Python 3.10 or later and Git.

```bash
pip install "git+https://github.com/sujaychandrakoyyalamudi/MCPTool.git"

# Optional LangChain dependencies (the adapter does not work yet; see Safety and limits)
pip install "mcptool[langchain] @ git+https://github.com/sujaychandrakoyyalamudi/MCPTool.git"
```

Not published on PyPI. The PyPI package named `mcptool` is an unrelated project; don't install it.

## Quick start

Save this as `my_server.py`:

```python
import asyncio

from mcptool import MCPServer, ToolContext, ToolResult

server = MCPServer(name="demo", version="0.1.0")


@server.tool(description="Add two integers.")
async def add(ctx: ToolContext, a: int, b: int) -> ToolResult:
    return ToolResult.success(
        structured_content={"sum": a + b},
        text_fallback=f"{a} + {b} = {a + b}",
    )


if __name__ == "__main__":
    asyncio.run(server.run_stdio())
```

Each tool must be an `async` function that returns a `ToolResult`. Its first parameter, named `ctx` or `context`, receives a `ToolContext`. To try the server, pipe in the handshake and a call:

```bash
printf '%s\n' \
  '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-11-25","capabilities":{},"clientInfo":{"name":"cli","version":"0"}}}' \
  '{"jsonrpc":"2.0","method":"notifications/initialized"}' \
  '{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"add","arguments":{"a":2,"b":3}}}' \
  | python my_server.py
```

The server writes only the two JSON-RPC responses to stdout, and the second contains `"structuredContent": {"sum": 5}`. The log lines around them go to stderr. Add `2>/dev/null` to hide them.

### Example server

`python -m mcptool.examples` prints a banner to stderr, then serves these tools over stdio:

| Tool | Behavior |
| --- | --- |
| `search_issues` | Queries GitHub's public search API without a token. Returns mock issues on network errors or HTTP 401. |
| `get_issue` | Fetches one issue from the GitHub REST API without a token. Returns a mock issue on network errors. |
| `add_issue_comment` | Simulated: returns a fake comment and calls no API. Marked `mutating` with `requires_approval=True`, but approval is not enforced. |
| `calculate` | Evaluates arithmetic with `eval` after a character allow-list. |
| `get_weather` | Returns random mock weather data. |

## Configuration

Unless you pass `config=ServerConfig(...)`, `MCPServer()` loads settings from environment variables with `ServerConfig.from_env()`. These settings have an effect:

| `ServerConfig` field | Environment variable | Default | Effect |
| --- | --- | --- | --- |
| `log_level` | `MCPTOOL_LOG_LEVEL` | `INFO` | Log level that `run_stdio()` passes to `setup_logging()`. |
| `enable_audit_logging` | `MCPTOOL_ENABLE_AUDIT_LOGGING` | `true` | Logs audit events for tools whose `risk_tier` is not `read_only`. |
| `protocol_version` | none | `2025-11-25` | `protocolVersion` returned when the client's `initialize` request omits it. |

```python
from mcptool import MCPServer, ServerConfig

config = ServerConfig(log_level="DEBUG", enable_audit_logging=False)
server = MCPServer(name="demo", version="0.1.0", config=config)
```

Boolean variables accept `true`, `1`, `yes`, or `on` (any case); other values mean false. Pass the server name and version to `MCPServer()`: `ServerConfig.name`, `ServerConfig.version`, `MCPTOOL_NAME`, and `MCPTOOL_VERSION` are not used. `ServerConfig` also has transport, host, port, auth, tracing, metrics, concurrency, timeout, and audit-log-path fields. `from_env()` reads them, but the server does not use them, and it never calls `ServerConfig.validate()`.

## Safety and limits

- There is no authentication or authorization. Use the server only with local, trusted clients.
- `risk_tier` and `requires_approval` are labels. Nothing blocks a tool or asks for approval before it runs, and audit events always report approval status `not_required`.
- Audit events are ordinary log lines on the same stream as other logs, with no tamper protection. Calls that fail validation or raise an exception are not audited.
- The stdio loop handles one message at a time, so a slow tool blocks the server. There are no timeouts or concurrency limits. A JSON-RPC batch (a JSON array) raises an exception that stops the server.
- Validation uses the `jsonschema` package when it can be imported. It is not a declared dependency; without it, only required fields and top-level types are checked. Tool output is not validated against `outputSchema`.
- Signature-based schemas map only `str`, `int`, `float`, `bool`, and `list`. Other annotations, such as `List[str]` or `dict`, become `"string"`.
- Unexpected exceptions are returned to the client as `INTERNAL_ERROR` results that include the exception message.
- `calculate` blocks names and attribute access but allows `**`, so an expression such as `9**9**9` can tie up the server.
- The server echoes any requested `protocolVersion` without checking it, returns `-32601` for `ping`, and advertises `tools.listChanged` and `logging` capabilities that it does not implement.
- The LangChain adapter does not work yet. `MCPToolLangChain.from_server()` creates `langchain_core.tools.Tool` objects without the required `func` argument, and `Tool` accepts a single input while these tools take keyword arguments. After `connect()`, `LangChainMCPClient.get_tools()` returns an empty list, because `from_server_url()` stores tool definitions without building tools.
- The `mcptool-server` and `mcptool-inspect` console scripts in `pyproject.toml` point to functions that do not exist. `fastmcp`, OpenTelemetry, and `prometheus-client` are declared dependencies that no code imports.

## Project layout

```
mcptool/
├── __init__.py               # Public exports
├── server.py                 # MCPServer, ToolContext, JSON-RPC dispatch, stdio loop
├── tool.py                   # ToolResult, ToolError, ToolDefinition, validation, argument hashing
├── config.py                 # ServerConfig and from_env()
├── logging_config.py         # setup_logging(), get_logger(), AuditLogger
├── langchain_integration.py  # LangChain adapter (not working yet)
└── examples.py               # Example server with five demo tools
tests/
└── test_server.py            # pytest suite (21 tests)
pyproject.toml                # Packaging metadata, extras, pytest settings
```

## Tests

Clone the repository, install the `dev` extra, and run pytest:

```bash
git clone https://github.com/sujaychandrakoyyalamudi/MCPTool.git
cd MCPTool
pip install -e ".[dev]"
pytest tests/test_server.py
```

`pyproject.toml` adds `-v --cov=mcptool --cov-report=term-missing` to every run, so `pytest-cov` from the `dev` extra is required. The 21 tests cover initialization, tool registration, `tools/list`, `tools/call` (success, unknown tool, invalid arguments), `ToolResult`, JSON-RPC error codes, and `ServerConfig`. Three of them start subprocesses to check that the example server writes only JSON-RPC to stdout and that `setup_logging()` sends logs to stderr in both formats.

## Roadmap (not implemented yet)

- Streamable HTTP transport. `ServerConfig` has `transport`, `host`, and `port` fields, but only stdio exists.
- OAuth 2.1 authorization for HTTP (RFC 8414, RFC 9728, RFC 8707) with PKCE.
- OpenTelemetry tracing with W3C Trace Context. Today each call gets a random UUID as its `trace_id`.
- Prometheus metrics endpoint.
- Kubernetes liveness and readiness probes.
- `tools/list` pagination and `notifications/tools/list_changed`.
- Progress notifications and cancellation. `ToolContext.report_progress()` and `ToolContext.is_cancelled()` exist, but the server never connects them, so they do nothing.
- Enforced approval for tools marked `requires_approval=True`.
- A tamper-evident audit log. The `audit_log_path` setting is unused.
- Working LangChain wrappers (async, with generated Pydantic argument schemas) for local and remote servers, with tests.

## License

MIT. See [LICENSE](LICENSE).
