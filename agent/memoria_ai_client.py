from __future__ import annotations

import os
import sys
from typing import Any, Dict, List

# Shared memory client lives in /mnt/raid0/memoria_ai
if "/mnt/raid0" not in sys.path:
    sys.path.insert(0, "/mnt/raid0")

from memoria_ai import MemoriaClient  # type: ignore


def get_memoria_client(project: str = "programmatore_di_arduini", author: str = "claude") -> MemoriaClient:
    return MemoriaClient(
        project=project,
        author=author,
        base_url=os.getenv("MEMORY_SERVER_URL", "http://127.0.0.1:7701"),
    )


def remember(text: str, memory_type: str = "session", tags: List[str] | None = None) -> Dict[str, Any]:
    return get_memoria_client().remember(text=text, memory_type=memory_type, tags=tags or [])


def recall(query: str, n: int = 5, lazy: bool = True) -> List[Dict[str, Any]]:
    return get_memoria_client().recall(query=query, n=n, hybrid_mode=True, lazy=lazy)


def handoff(text: str) -> Dict[str, Any]:
    return get_memoria_client().handoff(text=text, action="handoff")
