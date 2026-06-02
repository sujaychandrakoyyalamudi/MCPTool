"""Configuration and settings for MCPTool server."""

import os
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class ServerConfig:
    """Configuration for MCPTool server.
    
    Attributes:
        name: Server name for discovery and metadata
        version: Server version string
        host: Host address for HTTP transport (default: localhost)
        port: Port for HTTP transport (default: 8080)
        transport: Transport mode - 'stdio' or 'http' (default: stdio)
        protocol_version: MCP protocol version to use (default: 2025-11-25)
        log_level: Logging level (default: INFO)
        enable_auth: Enable OAuth authorization for remote servers
        auth_issuer: OAuth issuer URL for remote authorization
        auth_client_id: OAuth client ID
        auth_client_secret: OAuth client secret
        enable_tracing: Enable OpenTelemetry tracing
        otlp_endpoint: OTLP endpoint for traces (default: http://localhost:4317)
        enable_metrics: Enable Prometheus metrics
        metrics_port: Port for metrics endpoint (default: 9090)
        max_concurrent_calls: Maximum concurrent tool calls (default: 100)
        request_timeout: Request timeout in seconds (default: 60)
        enable_audit_logging: Enable audit logging for mutating operations
        audit_log_path: Path for audit log file
    """
    
    name: str = "mcptool-server"
    version: str = "1.0.0"
    host: str = "localhost"
    port: int = 8080
    transport: str = "stdio"  # 'stdio' or 'http'
    protocol_version: str = "2025-11-25"
    log_level: str = "INFO"
    enable_auth: bool = False
    auth_issuer: Optional[str] = None
    auth_client_id: Optional[str] = None
    auth_client_secret: Optional[str] = None
    enable_tracing: bool = False
    otlp_endpoint: str = "http://localhost:4317"
    enable_metrics: bool = True
    metrics_port: int = 9090
    max_concurrent_calls: int = 100
    request_timeout: int = 60
    enable_audit_logging: bool = True
    audit_log_path: Optional[str] = None
    
    @classmethod
    def from_env(cls) -> "ServerConfig":
        """Create configuration from environment variables.
        
        Environment variables:
            MCPTOOL_NAME: Server name
            MCPTOOL_VERSION: Server version
            MCPTOOL_HOST: Host address
            MCPTOOL_PORT: Port number
            MCPTOOL_TRANSPORT: Transport mode
            MCPTOOL_LOG_LEVEL: Logging level
            MCPTOOL_ENABLE_AUTH: Enable auth (true/false)
            MCPTOOL_AUTH_ISSUER: OAuth issuer
            MCPTOOL_AUTH_CLIENT_ID: OAuth client ID
            MCPTOOL_AUTH_CLIENT_SECRET: OAuth client secret
            MCPTOOL_ENABLE_TRACING: Enable tracing (true/false)
            MCPTOOL_OTLP_ENDPOINT: OTLP endpoint
            MCPTOOL_ENABLE_METRICS: Enable metrics (true/false)
            MCPTOOL_METRICS_PORT: Metrics port
            MCPTOOL_MAX_CONCURRENT_CALLS: Max concurrent calls
            MCPTOOL_REQUEST_TIMEOUT: Request timeout
            MCPTOOL_ENABLE_AUDIT_LOGGING: Enable audit logging (true/false)
            MCPTOOL_AUDIT_LOG_PATH: Audit log path
        """
        def get_bool(name: str, default: bool) -> bool:
            value = os.environ.get(name)
            if value is None:
                return default
            return value.lower() in ("true", "1", "yes", "on")
        
        def get_int(name: str, default: int) -> int:
            value = os.environ.get(name)
            if value is None:
                return default
            return int(value)
        
        return cls(
            name=os.environ.get("MCPTOOL_NAME", cls.name),
            version=os.environ.get("MCPTOOL_VERSION", cls.version),
            host=os.environ.get("MCPTOOL_HOST", cls.host),
            port=get_int("MCPTOOL_PORT", cls.port),
            transport=os.environ.get("MCPTOOL_TRANSPORT", cls.transport),
            log_level=os.environ.get("MCPTOOL_LOG_LEVEL", cls.log_level),
            enable_auth=get_bool("MCPTOOL_ENABLE_AUTH", cls.enable_auth),
            auth_issuer=os.environ.get("MCPTOOL_AUTH_ISSUER"),
            auth_client_id=os.environ.get("MCPTOOL_AUTH_CLIENT_ID"),
            auth_client_secret=os.environ.get("MCPTOOL_AUTH_CLIENT_SECRET"),
            enable_tracing=get_bool("MCPTOOL_ENABLE_TRACING", cls.enable_tracing),
            otlp_endpoint=os.environ.get("MCPTOOL_OTLP_ENDPOINT", cls.otlp_endpoint),
            enable_metrics=get_bool("MCPTOOL_ENABLE_METRICS", cls.enable_metrics),
            metrics_port=get_int("MCPTOOL_METRICS_PORT", cls.metrics_port),
            max_concurrent_calls=get_int("MCPTOOL_MAX_CONCURRENT_CALLS", cls.max_concurrent_calls),
            request_timeout=get_int("MCPTOOL_REQUEST_TIMEOUT", cls.request_timeout),
            enable_audit_logging=get_bool("MCPTOOL_ENABLE_AUDIT_LOGGING", cls.enable_audit_logging),
            audit_log_path=os.environ.get("MCPTOOL_AUDIT_LOG_PATH"),
        )
    
    def validate(self) -> None:
        """Validate configuration.
        
        Raises:
            ValueError: If configuration is invalid
        """
        if self.transport not in ("stdio", "http"):
            raise ValueError(f"Invalid transport: {self.transport}. Must be 'stdio' or 'http'")
        
        if self.port < 1 or self.port > 65535:
            raise ValueError(f"Invalid port: {self.port}. Must be between 1 and 65535")
        
        if self.enable_auth:
            if not self.auth_issuer:
                raise ValueError("auth_issuer is required when enable_auth is True")
            if not self.auth_client_id:
                raise ValueError("auth_client_id is required when enable_auth is True")
        
        if self.max_concurrent_calls < 1:
            raise ValueError("max_concurrent_calls must be at least 1")
        
        if self.request_timeout < 1:
            raise ValueError("request_timeout must be at least 1 second")
