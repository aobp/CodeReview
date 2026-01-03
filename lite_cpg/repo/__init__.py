"""Repository management and scanning utilities.

This module provides functionality for scanning, indexing, and managing
code repositories, including version tracking and file discovery.
"""

from .scan import RepoScanConfig, scan_repo
from .versioning import repo_fingerprint, content_hash

__all__ = [
    "RepoScanConfig",
    "scan_repo",
    "repo_fingerprint",
    "content_hash",
]
