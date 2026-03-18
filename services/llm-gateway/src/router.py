"""Smart model router — picks the best model based on prompt content."""

import re

from ai_lab_common.config import settings

# Keywords that signal a code/technical prompt.
# Matched as whole words (case-insensitive) to avoid false positives
# like "class" in "classical music".
_CODE_KEYWORDS = {
    # Languages & runtimes
    "python", "javascript", "typescript", "java", "golang", "rust", "ruby",
    "php", "swift", "kotlin", "scala", "perl", "lua", "haskell", "elixir",
    "c++", "c#", "bash", "powershell", "html", "css", "sql",
    # Core programming concepts
    "function", "variable", "array", "loop", "class", "method", "object",
    "interface", "enum", "struct", "pointer", "recursion", "algorithm",
    "inheritance", "polymorphism", "exception", "async", "await",
    # Dev actions
    "code", "debug", "refactor", "compile", "deploy", "test", "lint",
    "commit", "merge", "rebase", "dockerfile", "makefile",
    # Tools & infra
    "git", "docker", "kubernetes", "terraform", "ansible", "nginx",
    "apache", "systemd", "cron", "ssh", "grep", "sed", "awk",
    # Data & APIs
    "api", "endpoint", "http", "rest", "graphql", "json", "yaml", "xml",
    "regex", "csv", "dataframe", "pandas", "numpy",
    # Error signals
    "error", "traceback", "stacktrace", "exception", "segfault", "bug",
    "stderr", "exitcode",
    # System
    "terminal", "command", "shell", "linux", "ubuntu", "centos",
    "pip", "npm", "cargo", "maven", "gradle",
}

# Pre-compile a single regex that matches any code keyword as a whole word.
_CODE_PATTERN = re.compile(
    r"\b(" + "|".join(re.escape(kw) for kw in _CODE_KEYWORDS) + r")\b",
    re.IGNORECASE,
)

# Minimum number of distinct keyword matches to classify as code.
_CODE_THRESHOLD = 1


def select_model(message: str) -> tuple[str, str]:
    """Return (model_name, reason) based on prompt content.

    Returns the code model if code-related keywords are detected,
    otherwise the default general model.
    """
    matches = set(_CODE_PATTERN.findall(message.lower()))
    if len(matches) >= _CODE_THRESHOLD:
        return settings.ROUTE_CODE_MODEL, f"code keywords: {', '.join(sorted(matches))}"
    return settings.ROUTE_DEFAULT_MODEL, "general"
