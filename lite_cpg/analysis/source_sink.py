"""Source/Sink tagging for best-effort taint tracking."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Set


@dataclass
class SourceSinkConfig:
    sources: Dict[str, Set[str]] = field(default_factory=dict)
    sinks: Dict[str, Set[str]] = field(default_factory=dict)
    sanitizers: Dict[str, Set[str]] = field(default_factory=dict)

    def is_source(self, lang: str, symbol: str) -> bool:
        return symbol in self.sources.get(lang, set())

    def is_sink(self, lang: str, symbol: str) -> bool:
        return symbol in self.sinks.get(lang, set())

    def is_sanitizer(self, lang: str, symbol: str) -> bool:
        return symbol in self.sanitizers.get(lang, set())


DEFAULT_SOURCE_SINK_CONFIG = SourceSinkConfig(
    sources={
        "python": {"input", "sys.stdin", "flask.request.args", "flask.request.form"},
        "typescript": {"window.location", "document.cookie", "process.env"},
        "java": {"System.in", "HttpServletRequest.getParameter"},
        "go": {"os.Args", "http.Request.Form", "http.Request.Body"},
        "ruby": {"ARGV", "STDIN", "params"},
    },
    sinks={
        "python": {"subprocess.Popen", "os.system", "eval", "exec", "cursor.execute"},
        "typescript": {"eval", "Function", "document.write", "innerHTML"},
        "java": {"Runtime.exec", "ProcessBuilder.start", "Statement.execute"},
        "go": {"exec.Command", "db.Exec", "template.Execute"},
        "ruby": {"eval", "system", "exec", "Kernel.send"},
    },
    sanitizers={
        "python": {"html.escape", "markupsafe.escape"},
        "typescript": {"DOMPurify.sanitize"},
        "java": {"ESAPI.encoder().encodeForHTML"},
        "go": {"template.HTMLEscapeString"},
        "ruby": {"ERB::Util.html_escape"},
    },
)
