"""HostedClient — same @record decorator API as Client, but every action POSTs
to a Headlights server instead of being held in memory.

Synchronous httpx client; suitable for normal application code. An async
version is a v2 concern.

Example:

    from headlights_sdk import HostedClient

    client = HostedClient.register(
        api_url="https://api.useheadlights.com",
        agent_name="loan-analyser",
        owner_email="ops@example.com",
        purpose="approve consumer loans up to $1.5M",
        agent_version="3.1.0",
    )
    # The returned client has .agent_id and .api_key set. Persist them
    # somewhere — register() is one-shot and the API key is shown once.

    @client.record
    def lookup_credit_score(applicant_id: str) -> int:
        ...

    score = lookup_credit_score("APP-001")
    client.close()
"""

from __future__ import annotations

import time
import traceback
from contextlib import contextmanager
from dataclasses import dataclass
from functools import wraps
from typing import Any, Callable, Iterator, TypeVar

import httpx

from headlights_chain.enums import ActionType, ErrorCategory, Outcome, TrustLevel

from headlights_sdk.hashing import hash_call_inputs, hash_value

F = TypeVar("F", bound=Callable[..., Any])


class HostedClientError(RuntimeError):
    """Raised when the server returns a non-2xx response to an SDK call."""

    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(f"HTTP {status_code}: {message}")
        self.status_code = status_code
        self.server_message = message


@dataclass(frozen=True)
class _RecordOptions:
    action_type: ActionType
    trust_level: TrustLevel
    tool_name: str | None


