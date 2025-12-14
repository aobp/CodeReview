"""Manager role node for the code review workflow.

The Manager node analyzes the PR diff and repository map to identify
which files should be prioritized for review.
"""

import re
from typing import Any, Dict, List
from core.state import ReviewState
from core.llm import LLMProvider


def extract_files_from_diff(diff: str) -> List[str]:
    """Extract file paths from a Git diff string.
    
    Args:
        diff: The raw Git diff string.
    
    Returns:
        List of file paths mentioned in the diff.
    """
    # Pattern to match "diff --git a/path b/path" or "--- a/path" or "+++ b/path"
    file_patterns = [
        r'^diff --git a/(.+?) b/(.+?)$',
        r'^--- a/(.+?)$',
        r'^\+\+\+ b/(.+?)$',
    ]
    
    files = set()
    for line in diff.split('\n'):
        for pattern in file_patterns:
            match = re.match(pattern, line)
            if match:
                # Extract the file path (remove /dev/null and similar)
                file_path = match.group(1) if match.lastindex >= 1 else match.group(0)
                if file_path and file_path != '/dev/null':
                    files.add(file_path)
    
    return sorted(list(files))


async def manager_node(state: ReviewState, llm_provider: LLMProvider) -> Dict[str, Any]:
    """Manager node: Analyze diff and repo map to identify focus files.
    
    This node receives the PR diff and repository map, then uses the LLM
    to determine which files should be prioritized for review.
    
    Args:
        state: The current ReviewState containing pr_diff and repo_map_summary.
        llm_provider: The LLM provider instance for generating analysis.
    
    Returns:
        A dictionary with updated state, specifically the focus_files list.
    """
    try:
        pr_diff = state.get("pr_diff", "")
        repo_map_summary = state.get("repo_map_summary", "")
        
        # Extract files from diff as a baseline
        diff_files = extract_files_from_diff(pr_diff)
        
        # Build prompt for LLM to prioritize files
        # Truncate inputs to avoid token limits
        pr_diff_truncated = pr_diff[:2000]
        repo_map_truncated = repo_map_summary[:1000]
        diff_files_preview = ', '.join(diff_files[:10])
        
        prompt = f"""You are a code review manager. Analyze the following Git diff and repository structure to identify which files should be prioritized for code review.

        Git Diff:
        {pr_diff_truncated}

        Repository Structure:
        {repo_map_truncated}

        Files changed in diff: {diff_files_preview}

        Based on the diff and repository structure, identify the most important files that need review. Consider:
        1. Files with significant changes
        2. Core business logic files
        3. Files that might affect other parts of the system
        4. Security-sensitive files

        Return a JSON object with this structure:
        {{
        "focus_files": ["path/to/file1.py", "path/to/file2.js"],
        "reasoning": "Brief explanation of why these files were selected"
        }}

        Only return the JSON, no additional text."""

        # Get LLM response
        response = await llm_provider.generate_structured(
            prompt,
            response_format="json",
            temperature=0.3  # Lower temperature for more deterministic results
        )
        
        # Extract focus files from response
        if "error" in response:
            # Fallback: use all files from diff
            focus_files = diff_files[:5]  # Limit to 5 files as fallback
            reasoning = f"LLM error: {response.get('error')}. Using files from diff as fallback."
        else:
            focus_files = response.get("focus_files", diff_files[:5])
            reasoning = response.get("reasoning", "Files selected based on diff analysis")
        
        # Ensure focus_files is a list of strings
        if not isinstance(focus_files, list):
            focus_files = diff_files[:5]
        
        # Limit to reasonable number of files
        focus_files = focus_files[:10]
        
        return {
            "focus_files": focus_files,
            "metadata": {
                **state.get("metadata", {}),
                "manager_reasoning": reasoning,
                "diff_files_count": len(diff_files),
                "selected_files_count": len(focus_files)
            }
        }
    
    except Exception as e:
        # Error handling: return fallback focus files
        pr_diff = state.get("pr_diff", "")
        diff_files = extract_files_from_diff(pr_diff)
        
        return {
            "focus_files": diff_files[:5],  # Fallback to first 5 files from diff
            "identified_issues": [{
                "severity": "error",
                "message": f"Manager node error: {str(e)}",
                "file": "workflow",
                "line": 0
            }],
            "metadata": {
                **state.get("metadata", {}),
                "manager_error": str(e)
            }
        }

