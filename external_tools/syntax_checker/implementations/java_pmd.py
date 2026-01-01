"""Java syntax checker using PMD.

This module implements a syntax checker for Java files using PMD (Source Code Analyzer),
a static analysis tool that analyzes Java source code for potential bugs and code quality issues.
"""

import json
import shutil
import subprocess
from pathlib import Path
from typing import List

from external_tools.syntax_checker.base import BaseSyntaxChecker, LintError


class JavaPMDChecker(BaseSyntaxChecker):
    """Syntax checker for Java files using PMD.
    
    This checker uses the `pmd check` command to analyze Java files
    and report linting errors. It uses an Agent-Defined Config (ADC) strategy,
    forcing the use of an internal ruleset file that ignores user's PMD configuration
    and only reports critical errors.
    It gracefully handles cases where PMD is not installed or files don't exist.
    """
    
    def __init__(self):
        """Initialize the PMD checker."""
        self._pmd_available = self._check_pmd_available()
        self._ruleset_path = self._get_internal_ruleset_path()
        self._warning_shown = False
    
    def _get_internal_ruleset_path(self) -> Path:
        """Get path to the internal PMD ruleset file.
        
        Returns:
            Path to internal ruleset file (absolute path).
        """
        # Ruleset is in external_tools/config/pmd-rules.xml
        # Get the path relative to this file
        current_file = Path(__file__)
        # Go up: implementations -> syntax_checker -> external_tools -> config
        ruleset_path = current_file.parent.parent.parent / "config" / "pmd-rules.xml"
        return ruleset_path.resolve()
    
    def _check_pmd_available(self) -> bool:
        """Check if pmd command is available in PATH.
        
        Returns:
            True if pmd is available, False otherwise.
        """
        return shutil.which("pmd") is not None
    
    async def check(
        self,
        repo_path: Path,
        files: List[str]
    ) -> List[LintError]:
        """Run PMD on the specified Java files.
        
        Args:
            repo_path: Root path of the repository.
            files: List of file paths relative to repo_path to check.
        
        Returns:
            A list of LintError objects found by PMD. Returns empty list
            if PMD is not available, if no Java files are found, or if
            no errors are detected.
        """
        if not self._pmd_available:
            if not self._warning_shown:
                print("  ⚠️  Warning: PMD is not installed. Java syntax checking will be skipped.")
                print("     Install PMD from: https://pmd.github.io/")
                print("     Or use: brew install pmd")
                self._warning_shown = True
            return []
        
        # Check if internal ruleset exists
        if not self._ruleset_path.exists():
            print(f"  ⚠️  Warning: PMD ruleset file not found at {self._ruleset_path}")
            return []
        
        # Filter to only Java files and existing files
        java_files = [
            f for f in files
            if f.endswith(".java")
        ]
        
        if not java_files:
            return []
        
        # Get existing file paths
        existing_files = self._filter_existing_files(repo_path, java_files)
        
        if not existing_files:
            # If using --diff-file mode, files might not exist locally
            # Return empty list gracefully
            return []
        
        # Build PMD command with ADC strategy:
        # -R: Use internal ruleset file (ignores user's PMD configuration)
        # -f json: JSON output format
        # -d: Directory or files to analyze
        # Use relative paths from repo_path
        relative_paths = [str(f.relative_to(repo_path)) for f in existing_files]
        
        try:
            # Build PMD command with ADC strategy:
            # -R: Use internal ruleset file (ignores user's PMD configuration)
            # -f json: JSON output format
            # -d: Files or directories to analyze
            # PMD can analyze multiple files by specifying them as separate -d arguments
            cmd = [
                "pmd",
                "check",
                "-R", str(self._ruleset_path),  # Use internal ruleset
                "-f", "json"  # JSON output format
            ]
            
            # Add each file as a separate -d argument
            # This ensures we only analyze the files we're interested in
            for rel_path in relative_paths:
                cmd.extend(["-d", rel_path])
            
            result = subprocess.run(
                cmd,
                cwd=repo_path,
                capture_output=True,
                text=True,
                check=False,  # Don't raise on non-zero exit
                encoding="utf-8"
            )
            
            # PMD returns non-zero exit code if errors are found
            # Exit codes: 0 = no errors, 4 = violations found (both are valid)
            # Other codes indicate actual failures
            if result.returncode not in [0, 4]:
                # Other codes indicate actual failures
                # Check stderr for error messages
                if result.stderr:
                    print(f"  ⚠️  Warning: PMD error: {result.stderr[:200]}")
                return []
            
            # Parse JSON output
            if not result.stdout.strip():
                return []
            
            errors = []
            stdout = result.stdout.strip()
            
            # PMD outputs JSON - could be an object with files array
            try:
                data = json.loads(stdout)
                
                # PMD JSON format:
                # {
                #   "version": "7.x.x",
                #   "timestamp": "...",
                #   "files": [
                #     {
                #       "filename": "path/to/file.java",
                #       "violations": [
                #         {
                #           "beginLine": 10,
                #           "endLine": 10,
                #           "beginColumn": 5,
                #           "endColumn": 20,
                #           "rule": "NullAssignment",
                #           "ruleset": "Error Prone",
                #           "package": "com.example",
                #           "class": "MyClass",
                #           "method": "myMethod",
                #           "externalInfoUrl": "...",
                #           "message": "Error message",
                #           "priority": 1
                #         }
                #       ]
                #     }
                #   ]
                # }
                
                if not isinstance(data, dict):
                    return []
                
                files_data = data.get("files", [])
                if not isinstance(files_data, list):
                    return []
                
                # Filter to only files we're interested in
                file_paths_set = set(relative_paths)
                
                for file_data in files_data:
                    if not isinstance(file_data, dict):
                        continue
                    
                    # Extract file path
                    filename = file_data.get("filename", "")
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
                    
                    # Check if this file is in our list
                    file_path_str = str(file_path)
                    if file_path_str not in file_paths_set:
                        continue
                    
                    # Process violations for this file
                    violations = file_data.get("violations", [])
                    if not isinstance(violations, list):
                        continue
                    
                    for violation in violations:
                        if not isinstance(violation, dict):
                            continue
                        
                        # Extract line number
                        line_num = violation.get("beginLine", violation.get("line", 1))
                        if not isinstance(line_num, int):
                            line_num = 1
                        
                        # Extract message
                        message = violation.get("message", "")
                        if not message:
                            continue
                        
                        # Extract rule code
                        rule = violation.get("rule", "") or violation.get("ruleName", "")
                        
                        # Determine severity based on priority
                        # PMD priority: 1=Blocker, 2=Critical, 3=Major, 4=Minor, 5=Info
                        priority = violation.get("priority", 3)
                        if priority <= 2:
                            severity = "error"
                        elif priority == 3:
                            severity = "warning"
                        else:
                            severity = "info"
                        
                        errors.append(LintError(
                            file=file_path_str,
                            line=line_num,
                            message=message,
                            severity=severity,
                            code=rule
                        ))
                
                return errors
            
            except json.JSONDecodeError:
                # If JSON parsing fails, try to parse text output as fallback
                # (though this shouldn't happen with -f json)
                return []
        
        except Exception as e:
            # Gracefully handle any errors (subprocess failures, etc.)
            print(f"  ⚠️  Warning: PMD check failed: {e}")
            return []
    
    def get_supported_extensions(self) -> List[str]:
        """Get list of file extensions this checker supports.
        
        Returns:
            List of Java file extensions: [".java"].
        """
        return [".java"]

