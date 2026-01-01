"""Go syntax checker using go vet.

This module implements a syntax checker for Go files using go vet,
the official Go static analysis tool that comes with the Go standard library.
"""

import re
import shutil
import subprocess
from pathlib import Path
from typing import List

from external_tools.syntax_checker.base import BaseSyntaxChecker, LintError


class GoVetChecker(BaseSyntaxChecker):
    """Syntax checker for Go files using go vet.
    
    This checker uses the `go vet` command to analyze Go files
    and report linting errors. It uses an Agent-Defined Config (ADC) strategy,
    as go vet requires no configuration files and is the official Go tool.
    It gracefully handles cases where go command is not available or files don't exist.
    """
    
    def __init__(self):
        """Initialize the go vet checker."""
        self._go_available = self._check_go_available()
        self._warning_shown = False
    
    def _check_go_available(self) -> bool:
        """Check if go command is available in PATH.
        
        Returns:
            True if go is available, False otherwise.
        """
        return shutil.which("go") is not None
    
    def _get_package_dir(self, file_path: Path, repo_path: Path) -> Path:
        """Get the package directory for a Go file.
        
        Args:
            file_path: Full path to the Go file.
            repo_path: Root path of the repository.
        
        Returns:
            Path to the package directory relative to repo_path.
        """
        # Go package is defined by the directory containing the file
        # Simply use the file's parent directory as the package directory
        try:
            return file_path.parent.relative_to(repo_path)
        except ValueError:
            # If we can't get relative path, return current directory
            return Path(".")
    
    async def check(
        self,
        repo_path: Path,
        files: List[str]
    ) -> List[LintError]:
        """Run go vet on the specified Go files.
        
        Args:
            repo_path: Root path of the repository.
            files: List of file paths relative to repo_path to check.
        
        Returns:
            A list of LintError objects found by go vet. Returns empty list
            if go vet is not available, if no Go files are found, or if
            no errors are detected.
        """
        if not self._go_available:
            if not self._warning_shown:
                print("  ⚠️  Warning: Go is not installed. Go syntax checking will be skipped.")
                print("     Install Go from: https://go.dev/")
                self._warning_shown = True
            return []
        
        # Filter to only Go files and existing files
        go_files = [
            f for f in files
            if f.endswith(".go")
        ]
        
        if not go_files:
            return []
        
        # Get existing file paths
        existing_files = self._filter_existing_files(repo_path, go_files)
        
        if not existing_files:
            # If using --diff-file mode, files might not exist locally
            # Return empty list gracefully
            return []
        
        # Group files by package directory
        # go vet checks packages, not individual files
        packages: dict[Path, list[Path]] = {}
        for file_path in existing_files:
            package_dir = self._get_package_dir(file_path, repo_path)
            if package_dir not in packages:
                packages[package_dir] = []
            packages[package_dir].append(file_path)
        
        all_errors = []
        
        try:
            for package_dir, package_files in packages.items():
                # Build go vet command
                # go vet checks packages, so we pass the package path
                package_path = "./" + str(package_dir) if package_dir != Path(".") else "./..."
                
                cmd = [
                    "go",
                    "vet",
                    package_path
                ]
                
                result = subprocess.run(
                    cmd,
                    cwd=repo_path,
                    capture_output=True,
                    text=True,
                    check=False,  # Don't raise on non-zero exit
                    encoding="utf-8"
                )
                
                # go vet returns non-zero exit code if errors are found
                # Exit codes: 0 = no errors, non-zero = errors found
                if result.returncode == 0:
                    # No errors found
                    continue
                
                # Parse text output
                # Format: file.go:line:column: message
                # Example: pkg/services/authz/rbac.go:10:5: Printf format %d has arg #1 of wrong type
                if not result.stdout.strip() and not result.stderr.strip():
                    continue
                
                # go vet outputs to stderr, not stdout
                output = result.stderr.strip() or result.stdout.strip()
                
                # Parse each line
                # Pattern: file.go:line:column: message
                pattern = re.compile(r'^(.+?):(\d+):(\d+):\s+(.+)$')
                
                for line in output.split("\n"):
                    if not line.strip():
                        continue
                    
                    match = pattern.match(line.strip())
                    if not match:
                        # Try alternative format without column: file.go:line: message
                        alt_pattern = re.compile(r'^(.+?):(\d+):\s+(.+)$')
                        match = alt_pattern.match(line.strip())
                        if not match:
                            continue
                        file_path_str, line_str, message = match.groups()
                        col_str = "1"
                    else:
                        file_path_str, line_str, col_str, message = match.groups()
                    
                    # Get relative path from repo_path
                    # go vet outputs paths relative to the working directory (repo_path)
                    file_path = Path(file_path_str)
                    if file_path.is_absolute():
                        try:
                            file_path = file_path.relative_to(repo_path)
                        except ValueError:
                            # File is outside repo, skip
                            continue
                    else:
                        # Relative path, already relative to repo_path
                        # Normalize the path (remove ./ prefix if present)
                        if file_path_str.startswith("./"):
                            file_path = Path(file_path_str[2:])
                    
                    file_path_str_relative = str(file_path)
                    
                    # Parse line number
                    try:
                        line_num = int(line_str)
                    except ValueError:
                        line_num = 1
                    
                    # Extract error code if present (go vet doesn't provide codes, but we can infer from message)
                    code = ""
                    if "Printf" in message:
                        code = "printf"
                    elif "unused" in message.lower():
                        code = "unused"
                    elif "nil" in message.lower():
                        code = "nil"
                    
                    all_errors.append(LintError(
                        file=file_path_str_relative,
                        line=line_num,
                        message=message,
                        severity="error",  # go vet only reports errors
                        code=code
                    ))
            
            return all_errors
        
        except Exception as e:
            # Gracefully handle any errors (subprocess failures, etc.)
            print(f"  ⚠️  Warning: go vet check failed: {e}")
            return []
    
    def get_supported_extensions(self) -> List[str]:
        """Get list of file extensions this checker supports.
        
        Returns:
            List of Go file extensions: [".go"].
        """
        return [".go"]

