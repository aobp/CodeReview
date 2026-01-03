"""LangChain 工具定义。

将 file_tools 和 grep_tool 转换为可供 LangGraph 使用的 function call。
使用闭包注入上下文（workspace_root, asset_key），避免重复代码。
"""

import os
import json
from pathlib import Path
from typing import Optional, Dict, Any, List, Tuple
from langchain_core.tools import tool, BaseTool
from dao.factory import get_storage


def create_tools_with_context(
    workspace_root: Optional[Path] = None,
    asset_key: Optional[str] = None
) -> List[BaseTool]:
    """创建带上下文的 LangChain 工具列表。
    
    通过闭包注入 workspace_root 和 asset_key，创建可直接用于 LangGraph 的工具。
    
    Args:
        workspace_root: 工作区根目录路径。
        asset_key: 仓库映射的资产键。
    
    Returns:
        LangChain 工具列表：fetch_repo_map, read_file, run_grep。
    """
    workspace_root_str = str(workspace_root) if workspace_root else None
    
    @tool
    async def fetch_repo_map() -> Dict[str, Any]:
        """获取仓库结构映射。
        
        从存储层加载仓库映射资产，返回项目结构的摘要。
        
        Returns:
            包含 summary, file_count, files, source_path, error 的字典。
        """
        try:
            storage = get_storage()
            await storage.connect()
            
            key = asset_key if asset_key else "repo_map"
            repo_map_data = await storage.load("assets", key)
            
            if repo_map_data is None:
                return {
                    "summary": "Repository map not found. Please build the repository map first.",
                    "file_count": 0,
                    "files": [],
                    "error": "Repository map not found in storage"
                }
            
            file_tree = repo_map_data.get("file_tree", "No file tree available")
            file_count = repo_map_data.get("file_count", 0)
            files = repo_map_data.get("files", [])
            source_path = repo_map_data.get("source_path", "unknown")
            
            files_preview = files[:50]
            files_display = "\n".join(f"  - {f}" for f in files_preview)
            if len(files) > 50:
                files_display += f"\n  ... and {len(files) - 50} more files"
            
            summary = f"""Repository Structure Summary:
                    Source Path: {source_path}
                    Total Files: {file_count}

                    File Tree:
                    {file_tree}

                    Key Files (first 50):
                    {files_display}
                    """
            
            return {
                "summary": summary,
                "file_count": file_count,
                "files": files_preview,
                "all_files": files,
                "source_path": source_path,
                "error": None
            }
        except Exception as e:
            return {
                "summary": "",
                "file_count": 0,
                "files": [],
                "error": f"Error fetching repository map: {str(e)}"
            }
    
    @tool
    async def read_file(
        file_path: str,
        max_lines: Optional[int] = None,
        encoding: str = "utf-8"
    ) -> Dict[str, Any]:
        """读取文件内容。
        
        Args:
            file_path: 文件路径（相对于工作区根目录或绝对路径）。
            max_lines: 可选的最大行数限制。
            encoding: 文件编码，默认为 'utf-8'。
        
        Returns:
            包含 content, file_path, line_count, encoding, error 的字典。
        """
        try:
            file_path_obj = Path(file_path)
            if not file_path_obj.is_absolute():
                workspace = Path(workspace_root_str) if workspace_root_str else Path.cwd()
                file_path_obj = workspace / file_path_obj
            
            if not file_path_obj.exists():
                return {
                    "content": "",
                    "file_path": str(file_path_obj),
                    "line_count": 0,
                    "encoding": encoding,
                    "error": f"File not found: {file_path_obj}"
                }
            
            with open(file_path_obj, "r", encoding=encoding) as f:
                lines = f.readlines()
                line_count = len(lines)
                
                if max_lines and line_count > max_lines:
                    content = "".join(lines[:max_lines])
                    content += f"\n... (truncated, {line_count - max_lines} more lines)"
                else:
                    content = "".join(lines)
            
            return {
                "content": content,
                "file_path": str(file_path_obj),
                "line_count": line_count,
                "encoding": encoding,
                "error": None
            }
        except Exception as e:
            return {
                "content": "",
                "file_path": str(file_path),
                "line_count": 0,
                "encoding": encoding,
                "error": f"Error reading file: {str(e)}"
            }
    
    @tool
    async def run_grep(
        pattern: str,
        is_regex: bool = False,
        case_sensitive: bool = True,
        include_patterns: Optional[List[str]] = None,
        exclude_patterns: Optional[List[str]] = None,
        context_lines: int = 10,
        max_results: int = 50,
    ) -> str:
        """在代码库中搜索字符串或正则表达式。
        
        Args:
            pattern: 搜索模式（字符串或正则表达式）。
            is_regex: 是否将模式视为正则表达式。默认为 False。
            case_sensitive: 搜索是否区分大小写。默认为 True。
            include_patterns: 要包含的文件名模式列表。默认为 ["*"]。
            exclude_patterns: 要排除的文件模式列表。默认为空列表。
            context_lines: 每个匹配项前后的上下文行数。默认为 10。
            max_results: 返回的最大匹配块数。默认为 50。
        
        Returns:
            包含所有匹配项的格式化字符串，包含文件路径、匹配行和上下文。
        """
        from tools.grep_tool import _grep_internal
        import os
        
        repo_root = workspace_root_str if workspace_root_str else (os.getenv("REPO_ROOT") or os.getcwd())
        
        if include_patterns is None:
            include_patterns = ["*"]
        if exclude_patterns is None:
            exclude_patterns = []
        
        return _grep_internal(
            repo_root=repo_root,
            pattern=pattern,
            is_regex=is_regex,
            case_sensitive=case_sensitive,
            include_patterns=tuple(include_patterns),
            exclude_patterns=tuple(exclude_patterns),
            context_lines=context_lines,
            max_results=max_results,
        )

    # ---- Lite-CPG tools (vendored into CodeReview/lite_cpg) ----

    def _lite_cpg_db_path() -> Optional[str]:
        return os.environ.get("LITE_CPG_DB_PATH")

    def _lite_cpg_default_rev() -> str:
        return os.environ.get("LITE_CPG_DEFAULT_REV", "head")

    def _lite_cpg_missing() -> Dict[str, Any]:
        # Keep the same error style as existing tools: top-level "error" string (or None).
        return {
            "error": "Lite-CPG DB not available. Please run CodeReview main flow to build per-diff index first (LITE_CPG_DB_PATH is not set)."
        }

    def _unwrap_lite_cpg_result(res: Dict[str, Any]) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
        """将 lite_cpg.tools 返回的 ToolResult 统一转换为 (data, error_msg)。"""
        if not isinstance(res, dict):
            return None, f"Invalid Lite-CPG tool result type: {type(res)}"
        if res.get("ok") is True:
            data = res.get("data")
            if isinstance(data, dict):
                return data, None
            return {"data": data}, None
        err = res.get("error") or {}
        msg = err.get("message") if isinstance(err, dict) else str(err)
        if not msg:
            msg = "Lite-CPG tool call failed"
        return None, msg

    # ----------------------------
    # Lite-CPG output budget helpers
    # ----------------------------
    #
    # Motivation:
    # - Expert graph may accumulate tool results into messages; oversized tool payloads can
    #   easily exceed model context limits (see terminal: 260k+ tokens).
    # - Tool design intention here is "location-first": return enough evidence to guide
    #   the next, more targeted query, not to dump entire repo-scale structures.

    _CPG_MAX_ITEMS_DEFAULT = 120
    _CPG_MAX_TEXT_CHARS_DEFAULT = 6000

    def _attach_payload_stats(payload: Dict[str, Any]) -> Dict[str, Any]:
        """Attach lightweight payload size stats to help identify oversized tool outputs.

        NOTE: This is intentionally best-effort and must not raise.
        """
        try:
            s = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), default=str)
            return {
                "_payload": {
                    "approx_chars": len(s),
                    "approx_bytes_utf8": len(s.encode("utf-8", errors="ignore")),
                    "keys": sorted(list(payload.keys()))[:50],
                }
            }
        except Exception as e:
            return {"_payload": {"error": str(e)}}

    def _drop_attrs_inplace(obj: Any) -> Any:
        """Remove verbose 'attrs' keys recursively (best-effort) to reduce payload size."""
        if isinstance(obj, dict):
            if "attrs" in obj:
                obj.pop("attrs", None)
            for k, v in list(obj.items()):
                obj[k] = _drop_attrs_inplace(v)
            return obj
        if isinstance(obj, list):
            for i in range(len(obj)):
                obj[i] = _drop_attrs_inplace(obj[i])
            return obj
        return obj

    def _trim_list(obj: Any, *, key: str, limit: int) -> Tuple[Any, Dict[str, Any]]:
        """Trim a list field and return meta about truncation."""
        if not isinstance(obj, list):
            return obj, {}
        total = len(obj)
        if total <= limit:
            return obj, {f"{key}_total": total, f"{key}_returned": total, f"{key}_truncated": False}
        return (
            obj[:limit],
            {f"{key}_total": total, f"{key}_returned": limit, f"{key}_truncated": True},
        )

    def _trim_text(s: Any, *, key: str, limit_chars: int) -> Tuple[Any, Dict[str, Any]]:
        if not isinstance(s, str):
            return s, {}
        total = len(s)
        if total <= limit_chars:
            return s, {f"{key}_chars": total, f"{key}_truncated": False}
        return (
            s[:limit_chars] + "\n...[truncated]...",
            {f"{key}_chars": total, f"{key}_truncated": True},
        )

    @tool
    async def cpg_symbol_search(
        query: str,
        rev: Optional[str] = None,
        lang: Optional[str] = None,
        file_path: Optional[str] = None,
        limit: int = 50,
        include_callsites: bool = True,
        exact_name: bool = True,
    ) -> Dict[str, Any]:
        """Lite-CPG：符号定义搜索（可选包含调用点）。

        Args:
            query: 要搜索的符号名（默认优先精确匹配；无精确命中时才回退模糊匹配）。
            rev: 版本标识，"head" 或 "base"。默认使用 "head"。
            lang: 语言过滤（python/typescript/go/java/ruby），不传表示不过滤。
            file_path: 文件路径过滤（绝对路径），不传表示不过滤。
            limit: 最多返回多少个符号命中。
            include_callsites: 是否附带调用点（callsite）节点。
            exact_name: 是否要求符号名精确等于 query（默认 True）。若为 True 且无命中，工具会自动回退到模糊匹配。

        Returns:
            返回一个 dict，字段稳定、便于 prompt 引用：
            - rev: 实际使用的版本
            - query: 原始查询
            - symbols: 符号定义列表（含 location）
            - callsites: 调用点列表（含 location）
            - error: 错误信息（无错误为 None）
        """
        db_path = _lite_cpg_db_path()
        if not db_path:
            out = {"rev": rev or _lite_cpg_default_rev(), "query": query, "symbols": [], "callsites": [], "error": None}
            out.update(_lite_cpg_missing())
            return out
        from lite_cpg.tools.cpg_tools import symbol_search

        raw = symbol_search(
            db_path=db_path,
            rev=rev or _lite_cpg_default_rev(),
            query=query,
            lang=lang,
            file_path=file_path,
            limit=limit,
            include_callsites=include_callsites,
            exact_name=exact_name,
        )
        data, err = _unwrap_lite_cpg_result(raw)
        if data is None:
            return {"rev": rev or _lite_cpg_default_rev(), "query": query, "symbols": [], "callsites": [], "error": err}
        # Budget control: drop attrs + cap callsites/symbols even if upstream returns a lot.
        _drop_attrs_inplace(data)
        meta: Dict[str, Any] = {"_budget": {"attrs_dropped": True}}
        if "symbols" in data:
            data["symbols"], m = _trim_list(data["symbols"], key="symbols", limit=min(int(limit), _CPG_MAX_ITEMS_DEFAULT))
            meta["_budget"].update(m)
        if "callsites" in data:
            data["callsites"], m = _trim_list(data["callsites"], key="callsites", limit=_CPG_MAX_ITEMS_DEFAULT)
            meta["_budget"].update(m)
        out = {**data, **meta, "error": None}
        out.update(_attach_payload_stats(out))
        return out

    @tool
    async def cpg_ast_index(
        file_paths: Optional[List[str]] = None,
        rev: Optional[str] = None,
        lang: Optional[str] = None,
        include_defs: bool = True,
        include_calls: bool = True,
        include_imports: bool = True,
        limit_per_file: int = 120,
        compact: bool = True,
    ) -> Dict[str, Any]:
        """Lite-CPG：文件级 defs/calls/imports 索引视图。

        Args:
            file_paths: 需要索引视图的文件路径列表（绝对路径）。不传表示按 rev 返回全库文件的视图（可能很大）。
            rev: 版本标识，"head" 或 "base"。默认使用 "head"。
            lang: 语言过滤（python/typescript/go/java/ruby），不传表示不过滤。
            include_defs: 是否包含定义（defs）。
            include_calls: 是否包含调用（calls）。
            include_imports: 是否包含导入（imports）。
            limit_per_file: 每个文件最多返回的条目数量（用于防止输出过大）。
            compact: 是否返回精简视图（默认 True）。精简视图会去掉长字段（如 symbol_id/location 的完整结构），仅保留 name/kind/行号范围等用于导航的关键信息。

        Returns:
            - rev: 实际使用的版本
            - files: 文件视图列表（每个包含 path/lang/defs/calls/imports 等）
            - error: 错误信息（无错误为 None）
        """
        db_path = _lite_cpg_db_path()
        if not db_path:
            out = {"rev": rev or _lite_cpg_default_rev(), "files": [], "error": None}
            out.update(_lite_cpg_missing())
            return out
        from lite_cpg.tools.cpg_tools import ast_index

        # Budget control: repo-wide ast_index can be enormous. If file_paths is omitted,
        # we intentionally return a small file list only (location-first guidance),
        # and ask callers to pass file_paths for detailed defs/calls/imports.
        effective_include_defs = include_defs
        effective_include_calls = include_calls
        effective_include_imports = include_imports
        summary_only = file_paths is None
        if summary_only:
            effective_include_defs = False
            effective_include_calls = False
            effective_include_imports = False

        raw = ast_index(
            db_path=db_path,
            rev=rev or _lite_cpg_default_rev(),
            file_paths=file_paths,
            lang=lang,
            include_defs=effective_include_defs,
            include_calls=effective_include_calls,
            include_imports=effective_include_imports,
            limit_per_file=limit_per_file,
        )
        data, err = _unwrap_lite_cpg_result(raw)
        if data is None:
            return {"rev": rev or _lite_cpg_default_rev(), "files": [], "error": err}
        _drop_attrs_inplace(data)
        meta: Dict[str, Any] = {
            "_budget": {
                "attrs_dropped": True,
                "summary_only": bool(summary_only),
            }
        }
        # Trim files list; also shrink each file entry if summary_only.
        files = data.get("files", [])
        files, m = _trim_list(files, key="files", limit=_CPG_MAX_ITEMS_DEFAULT)
        meta["_budget"].update(m)
        if isinstance(files, list):
            if summary_only:
                files = [{"path": f.get("path"), "lang": f.get("lang")} if isinstance(f, dict) else f for f in files]
                meta["_budget"]["note"] = "file_paths not provided; returning files list only. Pass file_paths for defs/calls/imports."
            # If not summary_only and compact requested, shrink per-file entries to reduce payload.
            if (not summary_only) and compact:
                compacted = []
                for f in files:
                    if not isinstance(f, dict):
                        compacted.append(f)
                        continue
                    fe: Dict[str, Any] = {"path": f.get("path"), "lang": f.get("lang")}
                    # defs
                    if include_defs and isinstance(f.get("defs"), list):
                        defs_list = f.get("defs") or []
                        fe["defs_total"] = len(defs_list)
                        # Keep only name/kind and line-range for navigation; drop long symbol_id & nested location fields.
                        fe["defs"] = [
                            {
                                "name": d.get("name"),
                                "kind": d.get("kind"),
                                "start_line": (d.get("location") or {}).get("start_line") if isinstance(d, dict) else None,
                                "end_line": (d.get("location") or {}).get("end_line") if isinstance(d, dict) else None,
                            }
                            for d in defs_list[: int(limit_per_file)]
                            if isinstance(d, dict)
                        ]
                    # calls
                    if include_calls and isinstance(f.get("calls"), list):
                        calls_list = f.get("calls") or []
                        fe["calls_total"] = len(calls_list)
                        fe["calls"] = [
                            {
                                "dst_name": c.get("dst_name"),
                                "resolved": c.get("resolved"),
                                "line": (c.get("location") or {}).get("start_line") if isinstance(c, dict) else None,
                            }
                            for c in calls_list[: int(limit_per_file)]
                            if isinstance(c, dict)
                        ]
                    # imports
                    if include_imports and isinstance(f.get("imports"), list):
                        imps = f.get("imports") or []
                        fe["imports_total"] = len(imps)
                        fe["imports"] = [
                            {
                                "import_text": i.get("import_text"),
                                "line": (i.get("location") or {}).get("start_line") if isinstance(i, dict) else None,
                            }
                            for i in imps[: int(limit_per_file)]
                            if isinstance(i, dict)
                        ]
                    # pass through any import extraction error (small string)
                    if "imports_error" in f:
                        fe["imports_error"] = f.get("imports_error")
                    compacted.append(fe)
                files = compacted
                meta["_budget"]["compact"] = True
            data["files"] = files
        out = {**data, **meta, "error": None}
        out.update(_attach_payload_stats(out))
        return out

    @tool
    async def cpg_resolve_import(
        lang: str,
        from_module: str,
        name: str,
        rev: Optional[str] = None,
        repo_root_hint: Optional[str] = None,
        importer_file_path: Optional[str] = None,
        max_depth: int = 8,
    ) -> Dict[str, Any]:
        """Lite-CPG：严格导入/导出链验证（可证明才成功，不猜测）。

        Args:
            lang: 语言（python/typescript/go/java/ruby）。
            from_module: import 来源模块（按语言语义解释）。
            name: 需要证明可被导入/导出的符号名。
            rev: 版本标识，"head" 或 "base"。默认使用 "head"。
            repo_root_hint: 仓库根目录（用于 python/java/go/ruby 的 repo-local 严格解析）。
            importer_file_path: 发起导入的文件路径（用于 typescript/ruby 相对路径解析）。
            max_depth: TS re-export/`export *` 链的最大递归深度。

        Returns:
            - rev/lang/from_module/name
            - matches: 证明链命中的位置列表（结构按语言不同）
            - error: 错误信息（无错误为 None）
        """
        db_path = _lite_cpg_db_path()
        if not db_path:
            out = {"rev": rev or _lite_cpg_default_rev(), "lang": lang, "from_module": from_module, "name": name, "matches": [], "error": None}
            out.update(_lite_cpg_missing())
            return out
        from lite_cpg.tools.cpg_tools import resolve_import

        raw = resolve_import(
            db_path=db_path,
            rev=rev or _lite_cpg_default_rev(),
            lang=lang,
            from_module=from_module,
            name=name,
            repo_root_hint=repo_root_hint,
            importer_file_path=importer_file_path,
            max_depth=max_depth,
        )
        data, err = _unwrap_lite_cpg_result(raw)
        if data is None:
            return {"rev": rev or _lite_cpg_default_rev(), "lang": lang, "from_module": from_module, "name": name, "matches": [], "error": err}
        # normalize: ensure matches key exists for prompt stability
        if "matches" not in data:
            data["matches"] = []
        meta: Dict[str, Any] = {"_budget": {}}
        if "matches" in data:
            data["matches"], m = _trim_list(data["matches"], key="matches", limit=_CPG_MAX_ITEMS_DEFAULT)
            meta["_budget"].update(m)
        out = {**data, **meta, "error": None}
        out.update(_attach_payload_stats(out))
        return out

    @tool
    async def cpg_query_forward(
        start_node_id: str,
        rev: Optional[str] = None,
        max_steps: int = 64,
        max_visited: int = 2000,
    ) -> Dict[str, Any]:
        """Lite-CPG：从节点向前遍历（BFS）。

        Args:
            start_node_id: 起点节点 ID。
            rev: 版本标识，"head" 或 "base"。默认使用 "head"。
            max_steps: 最大步数（防止图遍历过深）。
            max_visited: 最大访问节点数（防止输出过大）。

        Returns:
            - rev
            - count: 返回节点数量
            - nodes: 节点列表（含 location）
            - error: 错误信息（无错误为 None）
        """
        db_path = _lite_cpg_db_path()
        if not db_path:
            out = {"rev": rev or _lite_cpg_default_rev(), "count": 0, "nodes": [], "error": None}
            out.update(_lite_cpg_missing())
            return out
        from lite_cpg.tools.cpg_tools import cpg_query_forward

        raw = cpg_query_forward(
            db_path=db_path,
            rev=rev or _lite_cpg_default_rev(),
            start_node_id=start_node_id,
            max_steps=max_steps,
            max_visited=max_visited,
        )
        data, err = _unwrap_lite_cpg_result(raw)
        if data is None:
            return {"rev": rev or _lite_cpg_default_rev(), "count": 0, "nodes": [], "error": err}
        meta: Dict[str, Any] = {"_budget": {}}
        if "nodes" in data:
            data["nodes"], m = _trim_list(data["nodes"], key="nodes", limit=_CPG_MAX_ITEMS_DEFAULT)
            meta["_budget"].update(m)
        out = {**data, **meta, "error": None}
        out.update(_attach_payload_stats(out))
        return out

    @tool
    async def cpg_query_backward(
        sink_node_id: str,
        rev: Optional[str] = None,
        max_steps: int = 64,
        max_visited: int = 2000,
    ) -> Dict[str, Any]:
        """Lite-CPG：从节点向后遍历（BFS）。

        Args:
            sink_node_id: 汇点节点 ID。
            rev: 版本标识，"head" 或 "base"。默认使用 "head"。
            max_steps: 最大步数（防止图遍历过深）。
            max_visited: 最大访问节点数（防止输出过大）。

        Returns:
            - rev
            - count: 返回节点数量
            - nodes: 节点列表（含 location）
            - error: 错误信息（无错误为 None）
        """
        db_path = _lite_cpg_db_path()
        if not db_path:
            out = {"rev": rev or _lite_cpg_default_rev(), "count": 0, "nodes": [], "error": None}
            out.update(_lite_cpg_missing())
            return out
        from lite_cpg.tools.cpg_tools import cpg_query_backward

        raw = cpg_query_backward(
            db_path=db_path,
            rev=rev or _lite_cpg_default_rev(),
            sink_node_id=sink_node_id,
            max_steps=max_steps,
            max_visited=max_visited,
        )
        data, err = _unwrap_lite_cpg_result(raw)
        if data is None:
            return {"rev": rev or _lite_cpg_default_rev(), "count": 0, "nodes": [], "error": err}
        meta: Dict[str, Any] = {"_budget": {}}
        if "nodes" in data:
            data["nodes"], m = _trim_list(data["nodes"], key="nodes", limit=_CPG_MAX_ITEMS_DEFAULT)
            meta["_budget"].update(m)
        out = {**data, **meta, "error": None}
        out.update(_attach_payload_stats(out))
        return out

    @tool
    async def cpg_slice(
        criteria_node_ids: List[str],
        direction: str,
        rev: Optional[str] = None,
        max_nodes: int = 200,
    ) -> Dict[str, Any]:
        """Lite-CPG：图切片（forward/backward）。

        Args:
            criteria_node_ids: 作为切片准则的节点 ID 列表。
            direction: "forward" 或 "backward"。
            rev: 版本标识，"head" 或 "base"。默认使用 "head"。
            max_nodes: 最大返回节点数（预算控制）。

        Returns:
            - rev
            - count
            - nodes: 节点列表（含 location）
            - error: 错误信息（无错误为 None）
        """
        db_path = _lite_cpg_db_path()
        if not db_path:
            out = {"rev": rev or _lite_cpg_default_rev(), "count": 0, "nodes": [], "error": None}
            out.update(_lite_cpg_missing())
            return out
        from lite_cpg.tools.cpg_tools import cpg_slice

        raw = cpg_slice(
            db_path=db_path,
            rev=rev or _lite_cpg_default_rev(),
            criteria_node_ids=criteria_node_ids,
            direction=direction,
            max_nodes=max_nodes,
        )
        data, err = _unwrap_lite_cpg_result(raw)
        if data is None:
            return {"rev": rev or _lite_cpg_default_rev(), "count": 0, "nodes": [], "error": err}
        meta: Dict[str, Any] = {"_budget": {}}
        if "nodes" in data:
            data["nodes"], m = _trim_list(data["nodes"], key="nodes", limit=min(int(max_nodes), _CPG_MAX_ITEMS_DEFAULT))
            meta["_budget"].update(m)
        out = {**data, **meta, "error": None}
        out.update(_attach_payload_stats(out))
        return out

    @tool
    async def cpg_reachability(
        src_node_id: str,
        dst_node_id: str,
        rev: Optional[str] = None,
        max_steps: int = 128,
    ) -> Dict[str, Any]:
        """Lite-CPG：可达性与最短路径（best-effort）。

        Args:
            src_node_id: 起点节点 ID。
            dst_node_id: 终点节点 ID。
            rev: 版本标识，"head" 或 "base"。默认使用 "head"。
            max_steps: 最大步数。

        Returns:
            - rev
            - reachable: 是否可达
            - path: 若可达，包含 node_ids/edge_kinds/locations
            - error: 错误信息（无错误为 None）
        """
        db_path = _lite_cpg_db_path()
        if not db_path:
            out = {"rev": rev or _lite_cpg_default_rev(), "reachable": False, "path": None, "error": None}
            out.update(_lite_cpg_missing())
            return out
        from lite_cpg.tools.cpg_tools import cpg_reachability

        raw = cpg_reachability(
            db_path=db_path,
            rev=rev or _lite_cpg_default_rev(),
            src_node_id=src_node_id,
            dst_node_id=dst_node_id,
            max_steps=max_steps,
        )
        data, err = _unwrap_lite_cpg_result(raw)
        if data is None:
            return {"rev": rev or _lite_cpg_default_rev(), "reachable": False, "path": None, "error": err}
        meta: Dict[str, Any] = {"_budget": {}}
        # Path can be long; cap node_ids/locations if present.
        path = data.get("path")
        if isinstance(path, dict):
            if "node_ids" in path:
                path["node_ids"], m = _trim_list(path["node_ids"], key="path_node_ids", limit=_CPG_MAX_ITEMS_DEFAULT)
                meta["_budget"].update(m)
            if "locations" in path:
                path["locations"], m = _trim_list(path["locations"], key="path_locations", limit=_CPG_MAX_ITEMS_DEFAULT)
                meta["_budget"].update(m)
            data["path"] = path
        out = {**data, **meta, "error": None}
        out.update(_attach_payload_stats(out))
        return out

    @tool
    async def cpg_callgraph(
        node_or_symbol: str,
        direction: str = "out",
        depth: int = 2,
        limit: int = 200,
        rev: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Lite-CPG：调用图邻域（best-effort）。

        Args:
            node_or_symbol: 节点 ID 或符号 ID（best-effort）。
            direction: "out" 或 "in"。
            depth: 扩展深度。
            limit: 每层边查询的限制。
            rev: 版本标识，"head" 或 "base"。默认使用 "head"。

        Returns:
            - rev
            - nodes: 节点列表（含 location）
            - edges: 边列表（src/dst/kind）
            - error: 错误信息（无错误为 None）
        """
        db_path = _lite_cpg_db_path()
        if not db_path:
            out = {"rev": rev or _lite_cpg_default_rev(), "nodes": [], "edges": [], "error": None}
            out.update(_lite_cpg_missing())
            return out
        from lite_cpg.tools.cpg_tools import cpg_callgraph

        raw = cpg_callgraph(
            db_path=db_path,
            rev=rev or _lite_cpg_default_rev(),
            node_or_symbol=node_or_symbol,
            direction=direction,
            depth=depth,
            limit=limit,
        )
        data, err = _unwrap_lite_cpg_result(raw)
        if data is None:
            return {"rev": rev or _lite_cpg_default_rev(), "nodes": [], "edges": [], "error": err}
        meta: Dict[str, Any] = {"_budget": {}}
        if "nodes" in data:
            data["nodes"], m = _trim_list(data["nodes"], key="nodes", limit=_CPG_MAX_ITEMS_DEFAULT)
            meta["_budget"].update(m)
        if "edges" in data:
            data["edges"], m = _trim_list(data["edges"], key="edges", limit=_CPG_MAX_ITEMS_DEFAULT)
            meta["_budget"].update(m)
        out = {**data, **meta, "error": None}
        out.update(_attach_payload_stats(out))
        return out

    @tool
    async def cpg_cfg_region(
        root_node_id: str,
        depth: int = 2,
        limit: int = 500,
        rev: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Lite-CPG：控制流局部区域（best-effort）。

        Args:
            root_node_id: 控制节点 ID（例如 if/for/while 等语句节点）。
            depth: 扩展深度。
            limit: 每层边查询的限制。
            rev: 版本标识，"head" 或 "base"。默认使用 "head"。

        Returns:
            - rev
            - nodes: 节点列表（含 location）
            - edges: 边列表（src/dst/kind）
            - error: 错误信息（无错误为 None）
        """
        db_path = _lite_cpg_db_path()
        if not db_path:
            out = {"rev": rev or _lite_cpg_default_rev(), "nodes": [], "edges": [], "error": None}
            out.update(_lite_cpg_missing())
            return out
        from lite_cpg.tools.cpg_tools import cpg_cfg_region

        raw = cpg_cfg_region(
            db_path=db_path,
            rev=rev or _lite_cpg_default_rev(),
            root_node_id=root_node_id,
            depth=depth,
            limit=limit,
        )
        data, err = _unwrap_lite_cpg_result(raw)
        if data is None:
            return {"rev": rev or _lite_cpg_default_rev(), "nodes": [], "edges": [], "error": err}
        meta: Dict[str, Any] = {"_budget": {}}
        if "nodes" in data:
            data["nodes"], m = _trim_list(data["nodes"], key="nodes", limit=_CPG_MAX_ITEMS_DEFAULT)
            meta["_budget"].update(m)
        if "edges" in data:
            data["edges"], m = _trim_list(data["edges"], key="edges", limit=_CPG_MAX_ITEMS_DEFAULT)
            meta["_budget"].update(m)
        out = {**data, **meta, "error": None}
        out.update(_attach_payload_stats(out))
        return out

    @tool
    async def cpg_summary(
        symbol: str,
        rev: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Lite-CPG：符号摘要（若无 RepoMap 摘要则回退 heuristic）。

        Args:
            symbol: 符号 ID 或符号名（若为名称将 best-effort 选择第一个匹配）。
            rev: 版本标识，"head" 或 "base"。默认使用 "head"。

        Returns:
            - rev/symbol_id/name/kind/lang/file_path/location
            - signature: 尽力提取的签名
            - summary_text / summary_struct: 摘要（若无 repomap 则启发式生成）
            - _meta: 生成器信息（heuristic/none 等）
            - error: 错误信息（无错误为 None）
        """
        db_path = _lite_cpg_db_path()
        if not db_path:
            out = {"rev": rev or _lite_cpg_default_rev(), "error": None}
            out.update(_lite_cpg_missing())
            return out
        from lite_cpg.tools.cpg_tools import cpg_summary

        raw = cpg_summary(
            db_path=db_path,
            rev=rev or _lite_cpg_default_rev(),
            symbol=symbol,
        )
        data, err = _unwrap_lite_cpg_result(raw)
        if data is None:
            return {"rev": rev or _lite_cpg_default_rev(), "symbol": symbol, "error": err}
        meta: Dict[str, Any] = {"_budget": {}}
        if "summary_text" in data:
            data["summary_text"], m = _trim_text(data["summary_text"], key="summary_text", limit_chars=_CPG_MAX_TEXT_CHARS_DEFAULT)
            meta["_budget"].update(m)
        out = {**data, **meta, "error": None}
        out.update(_attach_payload_stats(out))
        return out
    
    return [
        fetch_repo_map,
        read_file,
        run_grep,
        cpg_symbol_search,
        cpg_ast_index,
        cpg_resolve_import,
        cpg_query_forward,
        cpg_query_backward,
        cpg_slice,
        cpg_reachability,
        cpg_callgraph,
        cpg_cfg_region,
        cpg_summary,
    ]

