"""Privacy-conscious logging.

Policy:
* Request and response bodies, prompts, completions and headers are never logged.
* Every log line carries the request ID (when one exists) for tracing.
* A redaction filter masks anything that looks like a credential before it is emitted,
  as a second line of defence against accidental leakage.
"""

from __future__ import annotations

import logging
import re
import sys
from contextvars import ContextVar

request_id_ctx: ContextVar[str] = ContextVar("request_id", default="-")

_SECRET_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9_\-]{8,}"),  # OpenAI / Anthropic style keys
    re.compile(r"AIza[0-9A-Za-z_\-]{20,}"),  # Google API keys
    re.compile(r"mk_[A-Za-z0-9_\-]{16,}"),  # ModelOps project keys
    re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._\-]{16,}"),
    re.compile(r"eyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}"),  # JWTs
]


def redact(text: str) -> str:
    for pattern in _SECRET_PATTERNS:
        text = pattern.sub(lambda m: (m.group(1) if m.lastindex else "") + "[REDACTED]", text)
    return text


class _ContextFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_ctx.get()
        message = record.getMessage()
        redacted = redact(message)
        if redacted != message:
            record.msg, record.args = redacted, ()
        return True


def configure_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s [%(name)s] [req=%(request_id)s] %(message)s"))
    handler.addFilter(_ContextFilter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level.upper())
    # Uvicorn's access log prints full URLs (which could contain query-string keys); keep it quiet.
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
