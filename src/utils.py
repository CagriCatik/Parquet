from __future__ import annotations

import os
from pathlib import Path
from typing import Iterable


def ensure_parent(path: os.PathLike | str) -> Path:
    path_obj = Path(path)
    if path_obj.parent:
        path_obj.parent.mkdir(parents=True, exist_ok=True)
    return path_obj


def file_size(path: os.PathLike | str) -> int:
    try:
        return Path(path).stat().st_size
    except OSError:
        return 0


def human_mb(nbytes: int | float | None) -> float:
    if not nbytes or nbytes <= 0:
        return float("nan")
    return float(nbytes) / (1024.0 * 1024.0)


def chunk_iterable(iterable: Iterable, chunk_size: int):
    chunk = []
    for item in iterable:
        chunk.append(item)
        if len(chunk) >= chunk_size:
            yield chunk
            chunk = []
    if chunk:
        yield chunk
