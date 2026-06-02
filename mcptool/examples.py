"""Example MCP server with sample tools for demonstration."""

import asyncio
import httpx
from typing import Any, Dict, List

from mcptool import MCPServer, ToolContext, ToolResult, ToolError, ServerConfig
from mcptool.logging_config import setup_logging


def create_example_server() -> MCPServer:
    """Create an example MCP server with sample tools.
    
    Returns:
        Configured MCPServer instance with example tools
    """
    config = ServerConfig.from_env()
    server = MCPServer(
        name="example-tools",
        version="1.0.0",
        config=config,
    )
    
    @server.tool(
        description="Search for issues in a GitHub repository by query, labels, and state.",
        risk_tier="read_only",
    )
    async def search_issues(
        ctx: ToolContext,
        repo: str,
        query: str,
        state: str = "open",
        labels: List[str] = None,
        limit: int = 20,
    ) -> ToolResult:
        """Search for issues in a GitHub repository.
        
        Args:
            ctx: Tool execution context
            repo: Repository in format owner/name
            query: Search query string
            state: Issue state filter (open, closed, all)
            labels: List of label filters
            limit: Maximum number of results (1-100)
        
        Returns:
            ToolResult with issue list
        """
        labels = labels or []
        
        # Validate limit
        if limit < 1:
            limit = 1
        elif limit > 100:
            limit = 100
        
        # Simulate GitHub API call (replace with actual API call)
        # In production, you would use the GitHub API with proper authentication
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                # Build search query
                search_parts = [query, f"repo:{repo}", f"is:issue", f"is:{state}"]
                for label in labels:
                    search_parts.append(f"label:{label}")
                
                search_query = " ".join(search_parts)
                
                # Call GitHub API
                response = await client.get(
                    "https://api.github.com/search/issues",
                    params={
                        "q": search_query,
                        "per_page": limit,
                        "sort": "updated",
                        "order": "desc",
                    },
                    headers={
                        "Accept": "application/vnd.github.v3+json",
                        "User-Agent": "MCPTool-Example/1.0.0",
                    },
                )
                
                if response.status_code == 401:
                    # Return mock data if not authenticated
                    issues = _generate_mock_issues(repo, query, limit)
                elif response.status_code != 200:
                    raise ToolError(
                        f"GitHub API error: {response.status_code}",
                        error_code="API_ERROR",
                    )
                else:
                    data = response.json()
                    issues = [
                        {
                            "id": item["id"],
                            "title": item["title"],
                            "url": item["html_url"],
                            "state": item["state"],
                            "labels": [l["name"] for l in item.get("labels", [])],
                        }
                        for item in data.get("items", [])
                    ]
            
            return ToolResult.success(
                structured_content={
                    "items": issues,
                    "total": len(issues),
                    "repository": repo,
                    "query": query,
                },
                text_fallback=f"Found {len(issues)} issues in {repo}",
            )
        
        except httpx.HTTPError as e:
            # Return mock data on network errors for demo purposes
            issues = _generate_mock_issues(repo, query, limit)
            return ToolResult.success(
                structured_content={
                    "items": issues,
                    "total": len(issues),
                    "repository": repo,
                    "query": query,
                    "note": "Mock data (API unavailable)",
                },
                text_fallback=f"Found {len(issues)} issues in {repo} (mock data)",
            )
    
    @server.tool(
        description="Get details of a specific issue by number.",
        risk_tier="read_only",
    )
    async def get_issue(
        ctx: ToolContext,
        repo: str,
        issue_number: int,
    ) -> ToolResult:
        """Get details of a specific issue.
        
        Args:
            ctx: Tool execution context
            repo: Repository in format owner/name
            issue_number: Issue number
        
        Returns:
            ToolResult with issue details
        """
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(
                    f"https://api.github.com/repos/{repo}/issues/{issue_number}",
                    headers={
                        "Accept": "application/vnd.github.v3+json",
                        "User-Agent": "MCPTool-Example/1.0.0",
                    },
                )
                
                if response.status_code == 404:
                    raise ToolError(
                        f"Issue #{issue_number} not found in {repo}",
                        error_code="NOT_FOUND",
                    )
                elif response.status_code != 200:
                    raise ToolError(
                        f"GitHub API error: {response.status_code}",
                        error_code="API_ERROR",
                    )
                
                data = response.json()
                issue = {
                    "id": data["id"],
                    "number": data["number"],
                    "title": data["title"],
                    "body": data.get("body", ""),
                    "state": data["state"],
                    "url": data["html_url"],
                    "labels": [l["name"] for l in data.get("labels", [])],
                    "created_at": data["created_at"],
                    "updated_at": data["updated_at"],
                }
            
            return ToolResult.success(
                structured_content=issue,
                text_fallback=f"Issue #{issue['number']}: {issue['title']}",
            )
        
        except httpx.HTTPError:
            # Return mock data
            issue = {
                "id": issue_number,
                "number": issue_number,
                "title": f"Example Issue #{issue_number}",
                "body": "This is mock data for demonstration purposes.",
                "state": "open",
                "url": f"https://github.com/{repo}/issues/{issue_number}",
                "labels": ["example"],
                "created_at": "2024-01-01T00:00:00Z",
                "updated_at": "2024-01-01T00:00:00Z",
            }
            
            return ToolResult.success(
                structured_content=issue,
                text_fallback=f"Issue #{issue_number}: {issue['title']} (mock data)",
            )
    
    @server.tool(
        description="Add a comment to an issue. This is a mutating operation.",
        risk_tier="mutating",
        requires_approval=True,
    )
    async def add_issue_comment(
        ctx: ToolContext,
        repo: str,
        issue_number: int,
        body: str,
    ) -> ToolResult:
        """Add a comment to an issue.
        
        Args:
            ctx: Tool execution context
            repo: Repository in format owner/name
            issue_number: Issue number
            body: Comment text
        
        Returns:
            ToolResult with comment details
        """
        # In production, this would make a POST request to GitHub API
        # For safety, we'll return a simulated response
        comment = {
            "id": 12345,
            "body": body,
            "issue_number": issue_number,
            "repository": repo,
            "created_at": "2024-01-01T00:00:00Z",
            "note": "Comment simulation (actual API call disabled for safety)",
        }
        
        return ToolResult.success(
            structured_content=comment,
            text_fallback=f"Comment added to issue #{issue_number} in {repo}",
        )
    
    @server.tool(
        description="Execute a simple calculation. Useful for testing.",
        risk_tier="read_only",
    )
    async def calculate(
        ctx: ToolContext,
        expression: str,
    ) -> ToolResult:
        """Evaluate a mathematical expression safely.
        
        Args:
            ctx: Tool execution context
            expression: Mathematical expression to evaluate
        
        Returns:
            ToolResult with calculation result
        """
        try:
            # Safe evaluation of simple math expressions
            allowed_chars = set("0123456789+-*/.() ")
            if not all(c in allowed_chars for c in expression):
                raise ToolError(
                    "Expression contains invalid characters",
                    error_code="INVALID_EXPRESSION",
                )
            
            result = eval(expression, {"__builtins__": {}}, {})
            
            return ToolResult.success(
                structured_content={
                    "expression": expression,
                    "result": result,
                },
                text_fallback=f"{expression} = {result}",
            )
        
        except Exception as e:
            raise ToolError(
                f"Calculation error: {str(e)}",
                error_code="CALCULATION_ERROR",
            )
    
    @server.tool(
        description="Get weather information for a location.",
        risk_tier="read_only",
    )
    async def get_weather(
        ctx: ToolContext,
        location: str,
        units: str = "metric",
    ) -> ToolResult:
        """Get current weather for a location.
        
        Args:
            ctx: Tool execution context
            location: City name or coordinates
            units: Temperature units (metric, imperial, kelvin)
        
        Returns:
            ToolResult with weather data
        """
        # Mock weather data for demonstration
        # In production, integrate with OpenWeatherMap or similar
        import random
        
        weather_conditions = ["Clear", "Clouds", "Rain", "Snow", "Mist"]
        condition = random.choice(weather_conditions)
        
        if units == "imperial":
            temp = random.randint(32, 95)
            unit_symbol = "°F"
        elif units == "kelvin":
            temp = random.randint(233, 308)
            unit_symbol = "K"
        else:
            temp = random.randint(0, 35)
            unit_symbol = "°C"
        
        weather = {
            "location": location,
            "temperature": temp,
            "unit": units,
            "unit_symbol": unit_symbol,
            "condition": condition,
            "humidity": random.randint(30, 90),
            "wind_speed": random.randint(0, 30),
            "note": "Mock data for demonstration",
        }
        
        return ToolResult.success(
            structured_content=weather,
            text_fallback=f"Weather in {location}: {temp}{unit_symbol}, {condition}",
        )
    
    return server