class HostedClient:
    """Hosted variant of the SDK Client. Mirrors the local Client API."""

    def __init__(
        self,
        *,
        api_url: str,
        api_key: str,
        agent_id: str,
        agent_version: str,
        default_trust_level: TrustLevel = TrustLevel.L1,
        auto_session: bool = True,
        http_client: httpx.Client | None = None,
        timeout: float = 30.0,
    ) -> None:
        self.api_url = api_url.rstrip("/")
        self.api_key = api_key
        self.agent_id = agent_id
        self.agent_version = agent_version
        self._default_trust_level = default_trust_level
        self._auto_session = auto_session
        self._session_id: str | None = None
        self._session_closed = False
        self._owns_http_client = http_client is None
        self._http = http_client or httpx.Client(
            base_url=self.api_url,
            timeout=timeout,
            headers={"Authorization": f"Bearer {api_key}"},
        )

    # ── Construction helpers ────────────────────────────────────────────

    @classmethod
    def register(
        cls,
        *,
        api_url: str,
        agent_name: str,
        owner_email: str,
        purpose: str,
        agent_version: str = "0.0.1",
        public_key_pem: str | None = None,
        timeout: float = 30.0,
    ) -> "HostedClient":
        """Register a new agent on the server, return a ready HostedClient.

        The plaintext API key is held only on the returned client (in
        `.api_key`). Persist it before the process exits.
        """
        with httpx.Client(base_url=api_url.rstrip("/"), timeout=timeout) as bootstrap:
            response = bootstrap.post(
                "/v1/agents",
                json={
                    "agent_name": agent_name,
                    "owner_email": owner_email,
                    "purpose": purpose,
                    "agent_version": agent_version,
                    "public_key_pem": public_key_pem,
                },
            )
        if response.status_code != 201:
            raise HostedClientError(response.status_code, response.text)
        body = response.json()
        return cls(
            api_url=api_url,
            api_key=body["api_key"],
            agent_id=body["agent_id"],
            agent_version=agent_version,
            timeout=timeout,
        )

    def close(self) -> None:
        """Close the active session (idempotent) and the HTTP client we own."""
        if self._session_id and not self._session_closed:
            try:
                self._close_session(self._session_id)
            except HostedClientError:
                # If close fails the chain on the server is still valid up to
                # the last successfully-appended record. Swallow so callers
                # using `with client:` don't see surprises during teardown.
                pass
        if self._owns_http_client:
            self._http.close()

    def __enter__(self) -> "HostedClient":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    @property
    def is_session_active(self) -> bool:
        return self._session_id is not None and not self._session_closed

    @property
    def session_id(self) -> str | None:
        return self._session_id

    # ── Sessions ────────────────────────────────────────────────────────

    @contextmanager
    def session(
        self,
        *,
        trust_level: TrustLevel | str | None = None,
        genesis_detail: dict[str, Any] | None = None,
    ) -> Iterator["HostedClient"]:
        if self.is_session_active:
            raise RuntimeError("a session is already active")
        self._open_session(
            trust_level=trust_level or self._default_trust_level,
            genesis_detail=genesis_detail or {},
        )
        try:
            yield self
        finally:
            if self._session_id and not self._session_closed:
                self._close_session(self._session_id)

    def _open_session(
        self,
        *,
        trust_level: TrustLevel | str,
        genesis_detail: dict[str, Any],
    ) -> None:
        tl = trust_level.value if isinstance(trust_level, TrustLevel) else trust_level
        response = self._http.post(
            f"/v1/agents/{self.agent_id}/sessions",
            json={"trust_level": tl, "genesis_detail": genesis_detail},
        )
        self._raise_on_error(response)
        body = response.json()
        self._session_id = body["session_id"]
        self._session_closed = False

    def _close_session(self, session_id: str) -> dict[str, Any]:
        response = self._http.post(
            f"/v1/agents/{self.agent_id}/sessions/{session_id}/close",
        )
        self._raise_on_error(response)
        self._session_closed = True
        return response.json()

    # ── Recording ───────────────────────────────────────────────────────

    def record(
        self,
        func: F | None = None,
        *,
        action_type: ActionType | str = ActionType.TOOL_CALL,
        trust_level: TrustLevel | str | None = None,
        tool_name: str | None = None,
    ) -> F | Callable[[F], F]:
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
                call_response = self._post_action(
                    action_type=ActionType.TOOL_CALL,
                    action_detail={
                        "tool_name": resolved_tool_name,
                        "parameters_hash": f"sha256:{input_hash}",
                    },
                    outcome=Outcome.SUCCESS,
                    trust_level=options.trust_level,
                    input_hash=f"sha256:{input_hash}",
                )
                call_record_id = call_response["record_id"]
                start = time.perf_counter()
                try:
                    result = fn(*args, **kwargs)
                except Exception as exc:
                    latency_ms = int((time.perf_counter() - start) * 1000)
                    self._post_action(
                        action_type=ActionType.ERROR,
                        action_detail={
                            "error_code": type(exc).__name__,
                            "error_message": str(exc),
                            "error_category": ErrorCategory.INTERNAL.value,
                            "recoverable": False,
                            "tool_name": resolved_tool_name,
                            "parent_call_id": call_record_id,
                            "stack_hash": f"sha256:{hash_value(traceback.format_exc())}",
                        },
                        outcome=Outcome.FAILURE,
                        trust_level=options.trust_level,
                        latency_ms=latency_ms,
                    )
                    raise

                latency_ms = int((time.perf_counter() - start) * 1000)
                output_hash = hash_value(result)
                self._post_action(
                    action_type=ActionType.TOOL_RESPONSE,
                    action_detail={
                        "tool_name": resolved_tool_name,
                        "response_hash": f"sha256:{output_hash}",
                        "parent_call_id": call_record_id,
                    },
                    outcome=Outcome.SUCCESS,
                    trust_level=options.trust_level,
                    output_hash=f"sha256:{output_hash}",
                    latency_ms=latency_ms,
                )
                return result

            return wrapper  # type: ignore[return-value]

        if func is not None:
            return decorate(func)
        return decorate

    # ── Retrieval ──────────────────────────────────────────────────────

    def get_conduct(
        self,
        *,
        session_id: str | None = None,
        since: str | None = None,
        until: str | None = None,
    ) -> list[dict[str, Any]]:
        """Fetch records for this agent. Suitable input for `headlights-verify`."""
        if session_id is not None:
            response = self._http.get(
                f"/v1/agents/{self.agent_id}/sessions/{session_id}/conduct"
            )
        else:
            params: dict[str, str] = {}
            if since is not None:
                params["since"] = since
            if until is not None:
                params["until"] = until
            response = self._http.get(
                f"/v1/agents/{self.agent_id}/conduct", params=params
            )
        self._raise_on_error(response)
        return response.json()["records"]

    # ── Internals ──────────────────────────────────────────────────────

    def _ensure_session(self) -> None:
        if not self.is_session_active:
            if not self._auto_session:
                raise RuntimeError(
                    "no active session; enable auto_session or use `with client.session():`"
                )
            self._open_session(
                trust_level=self._default_trust_level, genesis_detail={}
            )

    def _post_action(
        self,
        *,
        action_type: ActionType,
        action_detail: dict[str, Any],
        outcome: Outcome,
        trust_level: TrustLevel,
        input_hash: str | None = None,
        output_hash: str | None = None,
        latency_ms: int | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "session_id": self._session_id,
            "action_type": action_type.value,
            "action_detail": action_detail,
            "outcome": outcome.value,
            "trust_level": trust_level.value,
        }
        if input_hash is not None:
            payload["input_hash"] = input_hash
        if output_hash is not None:
            payload["output_hash"] = output_hash
        if latency_ms is not None:
            payload["latency_ms"] = latency_ms

        response = self._http.post(
            f"/v1/agents/{self.agent_id}/actions", json=payload
        )
        self._raise_on_error(response)
        return response.json()

    @staticmethod
    def _raise_on_error(response: httpx.Response) -> None:
        if response.status_code >= 400:
            raise HostedClientError(response.status_code, response.text)
