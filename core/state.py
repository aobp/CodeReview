"""State definitions for the LangGraph workflow.

This module defines the ReviewState TypedDict that is passed between nodes
in the LangGraph workflow.
"""

from typing import TypedDict, List, Dict, Any, Optional


class ReviewState(TypedDict, total=False):
    """State object passed through the LangGraph workflow.
    
    This TypedDict defines all possible state keys that can be used in the
    code review workflow. Keys are optional (total=False) to allow incremental
    state updates.
    
    Attributes:
        pr_diff: The raw Git diff string from the PR.
        repo_map_summary: A summary of the repository structure (from RepoMap asset).
        focus_files: List of file paths that the manager identified as needing review.
        identified_issues: List of review comments/issues found by the reviewer.
        worklist: Optional worklist of tasks for the agent (for future extensibility).
        metadata: Optional dictionary for storing additional workflow metadata.
    """
    
    pr_diff: str
    repo_map_summary: str
    focus_files: List[str]
    identified_issues: List[Dict[str, Any]]
    worklist: Optional[List[Dict[str, Any]]]
    metadata: Optional[Dict[str, Any]]

