"""Reviewer role node for the code review workflow.

The Reviewer node examines the focus files and generates detailed
code review comments and suggestions.
"""

from typing import Any, Dict, List
from core.state import ReviewState
from core.llm import LLMProvider
from tools.file_tools import ReadFileTool


async def reviewer_node(
    state: ReviewState,
    llm_provider: LLMProvider,
    workspace_root: str = "."
) -> Dict[str, Any]:
    """Reviewer node: Review focus files and generate comments.
    
    This node reads the focus files, analyzes their content, and generates
    code review comments using the LLM.
    
    Args:
        state: The current ReviewState containing focus_files and pr_diff.
        llm_provider: The LLM provider instance for generating review comments.
        workspace_root: Root directory of the workspace for file reading.
    
    Returns:
        A dictionary with updated state, specifically the identified_issues list.
    """
    try:
        focus_files = state.get("focus_files", [])
        pr_diff = state.get("pr_diff", "")
        
        if not focus_files:
            return {
                "identified_issues": [],
                "metadata": {
                    **state.get("metadata", {}),
                    "reviewer_note": "No focus files to review"
                }
            }
        
        # Initialize file reading tool
        read_tool = ReadFileTool()
        
        # Read contents of focus files
        file_contents = {}
        for file_path in focus_files[:5]:  # Limit to 5 files for MVP
            try:
                result = await read_tool.run(file_path=file_path, max_lines=200)
                if result.get("error"):
                    file_contents[file_path] = f"Error reading file: {result.get('error')}"
                else:
                    file_contents[file_path] = result.get("content", "")
            except Exception as e:
                file_contents[file_path] = f"Error: {str(e)}"
        
        # Build prompt for LLM to generate review comments
        # Truncate each file to 500 chars to avoid token limits
        files_summary = "\n\n".join([
            f"=== File: {path} ===\n{content[:500]}"
            for path, content in file_contents.items()
        ])
        
        # Truncate diff to avoid token limits
        pr_diff_truncated = pr_diff[:1500]
        
        prompt = f"""You are a senior code reviewer. Review the following code files and the Git diff to identify issues, suggest improvements, and provide feedback.

        Git Diff (context):
        {pr_diff_truncated}

        Files to Review:
        {files_summary}

        For each file, identify:
        1. Potential bugs or errors
        2. Code quality issues (readability, maintainability)
        3. Security concerns
        4. Performance issues
        5. Best practice violations
        6. Missing error handling
        7. Type hints or documentation improvements

        Return a JSON array of review comments with this structure:
        [
        {{
            "file": "path/to/file.py",
            "line": 42,
            "severity": "error|warning|info",
            "message": "Description of the issue",
            "suggestion": "Optional suggestion for improvement"
        }}
        ]

        Only return the JSON array, no additional text."""

        # Get LLM response
        response = await llm_provider.generate_structured(
            prompt,
            response_format="json",
            temperature=0.5
        )
        
        # Extract issues from response
        if "error" in response:
            # Fallback: generate a generic review comment
            issues = [{
                "file": focus_files[0] if focus_files else "unknown",
                "line": 0,
                "severity": "warning",
                "message": f"Could not generate detailed review: {response.get('error')}",
                "suggestion": "Please review the code manually"
            }]
        else:
            # Ensure response is a list
            if isinstance(response, list):
                issues = response
            elif isinstance(response, dict) and "issues" in response:
                issues = response["issues"]
            else:
                issues = []
        
        # Validate and clean issues
        validated_issues = []
        for issue in issues:
            if isinstance(issue, dict) and "file" in issue:
                validated_issues.append({
                    "file": issue.get("file", "unknown"),
                    "line": issue.get("line", 0),
                    "severity": issue.get("severity", "info"),
                    "message": issue.get("message", "No message"),
                    "suggestion": issue.get("suggestion", "")
                })
        
        return {
            "identified_issues": validated_issues,
            "metadata": {
                **state.get("metadata", {}),
                "reviewed_files_count": len(file_contents),
                "issues_found": len(validated_issues)
            }
        }
    
    except Exception as e:
        # Error handling: return error issue
        return {
            "identified_issues": [{
                "file": "workflow",
                "line": 0,
                "severity": "error",
                "message": f"Reviewer node error: {str(e)}",
                "suggestion": "Check workflow configuration and file access"
            }],
            "metadata": {
                **state.get("metadata", {}),
                "reviewer_error": str(e)
            }
        }

