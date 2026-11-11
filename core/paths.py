from __future__ import annotations
import os, re
from pathlib import Path
from .errors import ServiceError

class PathError(ServiceError):
    def __init__(self, message: str): super().__init__("bad_request", message)

def path_key(rel: str) -> str:
    """Ключ сравнения путей: на Windows ФС регистронезависима."""
    return rel.casefold() if os.name == "nt" else rel

def safe_join(base: Path, rel: str) -> Path:
    """Никаких абсолютных путей, дисков, '..', NUL; результат строго внутри base."""
    if not isinstance(rel, str) or "\x00" in rel:
        raise PathError("invalid relative path")
    r = rel.replace("\\", "/")
    if r.startswith("/") or re.match(r"^[A-Za-z]:", r):
        raise PathError("absolute paths are not allowed")
    parts = [p for p in r.split("/") if p not in ("", ".")]
    if any(p == ".." for p in parts):
        raise PathError("parent traversal is not allowed")
    b = Path(os.path.normcase(str(base.resolve())))
    p = Path(os.path.normcase(str(base.joinpath(*parts).resolve())))
    if os.path.commonpath([str(p), str(b)]) != str(b):
        raise PathError("path escapes registered root")
    return p