def _generate_mock_issues(repo: str, query: str, limit: int) -> List[Dict[str, Any]]:
    """Generate mock issues for demonstration when API is unavailable.
    
    Args:
        repo: Repository name
        query: Search query
        limit: Number of issues to generate
    
    Returns:
        List of mock issue dictionaries
    """
    titles = [
        "Bug in authentication flow",
        "Feature request: Add dark mode",
        "Documentation update needed",
        "Performance improvement for large datasets",
        "Fix typo in README",
        "Add unit tests for API module",
        "Memory leak in background worker",
        "Update dependencies to latest versions",
        "Improve error messages",
        "Add support for webhooks",
    ]
    
    issues = []
    for i in range(min(limit, len(titles))):
        issues.append({
            "id": 1000 + i,
            "title": titles[i],
            "url": f"https://github.com/{repo}/issues/{100 + i}",
            "state": "open" if i % 3 != 0 else "closed",
            "labels": ["bug" if "Bug" in titles[i] else "enhancement"],
        })
    
    return issues


def main():
    """Main entry point for running the example server."""
    import sys
    
    server = create_example_server()
    
    print("Example MCP Server")
    print("==================")
    print(f"Server name: {server.name}")
    print(f"Version: {server.version}")
    print(f"Transport: {server.config.transport}")
    print()
    print("Available tools:")
    for tool_name, tool_def in server._tools.items():
        print(f"  - {tool_name}: {tool_def.description[:60]}...")
    print()
    print("Starting server with stdio transport...")
    print("(Press Ctrl+C to stop)")
    print()
    
    try:
        asyncio.run(server.run_stdio())
    except KeyboardInterrupt:
        print("\nServer stopped.")
        sys.exit(0)


if __name__ == "__main__":
    main()
