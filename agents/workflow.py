"""LangGraph workflow for the code review system.

This module defines the main workflow using LangGraph's StateGraph,
connecting Manager and Reviewer nodes in a sequential pipeline.
"""

from typing import Any, Dict
from langgraph.graph import StateGraph, END
from core.state import ReviewState
from core.llm import LLMProvider
from core.config import Config
from agents.roles.manager import manager_node
from agents.roles.reviewer import reviewer_node


def create_review_workflow(config: Config) -> StateGraph:
    """Create the code review workflow graph.
    
    The workflow follows this structure:
    START -> Manager Node -> Reviewer Node -> END
    
    Args:
        config: Configuration object containing LLM and system settings.
    
    Returns:
        A compiled LangGraph StateGraph ready for execution.
    """
    # Initialize LLM provider
    llm_provider = LLMProvider(config.llm)
    workspace_root = str(config.system.workspace_root)
    
    # Create the graph
    workflow = StateGraph(ReviewState)
    
    # Create async wrapper functions for nodes
    # LangGraph supports async nodes directly, so we can pass the async functions
    # But we need to bind the additional parameters (llm_provider, workspace_root)
    async def manager_wrapper(state: ReviewState) -> Dict[str, Any]:
        """Wrapper for manager node with bound llm_provider."""
        return await manager_node(state, llm_provider)
    
    async def reviewer_wrapper(state: ReviewState) -> Dict[str, Any]:
        """Wrapper for reviewer node with bound parameters."""
        return await reviewer_node(state, llm_provider, workspace_root)
    
    # Add nodes - LangGraph supports async functions directly
    workflow.add_node("manager", manager_wrapper)
    workflow.add_node("reviewer", reviewer_wrapper)
    
    # Define the flow
    workflow.set_entry_point("manager")
    workflow.add_edge("manager", "reviewer")
    workflow.add_edge("reviewer", END)
    
    # Compile the graph
    return workflow.compile()


async def run_review_workflow(
    pr_diff: str,
    repo_map_summary: str,
    config: Config = None
) -> Dict[str, Any]:
    """Run the complete code review workflow.
    
    This function initializes the workflow, builds the RepoMap if needed,
    and executes the review process.
    
    Args:
        pr_diff: The raw Git diff string from the PR.
        repo_map_summary: Summary of the repository structure (from RepoMap).
        config: Optional configuration object. If None, uses default config.
    
    Returns:
        A dictionary containing the final state with review results:
        - focus_files: List of files that were reviewed
        - identified_issues: List of review comments/issues
        - metadata: Additional workflow metadata
    """
    if config is None:
        config = Config.load_default()
    
    # Create workflow
    app = create_review_workflow(config)
    
    # Initialize state
    initial_state: ReviewState = {
        "pr_diff": pr_diff,
        "repo_map_summary": repo_map_summary,
        "focus_files": [],
        "identified_issues": [],
        "metadata": {
            "workflow_version": "mvp",
            "config_provider": config.llm.provider
        }
    }
    
    # Run the workflow
    try:
        final_state = await app.ainvoke(initial_state)
        return final_state
    except Exception as e:
        # Error handling: return error state
        return {
            **initial_state,
            "identified_issues": [{
                "file": "workflow",
                "line": 0,
                "severity": "error",
                "message": f"Workflow execution error: {str(e)}",
                "suggestion": "Check workflow configuration and dependencies"
            }],
            "metadata": {
                **initial_state.get("metadata", {}),
                "workflow_error": str(e)
            }
        }

