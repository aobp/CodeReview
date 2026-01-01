"""Python syntax checker using Ruff.

This module implements a syntax checker for Python files using Ruff,
a fast Python linter written in Rust.
"""

import json
import shutil
import subprocess
from pathlib import Path
from typing import List

from external_tools.syntax_checker.base import BaseSyntaxChecker, LintError


class PythonRuffChecker(BaseSyntaxChecker):
    """Syntax checker for Python files using Ruff.
    
    This checker uses the `ruff check` command to analyze Python files
    and report linting errors. It gracefully handles cases where Ruff
    is not installed or files don't exist.
    """
    
    def __init__(self):
        """Initialize the Ruff checker."""
        self._ruff_available = self._check_ruff_available()
    
    def _check_ruff_available(self) -> bool:
        """Check if ruff command is available in PATH.
        
        Returns:
            True if ruff is available, False otherwise.
        """
        return shutil.which("ruff") is not None
    
    async def check(
        self,
        repo_path: Path,
        files: List[str]
    ) -> List[LintError]:
        """Run Ruff on the specified Python files.
        
        Args:
            repo_path: Root path of the repository.
            files: List of file paths relative to repo_path to check.
        
        Returns:
            A list of LintError objects found by Ruff. Returns empty list
            if Ruff is not available, if no Python files are found, or if
            no errors are detected.
        """
        if not self._ruff_available:
            print("  ⚠️  Warning: Ruff is not installed. Python syntax checking will be skipped.")
            print("     Install Ruff with: pip install ruff")
            return []
        
        # Filter to only Python files and existing files
        python_files = [
            f for f in files
            if f.endswith((".py", ".pyi"))
        ]
        
        if not python_files:
            return []
        
        # Get existing file paths
        existing_files = self._filter_existing_files(repo_path, python_files)
        
        if not existing_files:
            # If using --diff-file mode, files might not exist locally
            # Return empty list gracefully
            return []
        
        # Build ruff command with ADC (Agent-Defined Config) strategy:
        # --isolated: Ignore user's pyproject.toml configuration
        # --select=E9,F,B,PLE: Only select critical error categories
        #   - E9: Syntax Errors (must fix)
        #   - F: Pyflakes (logic errors, e.g., undefined variables)
        #   - B: Flake8-Bugbear (common potential bugs)
        #   - PLE: Pylint Error (serious error subset)
        # --ignore=E501,F401: Explicitly ignore style issues
        #   - E501: Line too long (style issue, LLM doesn't care)
        #   - F401: Unused imports (unless causing logic issues, usually noise)
        # --output-format=json: JSON output format
        # Use relative paths from repo_path
        relative_paths = [str(f.relative_to(repo_path)) for f in existing_files]
        
        try:
            cmd = [
                "ruff",
                "check",
                "--isolated",  # Ignore user's pyproject.toml
                "--select=E9,F,B,PLE",  # Only critical errors
                "--ignore=E501,F401",  # Ignore style issues
                "--output-format=json",
                *relative_paths
            ]
            
            result = subprocess.run(
                cmd,
                cwd=repo_path,
                capture_output=True,
                text=True,
                check=False,  # Don't raise on non-zero exit (ruff returns non-zero if errors found)
                encoding="utf-8"
            )
            
            # Ruff returns non-zero exit code if errors are found, which is expected
            # We only care about the JSON output
            if result.returncode not in [0, 1]:
                # Exit code 0 = no errors, 1 = errors found (both are valid)
                # Other codes indicate actual failures
                return []
            
            # Parse JSON output
            if not result.stdout.strip():
                return []
            
            # Ruff outputs JSON - could be an array or one object per line
            errors = []
            stdout = result.stdout.strip()
            
            # Try parsing as JSON array first
            try:
                data_list = json.loads(stdout)
                if isinstance(data_list, list):
                    # It's a JSON array
                    diagnostics = data_list
                else:
                    # Single object, wrap in list
                    diagnostics = [data_list]
            except json.JSONDecodeError:
                # Not a JSON array, try parsing line by line
                diagnostics = []
                for line in stdout.split("\n"):
                    if not line.strip():
                        continue
                    try:
                        diagnostics.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
            
            # Process each diagnostic
            for data in diagnostics:
                if not isinstance(data, dict):
                    continue
                
                # Ruff JSON format: {"code": "E501", "message": "...", "location": {"row": 10, "column": 80}, "filename": "path/to/file.py"}
                # Or: {"code": {...}, "message": "...", "location": {...}, "filename": "..."}
                code_obj = data.get("code", {})
                if isinstance(code_obj, dict):
                    code = code_obj.get("code", "") or code_obj.get("name", "")
                else:
                    code = str(code_obj) if code_obj else ""
                
                message = data.get("message", "")
                location = data.get("location", {})
                filename = data.get("filename", "")
                
                if not filename:
                    continue
                
                # Get relative path from repo_path
                file_path = Path(filename)
                if file_path.is_absolute():
                    try:
                        file_path = file_path.relative_to(repo_path)
                    except ValueError:
                        # File is outside repo, skip
                        continue
                
                line_num = location.get("row", 1) if isinstance(location, dict) else 1
                
                # Determine severity based on error code
                # Ruff error codes: E = error, W = warning, F = error (pyflakes), etc.
                severity = "error"
                if code.startswith("W") or code.startswith("I"):
                    severity = "warning"
                elif code.startswith("N") or code.startswith("UP"):
                    severity = "info"
                
                errors.append(LintError(
                    file=str(file_path),
                    line=line_num,
                    message=message,
                    severity=severity,
                    code=code
                ))
            
            return errors
        
        except Exception:
            # Gracefully handle any errors (subprocess failures, etc.)
            return []
    
    def get_supported_extensions(self) -> List[str]:
        """Get list of file extensions this checker supports.
        
        Returns:
            List of Python file extensions: [".py", ".pyi"].
        """
        return [".py", ".pyi"]
