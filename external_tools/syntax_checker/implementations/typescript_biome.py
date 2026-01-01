"""TypeScript/JavaScript syntax checker using Biome.

This module implements a syntax checker for TypeScript and JavaScript files using Biome,
a fast linter written in Rust that replaces ESLint and Prettier.
"""

import json
import shutil
import subprocess
from pathlib import Path
from typing import List

from external_tools.syntax_checker.base import BaseSyntaxChecker, LintError


class TypeScriptBiomeChecker(BaseSyntaxChecker):
    """Syntax checker for TypeScript and JavaScript files using Biome.
    
    This checker uses the `biome lint` command to analyze TypeScript and JavaScript files
    and report linting errors. It uses an Agent-Defined Config (ADC) strategy, forcing
    the use of an internal configuration file that ignores user's project configuration.
    It gracefully handles cases where Biome is not installed or files don't exist.
    """
    
    def __init__(self):
        """Initialize the Biome checker."""
        self._biome_available = self._check_biome_available()
        self._config_path = self._get_internal_config_path()
        self._warning_shown = False
    
    def _get_internal_config_path(self) -> Path:
        """Get path to the internal Biome configuration file.
        
        Returns:
            Path to internal config file (absolute path).
        """
        # Config is in external_tools/config/biome.json
        # Get the path relative to this file
        current_file = Path(__file__)
        # Go up: implementations -> syntax_checker -> external_tools -> config
        config_path = current_file.parent.parent.parent / "config" / "biome.json"
        return config_path.resolve()
    
    def _check_biome_available(self) -> bool:
        """Check if biome command is available in PATH.
        
        Returns:
            True if biome is available, False otherwise.
        """
        return shutil.which("biome") is not None
    
    async def check(
        self,
        repo_path: Path,
        files: List[str]
    ) -> List[LintError]:
        """Run Biome on the specified TypeScript/JavaScript files.
        
        Args:
            repo_path: Root path of the repository.
            files: List of file paths relative to repo_path to check.
        
        Returns:
            A list of LintError objects found by Biome. Returns empty list
            if Biome is not available, if no TypeScript/JavaScript files are found, or if
            no errors are detected. Only errors with severity "error" are included.
        """
        if not self._biome_available:
            if not self._warning_shown:
                print("  ⚠️  Warning: Biome is not installed. TypeScript/JavaScript syntax checking will be skipped.")
                print("     Install Biome with: npm install -g @biomejs/biome")
                self._warning_shown = True
            return []
        
        # Check if internal config exists
        if not self._config_path.exists():
            print(f"  ⚠️  Warning: Biome config file not found at {self._config_path}")
            return []
        
        # Filter to only TypeScript/JavaScript files and existing files
        ts_js_files = [
            f for f in files
            if f.endswith((".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs"))
        ]
        
        if not ts_js_files:
            return []
        
        # Get existing file paths
        existing_files = self._filter_existing_files(repo_path, ts_js_files)
        
        if not existing_files:
            # If using --diff-file mode, files might not exist locally
            # Return empty list gracefully
            return []
        
        # Build biome command with ADC strategy:
        # --config-path: Use internal config file (ignores user's biome.json)
        # --reporter=json: JSON output format
        # Use relative paths from repo_path
        relative_paths = [str(f.relative_to(repo_path)) for f in existing_files]
        
        try:
            cmd = [
                "biome",
                "lint",
                "--config-path", str(self._config_path),
                "--reporter=json",
                *relative_paths
            ]
            
            result = subprocess.run(
                cmd,
                cwd=repo_path,
                capture_output=True,
                text=True,
                check=False,  # Don't raise on non-zero exit
                encoding="utf-8"
            )
            
            # Biome returns non-zero exit code if errors are found
            # Exit codes: 0 = no errors, 1 = errors found
            # We only care about the JSON output
            if result.returncode not in [0, 1]:
                # Other codes indicate actual failures
                return []
            
            # Parse JSON output
            if not result.stdout.strip():
                return []
            
            errors = []
            stdout = result.stdout.strip()
            
            # Biome outputs JSON - could be an array or one object per line
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
                
                # Biome JSON format:
                # {
                #   "source": {
                #     "name": "path/to/file.ts",
                #     "text": "..."
                #   },
                #   "diagnostics": [
                #     {
                #       "severity": "error",
                #       "message": {
                #         "text": "Error message"
                #       },
                #       "span": {
                #         "start": {
                #           "line": 10,
                #           "column": 5
                #         }
                #       },
                #       "rule": "suspicious/noExplicitAny"
                #     }
                #   ]
                # }
                
                # Extract file path
                source = data.get("source", {})
                if isinstance(source, dict):
                    file_path_str = source.get("name", "")
                else:
                    file_path_str = ""
                
                if not file_path_str:
                    continue
                
                # Get relative path from repo_path
                file_path = Path(file_path_str)
                if file_path.is_absolute():
                    try:
                        file_path = file_path.relative_to(repo_path)
                    except ValueError:
                        # File is outside repo, skip
                        continue
                
                # Process diagnostics for this file
                diagnostics_list = data.get("diagnostics", [])
                for diag in diagnostics_list:
                    if not isinstance(diag, dict):
                        continue
                    
                    # Only keep errors with severity "error" (ignore warnings and info)
                    severity_str = diag.get("severity", "").lower()
                    if severity_str != "error":
                        continue
                    
                    # Extract message
                    message_obj = diag.get("message", {})
                    if isinstance(message_obj, dict):
                        message = message_obj.get("text", "") or message_obj.get("message", "")
                    else:
                        message = str(message_obj) if message_obj else ""
                    
                    if not message:
                        continue
                    
                    # Extract line number
                    span = diag.get("span", {})
                    if isinstance(span, dict):
                        start = span.get("start", {})
                        if isinstance(start, dict):
                            line_num = start.get("line", 1)
                            # Biome uses 0-indexed lines, convert to 1-indexed
                            if isinstance(line_num, int):
                                line_num = line_num + 1
                        else:
                            line_num = 1
                    else:
                        line_num = 1
                    
                    # Extract rule code
                    rule = diag.get("rule", "") or diag.get("code", "")
                    
                    errors.append(LintError(
                        file=str(file_path),
                        line=line_num,
                        message=message,
                        severity="error",  # Only errors are kept
                        code=rule
                    ))
            
            return errors
        
        except Exception:
            # Gracefully handle any errors (subprocess failures, etc.)
            return []
    
    def get_supported_extensions(self) -> List[str]:
        """Get list of file extensions this checker supports.
        
        Returns:
            List of TypeScript/JavaScript file extensions: [".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs"].
        """
        return [".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs"]

