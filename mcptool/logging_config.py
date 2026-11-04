"""Structured logging configuration for MCPTool."""

import logging
import sys
from typing import Any, Dict, Optional

import structlog

# MCP stdio clients read JSON-RPC messages from stdout, so logs must go to stderr.
# Tools log when they are registered, before run_stdio() calls setup_logging(),
# and structlog's defaults print to stdout. Redirect those defaults to stderr
# unless the application has already configured structlog.
if not structlog.is_configured():
    structlog.configure(logger_factory=structlog.PrintLoggerFactory(file=sys.stderr))


def setup_logging(
    level: str = "INFO",
    format_type: str = "json",
    service_name: str = "mcptool-server",
) -> None:
    """Setup structured logging for the MCPTool server.
    
    Args:
        level: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        format_type: Log format - 'json' or 'console'
        service_name: Service name to include in log records
    
    This configures both standard library logging and structlog for consistent
    structured logging across the application. Both write to stderr, because
    stdio clients read JSON-RPC messages from stdout.
    """
    # Configure standard library logging
    log_level = getattr(logging, level.upper(), logging.INFO)
    
    if format_type == "json":
        # JSON formatter for production
        handler = logging.StreamHandler(sys.stderr)
        handler.setFormatter(logging.Formatter("%(message)s"))
    else:
        # Console formatter for development
        handler = logging.StreamHandler(sys.stderr)
        handler.setFormatter(logging.Formatter(
            "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
        ))
    
    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)
    root_logger.addHandler(handler)
    
    # Configure structlog
    processors = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.StackInfoRenderer(),
    ]
    
    if format_type == "json":
        processors.append(structlog.processors.JSONRenderer())
    else:
        processors.append(structlog.dev.ConsoleRenderer())
    
    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(log_level),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(file=sys.stderr),
        cache_logger_on_first_use=True,
    )
    
    # Add service name to all logs
    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(service=service_name)


def get_logger(name: str) -> structlog.BoundLogger:
    """Get a structured logger instance.
    
    Args:
        name: Logger name (typically __name__ of the module)
    
    Returns:
        A configured structlog BoundLogger instance
    """
    return structlog.get_logger(name)


class AuditLogger:
    """Audit logger for recording security-relevant events.
    
    This provides immutable audit trails for mutating operations,
    approvals, denials, and scope usage as required by MCP security guidance.
    """
    
    def __init__(self, logger: Optional[structlog.BoundLogger] = None):
        self.logger = logger or get_logger("audit")
    
    def log_tool_call(
        self,
        tool_name: str,
        request_id: int,
        trace_id: str,
        client_info: Dict[str, str],
        server_info: Dict[str, str],
        args_hash: str,
        auth_subject: str,
        auth_scopes: list,
        result_status: str,
        latency_ms: int,
        is_error: bool,
        risk_tier: str = "read_only",
        approval_required: bool = False,
        approval_status: str = "not_required",
        data_labels: Optional[list] = None,
        pii_detected: bool = False,
    ) -> None:
        """Log a tool call audit event.
        
        Args:
            tool_name: Name of the tool that was called
            request_id: JSON-RPC request ID
            trace_id: W3C trace context ID
            client_info: Client metadata (name, version, user_id)
            server_info: Server metadata (name, version)
            args_hash: SHA256 hash of tool arguments
            auth_subject: Authenticated subject identifier
            auth_scopes: OAuth scopes used
            result_status: Result status (ok, error, denied)
            latency_ms: Call latency in milliseconds
            is_error: Whether the call resulted in an error
            risk_tier: Tool risk tier (read_only, mutating, sensitive)
            approval_required: Whether approval was required
            approval_status: Approval status (not_required, approved, denied, pending)
            data_labels: Data classification labels
            pii_detected: Whether PII was detected in the operation
        """
        event = {
            "event_type": "mcp.tool_call.completed",
            "tool": {
                "name": tool_name,
                "risk_tier": risk_tier,
                "args_hash": args_hash,
            },
            "request_id": request_id,
            "trace_id": trace_id,
            "client": client_info,
            "server": server_info,
            "auth": {
                "subject": auth_subject,
                "scopes": auth_scopes,
            },
            "approval": {
                "required": approval_required,
                "status": approval_status,
            },
            "result": {
                "status": result_status,
                "latency_ms": latency_ms,
                "is_error": is_error,
            },
            "governance": {
                "data_labels": data_labels or ["internal"],
                "pii_detected": pii_detected,
                "retention_class": "30d",
            },
        }
        
        self.logger.info("tool_call_audit", **event)
    
    def log_auth_failure(
        self,
        reason: str,
        client_info: Dict[str, str],
        requested_scopes: list,
    ) -> None:
        """Log an authentication/authorization failure.
        
        Args:
            reason: Failure reason
            client_info: Client metadata
            requested_scopes: Scopes that were requested
        """
        self.logger.warning(
            "auth_failure",
            reason=reason,
            client=client_info,
            requested_scopes=requested_scopes,
        )
    
    def log_policy_violation(
        self,
        policy_name: str,
        violation_type: str,
        details: Dict[str, Any],
        trace_id: str,
    ) -> None:
        """Log a policy violation event.
        
        Args:
            policy_name: Name of the violated policy
            violation_type: Type of violation
            details: Additional violation details
            trace_id: W3C trace context ID
        """
        self.logger.error(
            "policy_violation",
            policy_name=policy_name,
            violation_type=violation_type,
            details=details,
            trace_id=trace_id,
        )
