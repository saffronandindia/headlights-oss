"""The Headlights SDK Client.

Local-only at v1. Holds a single in-memory Chain per active session. The
hosted-platform client (which POSTs to the Headlights API) is a v2 concern
and will share this API surface.
"""

from __future__ import annotations

import time
import traceback
from contextlib import contextmanager
from dataclasses import dataclass
from functools import wraps
from typing import Any, Callable, Iterator, TypeVar

from headlights_chain import (
    Chain,
    Outcome,
    SigningKey,
    TrustLevel,
)
from headlights_chain.enums import ActionType, ErrorCategory

from headlights_sdk.hashing import hash_call_inputs, hash_value

F = TypeVar("F", bound=Callable[..., Any])


class NoActiveSessionError(RuntimeError):
    """Raised when a recording call happens with no active session and
    auto_session is disabled."""


@dataclass
class _RecordOptions:
    """Per-decorator options resolved at decoration time."""

    action_type: ActionType
    trust_level: TrustLevel
    tool_name: str | None  # for tool_call/tool_response records


class Client:
    """Records AI agent conduct to an in-memory chain.

    Parameters
    ----------
    agent_id
        URI identifying the agent (e.g. "urn:headlights:agent:loan-analyser").
    agent_version
        SemVer 2.0.0 version of the agent.
    signing_key
        Optional ECDSA P-256 signing key. When set, every record is signed.
    default_trust_level
        Default trust level applied to records when the decorator does not
        override it. L1 (self-signed) is the SDK default.
    auto_session
        When True (default), the first decorated call auto-opens a session.
        When False, calls without an active session raise NoActiveSessionError.
    """

    def __init__(
        self,
        *,
        agent_id: str,
        agent_version: str,
        signing_key: SigningKey | None = None,
        default_trust_level: TrustLevel = TrustLevel.L1,
        auto_session: bool = True,
    ) -> None:
        self.agent_id = agent_id
        self.agent_version = agent_version
        self._signing_key = signing_key
        self._default_trust_level = default_trust_level
        self._auto_session = auto_session
        self._chain: Chain | None = None

    # ── Session management ──────────────────────────────────────────────

    @contextmanager
    def session(
        self,
        *,
        trust_level: TrustLevel | str | None = None,
        genesis_detail: dict[str, Any] | None = None,
    ) -> Iterator["Client"]:
        """Context manager that opens a session and closes it on exit.

        Raises RuntimeError if a session is already active.
        """
        if self._chain is not None and not self._chain.is_closed:
            raise RuntimeError("a session is already active; close it before opening another")
        self._start_session(trust_level=trust_level, genesis_detail=genesis_detail)
        try:
            yield self
        finally:
            if self._chain is not None and not self._chain.is_closed:
                self._chain.close()

    def _start_session(
        self,
        *,
        trust_level: TrustLevel | str | None = None,
        genesis_detail: dict[str, Any] | None = None,
    ) -> None:
        self._chain = Chain.genesis(
            agent_id=self.agent_id,
            agent_version=self.agent_version,
            signing_key=self._signing_key,
            trust_level=trust_level or self._default_trust_level,
            genesis_detail=genesis_detail,
        )

    def close(self) -> None:
        """Close the active session, writing the session_end record.

        Idempotent: a no-op if no session is open or the session is already closed.
        """
        if self._chain is not None and not self._chain.is_closed:
            self._chain.close()

    @property
    def is_session_active(self) -> bool:
        return self._chain is not None and not self._chain.is_closed

    @property
    def chain(self) -> Chain | None:
        """The active chain, or None if no session has been opened."""
        return self._chain

    def export(self) -> list[dict[str, Any]]:
        """Export the current chain's records as canonical-form dicts.

        Suitable input for `headlights-verify`. Raises RuntimeError if no
        chain has been created yet.
        """
        if self._chain is None:
            raise RuntimeError("no chain to export; call a decorated function or open a session first")
        return self._chain.export_records()

    # ── Decoration ──────────────────────────────────────────────────────

    def record(
        self,
        func: F | None = None,
        *,
        action_type: ActionType | str = ActionType.TOOL_CALL,
        trust_level: TrustLevel | str | None = None,
        tool_name: str | None = None,
    ) -> F | Callable[[F], F]:
        """Decorator factory. Use as `@client.record` or `@client.record(...)`.

        Wraps a function so that each call appends a `tool_call` + `tool_response`
        pair to the active chain (or an `error` record if the function raises).
        """
        options = _RecordOptions(
            action_type=ActionType(action_type) if not isinstance(action_type, ActionType) else action_type,
            trust_level=TrustLevel(trust_level) if isinstance(trust_level, str) else (trust_level or self._default_trust_level),
            tool_name=tool_name,
        )

        def decorate(fn: F) -> F:
            resolved_tool_name = options.tool_name or fn.__name__

            @wraps(fn)
            def wrapper(*args: Any, **kwargs: Any) -> Any:
                self._ensure_session()
                input_hash = hash_call_inputs(args, kwargs)
                call_pos, _ = self._append_tool_call(
                    tool_name=resolved_tool_name,
                    input_hash=input_hash,
                    trust_level=options.trust_level,
                )
                start = time.perf_counter()
                try:
                    result = fn(*args, **kwargs)
                except Exception as exc:  # noqa: BLE001 — we re-raise after recording
                    latency_ms = int((time.perf_counter() - start) * 1000)
                    self._append_error(
                        tool_name=resolved_tool_name,
                        call_pos=call_pos,
                        exc=exc,
                        latency_ms=latency_ms,
                        trust_level=options.trust_level,
                    )
                    raise

                latency_ms = int((time.perf_counter() - start) * 1000)
                self._append_tool_response(
                    tool_name=resolved_tool_name,
                    call_pos=call_pos,
                    result=result,
                    latency_ms=latency_ms,
                    trust_level=options.trust_level,
                )
                return result

            return wrapper  # type: ignore[return-value]

        if func is not None:
            # Used as @client.record without parentheses.
            return decorate(func)
        return decorate

    # ── Internals ───────────────────────────────────────────────────────

    def _ensure_session(self) -> None:
        if self._chain is None or self._chain.is_closed:
            if not self._auto_session:
                raise NoActiveSessionError(
                    "no active session; either enable auto_session or use `with client.session():`"
                )
            self._start_session()

    def _append_tool_call(
        self,
        *,
        tool_name: str,
        input_hash: str,
        trust_level: TrustLevel,
    ) -> tuple[int, str]:
        assert self._chain is not None
        return self._chain.append(
            action_type=ActionType.TOOL_CALL,
            action_detail={
                "tool_name": tool_name,
                "parameters_hash": f"sha256:{input_hash}",
            },
            outcome=Outcome.SUCCESS,
            trust_level=trust_level,
            input_hash=f"sha256:{input_hash}",
        )

    def _append_tool_response(
        self,
        *,
        tool_name: str,
        call_pos: int,
        result: Any,
        latency_ms: int,
        trust_level: TrustLevel,
    ) -> tuple[int, str]:
        assert self._chain is not None
        output_hash = hash_value(result)
        return self._chain.append(
            action_type=ActionType.TOOL_RESPONSE,
            action_detail={
                "tool_name": tool_name,
                "response_hash": f"sha256:{output_hash}",
                "parent_call_id": self._chain.records()[call_pos].record_id,
            },
            outcome=Outcome.SUCCESS,
            trust_level=trust_level,
            latency_ms=latency_ms,
            output_hash=f"sha256:{output_hash}",
        )

    def _append_error(
        self,
        *,
        tool_name: str,
        call_pos: int,
        exc: BaseException,
        latency_ms: int,
        trust_level: TrustLevel,
    ) -> tuple[int, str]:
        assert self._chain is not None
        return self._chain.append(
            action_type=ActionType.ERROR,
            action_detail={
                "error_code": type(exc).__name__,
                "error_message": str(exc),
                "error_category": ErrorCategory.INTERNAL.value,
                "recoverable": False,
                "tool_name": tool_name,
                "parent_call_id": self._chain.records()[call_pos].record_id,
                "stack_hash": f"sha256:{hash_value(traceback.format_exc())}",
            },
            outcome=Outcome.FAILURE,
            trust_level=trust_level,
            latency_ms=latency_ms,
        )
