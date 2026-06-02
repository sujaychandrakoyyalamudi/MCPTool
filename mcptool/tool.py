"""Tool definitions and result handling for MCPTool."""

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Type

from pydantic import BaseModel, create_model


@dataclass
class ToolResult:
    """Result of a tool execution.
    
    Attributes:
        content: List of content items (text, image, resource, etc.)
        structured_content: Machine-readable structured data
        is_error: Whether this result represents an error
        progress: Optional progress information (0-100)
    """
    
    content: List[Dict[str, Any]] = field(default_factory=list)
    structured_content: Optional[Dict[str, Any]] = None
    is_error: bool = False
    progress: Optional[float] = None
    
    @classmethod
    def success(
        cls,
        structured_content: Dict[str, Any],
        text_fallback: Optional[str] = None,
    ) -> "ToolResult":
        """Create a successful tool result.
        
        Args:
            structured_content: Machine-readable result data
            text_fallback: Optional text representation for backward compatibility
        
        Returns:
            A ToolResult with is_error=False
        """
        content = []
        if text_fallback:
            content.append({"type": "text", "text": text_fallback})
        else:
            # Auto-generate text fallback from structured content
            content.append({
                "type": "text",
                "text": json.dumps(structured_content),
            })
        
        return cls(
            content=content,
            structured_content=structured_content,
            is_error=False,
        )
    
    @classmethod
    def error(
        cls,
        message: str,
        error_code: Optional[str] = None,
    ) -> "ToolResult":
        """Create an error tool result.
        
        Args:
            message: Error message
            error_code: Optional error code for programmatic handling
        
        Returns:
            A ToolResult with is_error=True
        """
        content = [{"type": "text", "text": f"Error: {message}"}]
        structured = {"error": message}
        if error_code:
            structured["error_code"] = error_code
        
        return cls(
            content=content,
            structured_content=structured,
            is_error=True,
        )
    
    def to_mcp_response(self) -> Dict[str, Any]:
        """Convert to MCP tools/call response format.
        
        Returns:
            Dictionary suitable for MCP tools/call response
        """
        response = {
            "content": self.content,
            "isError": self.is_error,
        }
        if self.structured_content is not None:
            response["structuredContent"] = self.structured_content
        return response


class ToolError(Exception):
    """Exception raised by tools during execution.
    
    Attributes:
        message: Error message
        error_code: Optional error code
        details: Additional error details
    """
    
    def __init__(
        self,
        message: str,
        error_code: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
    ):
        self.message = message
        self.error_code = error_code
        self.details = details or {}
        super().__init__(message)
    
    def to_result(self) -> ToolResult:
        """Convert to ToolResult.
        
        Returns:
            ToolResult representing this error
        """
        return ToolResult.error(self.message, self.error_code)


@dataclass
class ToolDefinition:
    """Definition of an MCP tool.
    
    Attributes:
        name: Tool identifier (must be unique within server)
        title: Human-readable title
        description: Detailed description for LLM discovery
        input_schema: JSON Schema for tool arguments
        output_schema: JSON Schema for tool output (optional)
        icons: Optional icon metadata for UI display
        annotations: Optional annotations about tool behavior
        risk_tier: Risk classification (read_only, mutating, sensitive)
        requires_approval: Whether human approval is required
    """
    
    name: str
    title: str
    description: str
    input_schema: Dict[str, Any]
    output_schema: Optional[Dict[str, Any]] = None
    icons: Optional[List[Dict[str, str]]] = None
    annotations: Optional[Dict[str, Any]] = None
    risk_tier: str = "read_only"  # read_only, mutating, sensitive
    requires_approval: bool = False
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to MCP tools/list format.
        
        Returns:
            Dictionary suitable for MCP tools/list response
        """
        result = {
            "name": self.name,
            "title": self.title,
            "description": self.description,
            "inputSchema": self.input_schema,
        }
        
        if self.output_schema:
            result["outputSchema"] = self.output_schema
        
        if self.icons:
            result["icons"] = self.icons
        
        if self.annotations:
            result["annotations"] = self.annotations
        
        return result
    
    @classmethod
    def from_pydantic(
        cls,
        name: str,
        title: str,
        description: str,
        input_model: Type[BaseModel],
        output_model: Optional[Type[BaseModel]] = None,
        **kwargs,
    ) -> "ToolDefinition":
        """Create tool definition from Pydantic models.
        
        Args:
            name: Tool identifier
            title: Human-readable title
            description: Tool description
            input_model: Pydantic model for input validation
            output_model: Optional Pydantic model for output schema
            **kwargs: Additional ToolDefinition arguments
        
        Returns:
            Configured ToolDefinition instance
        """
        # Generate JSON Schema from Pydantic model
        input_schema = input_model.model_json_schema()
        
        # Ensure $schema is set to JSON Schema 2020-12 (MCP default)
        if "$schema" not in input_schema:
            input_schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
        
        output_schema = None
        if output_model:
            output_schema = output_model.model_json_schema()
            if "$schema" not in output_schema:
                output_schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
        
        return cls(
            name=name,
            title=title,
            description=description,
            input_schema=input_schema,
            output_schema=output_schema,
            **kwargs,
        )


def hash_arguments(args: Dict[str, Any]) -> str:
    """Generate SHA256 hash of tool arguments for audit logging.
    
    Args:
        args: Tool arguments dictionary
    
    Returns:
        SHA256 hash as hex string
    """
    # Sort keys for consistent hashing
    canonical = json.dumps(args, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


def validate_against_schema(
    data: Dict[str, Any],
    schema: Dict[str, Any],
) -> tuple[bool, Optional[str]]:
    """Validate data against JSON Schema.
    
    Args:
        data: Data to validate
        schema: JSON Schema
    
    Returns:
        Tuple of (is_valid, error_message)
    """
    try:
        from jsonschema import validate, ValidationError
        
        try:
            validate(instance=data, schema=schema)
            return True, None
        except ValidationError as e:
            return False, str(e.message)
    except ImportError:
        # Fallback: basic validation without jsonschema library
        if not isinstance(data, dict):
            return False, "Data must be an object"
        
        # Check required fields
        required = schema.get("required", [])
        properties = schema.get("properties", {})
        
        for field in required:
            if field not in data:
                return False, f"Missing required field: {field}"
        
        # Basic type checking
        for key, value in data.items():
            if key in properties:
                expected_type = properties[key].get("type")
                if expected_type == "string" and not isinstance(value, str):
                    return False, f"Field '{key}' must be a string"
                elif expected_type == "integer" and not isinstance(value, int):
                    return False, f"Field '{key}' must be an integer"
                elif expected_type == "number" and not isinstance(value, (int, float)):
                    return False, f"Field '{key}' must be a number"
                elif expected_type == "boolean" and not isinstance(value, bool):
                    return False, f"Field '{key}' must be a boolean"
                elif expected_type == "array" and not isinstance(value, list):
                    return False, f"Field '{key}' must be an array"
        
        return True, None
