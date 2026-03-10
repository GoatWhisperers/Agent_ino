"""Shared dataclasses used across all agent modules."""

from dataclasses import dataclass, field
from typing import Optional, List


@dataclass
class CompileResult:
    """Result of a sketch compilation attempt."""

    success: bool
    binary_path: Optional[str]
    errors: List[dict]
    warnings: List[dict]
    raw_stdout: str
    raw_stderr: str


@dataclass
class LLMResponse:
    """Parsed response from an LLM that uses <think>...</think> tags."""

    thinking: str      # contenuto <think>...</think>
    response: str      # risposta finale (dopo </think>)
    raw: str           # output grezzo completo


@dataclass
class TaskContext:
    """All contextual information needed to tackle a programming task."""

    task: str
    mode: str          # "NEW" | "CONTINUE" | "MODIFY"
    board_fqbn: str = "arduino:avr:uno"
    board_port: str = ""
    existing_code: Optional[str] = None
    existing_logs: Optional[List[dict]] = None
    similar_snippets: List[dict] = field(default_factory=list)
    relevant_docs: List[str] = field(default_factory=list)


@dataclass
class EvalResult:
    """Result of an evaluation step performed by an LLM judge."""

    success: bool
    reason: str
    suggestions: str
    thinking: str


@dataclass
class RunLog:
    """Full log of a single autonomous run (task → compile → upload cycle)."""

    run_id: str
    task: str
    mode: str
    iterations: List[dict]       # ogni iterazione compile/fix
    final_code: Optional[str]
    serial_output: Optional[str]
    success: bool
    thinking_log: List[dict]     # tutti i thinking dei LLM
