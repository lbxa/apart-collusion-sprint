"""Reusable asynchronous HTTP client for the Rust game's versioned API.

Persist each write's idempotency key before submitting it. If the response is
lost, submit the same request with the same key to recover its original result.
Game actions return durable handles for ``get_operation``, ``reconcile_operation``,
and ``wait_operation``. Chat writes return chat/message models immediately.
Python keeps no episode mappings, ballots, or private transcripts in this client.
"""

from __future__ import annotations

import asyncio
import hashlib
import math
from collections.abc import Awaitable, Mapping
from types import MappingProxyType
from typing import Any
from urllib.parse import urlsplit

import aiohttp
from pydantic import ValidationError

from .generated import (
    ApiProblem,
    BalancesView,
    BlockRange,
    ChallengeRequest,
    ChatAuditReport,
    ChatMessage,
    ChatPage,
    ChatView,
    ClaimRequest,
    CommitmentRequest,
    CreateChat,
    EmptyRequest,
    EpisodeView,
    ErrorResponse,
    ForumAuditReport,
    ForumMessage,
    ForumMessagePage,
    ForumSendMessage,
    GeneratedAPI,
    HealthResponse,
    MessagePage,
    OperationView,
    ParticipantView,
    RegisterEpisode,
    ReplayResponse,
    SendMessage,
    SettlementView,
    TransferRequest,
    Verdict,
)


class CoreClientError(RuntimeError):
    """A response cannot safely be used as an engine result."""


class CoreHTTPError(CoreClientError):
    """An HTTP failure, with validated API details available without logging them."""

    def __init__(
        self,
        status: int,
        problem: ApiProblem | None,
        *,
        method: str,
        path: str,
        idempotency_key: str | None,
    ):
        super().__init__(f"Engine HTTP {status}")
        self.status = status
        self.problem = problem
        self.method = method
        self.path = path
        self.idempotency_key = idempotency_key


class CoreTransportError(CoreClientError):
    """The request outcome is unknown; reuse its saved key rather than a new key."""

    def __init__(self, *, method: str, path: str, idempotency_key: str | None):
        super().__init__(
            "Engine transport failed; retry the same request with its original idempotency key "
            "when applicable, or inspect a saved operation"
        )
        self.method = method
        self.path = path
        self.idempotency_key = idempotency_key
        self.operation: OperationView | None = None


class CoreOperationError(CoreClientError):
    """A durable operation failed; its full evidence remains inspectable."""

    def __init__(self, operation: OperationView):
        super().__init__(f"Operation {operation.operation_id} {operation.status}")
        self.operation = operation


class CoreOperationTimeout(CoreClientError):
    """Waiting ended while the server still owns a resumable operation."""

    def __init__(self, operation_id: str, operation: OperationView | None):
        super().__init__(
            f"Operation {operation_id} is still pending; resume with the same operation ID"
        )
        self.operation_id = operation_id
        self.operation = operation


def _credential(token: str | None) -> str | None:
    if token is not None and (not token or any(not 0x21 <= ord(char) <= 0x7E for char in token)):
        raise ValueError(
            "Bearer credentials must contain visible ASCII characters without whitespace"
        )
    return token


def _key(value: str) -> str:
    if (
        not isinstance(value, str)
        or not 1 <= len(value) <= 128
        or any(not 0x21 <= ord(char) <= 0x7E for char in value)
    ):
        raise ValueError(
            "Idempotency keys must contain 1–128 visible ASCII characters without whitespace"
        )
    return value


def _chat_pagination(after: int | str | None, limit: int | None, *, listing: bool = False) -> None:
    if limit is not None and (type(limit) is not int or not 1 <= limit <= 100):
        raise ValueError("Chat page limits must be integers from 1 to 100")
    if after is not None:
        if listing:
            if not isinstance(after, str) or len(after) > 128:
                raise ValueError("Chat listing cursors must be strings of at most 128 characters")
        elif type(after) is not int or not 0 <= after <= 2**63 - 1:
            raise ValueError("Chat sequence cursors must be nonnegative signed 64-bit integers")


class CoreClient:
    """Connect to an existing deployment using explicitly supplied credentials.

    Game actions return durable operation handles immediately. ``settle``
    submits only settlement; callers choose when to commit, reveal, and settle.
    ``wait_operation`` accepts a saved ID after reconnecting and returns only a
    successful confirmed receipt. Chat calls return immediate typed results and
    require explicit participant or operator credentials. Financial values remain
    decimal integer strings.
    """

    def __init__(
        self,
        base_url: str,
        *,
        operator_token: str | None = None,
        participant_tokens: Mapping[str, str] | None = None,
        request_timeout: float = 15,
        operation_timeout: float = 30,
        poll_interval: float = 0.1,
    ):
        try:
            url = urlsplit(base_url)
            if (
                url.scheme not in {"http", "https"}
                or not url.hostname
                or url.username is not None
                or url.password is not None
                or url.query
                or url.fragment
                or url.path not in {"", "/"}
            ):
                raise ValueError
            _ = url.port  # Validate the optional port without exposing the input.
        except (ValueError, TypeError):
            raise ValueError(
                "Engine URL must be an HTTP(S) origin without credentials, query, or fragment"
            ) from None
        if request_timeout <= 0 or operation_timeout <= 0 or poll_interval < 0:
            raise ValueError("Timeouts must be positive and the polling interval nonnegative")
        self._base_url = base_url.rstrip("/")
        self._operator_token = _credential(operator_token)
        self._participant_tokens = MappingProxyType(
            {actor: _credential(token) for actor, token in (participant_tokens or {}).items()}
        )
        self._request_timeout = request_timeout
        self._operation_timeout = operation_timeout
        self._poll_interval = poll_interval
        self._session: aiohttp.ClientSession | None = None
        self._api = GeneratedAPI(self._request)

    @property
    def api_url(self) -> str:
        return self._base_url

    @property
    def api(self) -> GeneratedAPI:
        """All generated endpoint calls; advanced callers supply per-call credentials."""
        return self._api

    async def start(self) -> None:
        """Open the HTTP session; never start or own a game service process."""
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=self._request_timeout)
            )

    async def close(self) -> None:
        if self._session is not None:
            await self._session.close()
            self._session = None

    async def __aenter__(self) -> CoreClient:
        await self.start()
        return self

    async def __aexit__(self, *args) -> None:
        await self.close()

    def _operator(self) -> str:
        if self._operator_token is None:
            raise ValueError("This action requires a configured operator credential")
        return self._operator_token

    def _participant(self, actor_id: str) -> str:
        token = self._participant_tokens.get(actor_id)
        if token is None:
            raise ValueError("This action requires a configured credential for the participant")
        return token

    async def _request(
        self,
        method: str,
        path: str,
        *,
        token: str | None = None,
        body: dict | None = None,
        idempotency_key: str | None = None,
        response_format: str = "json",
    ) -> object:
        await self.start()
        headers = {}
        if token is not None:
            headers["Authorization"] = f"Bearer {token}"
        if idempotency_key is not None:
            headers["Idempotency-Key"] = _key(idempotency_key)
        try:
            async with self._session.request(
                method,
                self._base_url + path,
                headers=headers,
                json=body,
                allow_redirects=False,
            ) as response:
                if not 200 <= response.status < 300:
                    problem = None
                    try:
                        problem = ErrorResponse.model_validate(await response.json()).error
                    except (ValueError, aiohttp.ContentTypeError):
                        pass
                    raise CoreHTTPError(
                        response.status,
                        problem,
                        method=method,
                        path=path,
                        idempotency_key=idempotency_key,
                    )
                try:
                    if response_format == "text":
                        return await response.text()
                    return await response.json()
                except (ValueError, aiohttp.ContentTypeError):
                    raise CoreClientError("Engine returned invalid JSON") from None
        except (aiohttp.ClientError, TimeoutError):
            raise CoreTransportError(
                method=method, path=path, idempotency_key=idempotency_key
            ) from None

    @staticmethod
    async def _validated[T](call: Awaitable[T]) -> T:
        try:
            return await call
        except ValidationError:
            # Never embed response bodies, ballots, or credentials in exceptions.
            raise CoreClientError("Invalid /v1 response") from None

    async def _command(
        self,
        call: Awaitable[OperationView],
        episode_id: str,
        kind: str,
        actor_id: str | None = None,
    ) -> OperationView:
        operation = await self._validated(call)
        if (
            operation.episode_id != episode_id
            or operation.kind != kind
            or (actor_id is not None and operation.actor_id != actor_id)
        ):
            raise CoreClientError("Operation identity does not match the submitted command")
        return operation

    async def _episode_response[T: EpisodeView | SettlementView | BalancesView](
        self,
        call: Awaitable[T],
        episode_id: str,
    ) -> T:
        response = await self._validated(call)
        if response.episode_id != episode_id:
            raise CoreClientError("Episode identity does not match the requested resource")
        return response

    async def health(self) -> HealthResponse:
        return await self._validated(self._api.health())

    async def participants(self) -> list[ParticipantView]:
        return await self._validated(self._api.participants(token=None))

    async def get_openapi_document(self) -> dict[str, Any]:
        return await self._validated(self._api.openapi_document())

    async def get_docs(self) -> str:
        return await self._validated(self._api.docs())

    async def get_events(self, from_block: int, to_block: int) -> str:
        block_range = BlockRange(from_block=from_block, to_block=to_block)
        return await self._validated(
            self._api.events(from_block=block_range.from_block, to_block=block_range.to_block)
        )

    async def replay_events(self, from_block: int, to_block: int) -> ReplayResponse:
        return await self._validated(
            self._api.replay(
                BlockRange(from_block=from_block, to_block=to_block), token=self._operator()
            )
        )

    async def register_episode(
        self, registration: RegisterEpisode, *, idempotency_key: str
    ) -> OperationView:
        return await self._command(
            self._api.register(
                registration, token=self._operator(), idempotency_key=_key(idempotency_key)
            ),
            registration.episode_id,
            "register",
        )

    async def get_episode(self, episode_id: str) -> EpisodeView:
        return await self._episode_response(self._api.episode(episode_id, token=None), episode_id)

    async def get_settlement(self, episode_id: str) -> SettlementView:
        return await self._episode_response(
            self._api.settlement(episode_id, token=None), episode_id
        )

    async def get_balances(self, episode_id: str) -> BalancesView:
        return await self._episode_response(self._api.balances(episode_id, token=None), episode_id)

    async def post_claim(
        self, episode_id: str, creator_id: str, content: str, *, idempotency_key: str
    ) -> OperationView:
        return await self._command(
            self._api.claim(
                episode_id,
                ClaimRequest(content=content),
                token=self._participant(creator_id),
                idempotency_key=_key(idempotency_key),
            ),
            episode_id,
            "post_claim",
            creator_id,
        )

    async def challenge(
        self, episode_id: str, challenger_id: str, evidence: str, *, idempotency_key: str
    ) -> OperationView:
        return await self._command(
            self._api.challenge(
                episode_id,
                ChallengeRequest(evidence=evidence),
                token=self._participant(challenger_id),
                idempotency_key=_key(idempotency_key),
            ),
            episode_id,
            "challenge",
            challenger_id,
        )

    async def commit(
        self,
        episode_id: str,
        juror_id: str,
        verdict: Verdict,
        assessment: str,
        *,
        idempotency_key: str,
    ) -> OperationView:
        return await self._command(
            self._api.commitment(
                episode_id,
                CommitmentRequest(verdict=verdict, assessment=assessment),
                token=self._participant(juror_id),
                idempotency_key=_key(idempotency_key),
            ),
            episode_id,
            "commit_vote",
            juror_id,
        )

    async def reveal(
        self, episode_id: str, juror_id: str, *, idempotency_key: str
    ) -> OperationView:
        return await self._command(
            self._api.reveal(
                episode_id,
                EmptyRequest(),
                token=self._participant(juror_id),
                idempotency_key=_key(idempotency_key),
            ),
            episode_id,
            "reveal_vote",
            juror_id,
        )

    async def settle(self, episode_id: str, *, idempotency_key: str) -> OperationView:
        return await self._command(
            self._api.settle(
                episode_id,
                EmptyRequest(),
                token=self._operator(),
                idempotency_key=_key(idempotency_key),
            ),
            episode_id,
            "settle",
        )

    async def expire(self, episode_id: str, *, idempotency_key: str) -> OperationView:
        return await self._command(
            self._api.expire(
                episode_id,
                EmptyRequest(),
                token=self._operator(),
                idempotency_key=_key(idempotency_key),
            ),
            episode_id,
            "expire",
        )

    async def withdraw(
        self, episode_id: str, participant_id: str, *, idempotency_key: str
    ) -> OperationView:
        return await self._command(
            self._api.withdraw(
                episode_id,
                EmptyRequest(),
                token=self._participant(participant_id),
                idempotency_key=_key(idempotency_key),
            ),
            episode_id,
            "withdraw",
            participant_id,
        )

    async def transfer_credits(
        self,
        episode_id: str,
        participant_id: str,
        recipient_id: str,
        amount_wei: int | str,
        *,
        idempotency_key: str,
    ) -> OperationView:
        return await self._command(
            self._api.transfer(
                episode_id,
                TransferRequest(recipient_id=recipient_id, amount_wei=str(amount_wei)),
                token=self._participant(participant_id),
                idempotency_key=_key(idempotency_key),
            ),
            episode_id,
            "transfer_credits",
            participant_id,
        )

    async def create_chat(
        self,
        episode_id: str,
        participant_ids: list[str],
        *,
        idempotency_key: str,
        actor_id: str | None = None,
        history_enabled: bool = False,
        communication_prohibited: bool = True,
    ) -> ChatView:
        """Create an immutable pair; actor_id chooses participant or operator provisioning.

        Prohibited communication is delivered and audited by the server. The
        participant history setting never removes the retained operator transcript.
        """
        token = self._operator() if actor_id is None else self._participant(actor_id)
        body = CreateChat(
            participant_ids=participant_ids,
            history_enabled=history_enabled,
            communication_prohibited=communication_prohibited,
        )
        result = await self._validated(
            self._api.create(episode_id, body, token=token, idempotency_key=_key(idempotency_key))
        )
        if (
            result.episode_id != episode_id
            or set(result.participant_ids) != set(participant_ids)
            or result.history_enabled != history_enabled
        ):
            raise CoreClientError(
                "Chat identity or history setting does not match the submitted request"
            )
        return result

    async def list_chats(
        self,
        episode_id: str,
        *,
        actor_id: str | None = None,
        after: str | None = None,
        limit: int | None = None,
    ) -> ChatPage:
        """Discover the participant's chats, or all episode chats for the operator."""
        _chat_pagination(after, limit, listing=True)
        token = self._operator() if actor_id is None else self._participant(actor_id)
        page = await self._validated(
            self._api.list(episode_id, after=after, limit=limit, token=token)
        )
        if any(
            chat.episode_id != episode_id
            or (actor_id is not None and actor_id not in chat.participant_ids)
            for chat in page.chats
        ):
            raise CoreClientError(
                "Chat listing does not match the requested episode or participant"
            )
        return page

    async def send_message(
        self, chat_id: str, sender_id: str, content: str, *, idempotency_key: str
    ) -> ChatMessage:
        """Send exact UTF-8 using the sender's participant credential; return immediately."""
        message = await self._validated(
            self._api.send(
                chat_id,
                SendMessage(content=content),
                token=self._participant(sender_id),
                idempotency_key=_key(idempotency_key),
            )
        )
        if message.sender_id != sender_id or message.content != content:
            raise CoreClientError("Message sender or content does not match the submitted request")
        return message

    async def get_messages(
        self,
        chat_id: str,
        participant_id: str,
        *,
        after: int | None = None,
        limit: int | None = None,
    ) -> MessagePage:
        """Read permitted history without reconstructing older messages in latest-only chats."""
        _chat_pagination(after, limit)
        page = await self._validated(
            self._api.messages(
                chat_id, after=after, limit=limit, token=self._participant(participant_id)
            )
        )
        if page.chat_id != chat_id or any(
            participant_id not in {message.sender_id, message.recipient_id}
            for message in page.messages
        ):
            raise CoreClientError("Message page does not match the requested chat or participant")
        return page

    async def poll_messages(
        self,
        chat_id: str,
        participant_id: str,
        *,
        after: int | None = None,
        limit: int | None = None,
        timeout: float = 30,  # noqa: ASYNC109 -- explicit polling deadline is part of the API
    ) -> MessagePage:
        """Poll participant reads until a nonempty page or timeout, without retaining history.

        Every read is auditable server-side. Save the returned next_after for the
        next poll. Timeout returns the latest valid empty page; timeout=0 does one
        read. No operator transcript is consulted or cached by this method.
        """
        if not math.isfinite(timeout) or timeout < 0:
            raise ValueError("Chat polling timeout must be finite and nonnegative")
        if timeout == 0:
            return await self.get_messages(chat_id, participant_id, after=after, limit=limit)
        last_page = None
        try:
            async with asyncio.timeout(timeout):
                while True:
                    last_page = await self.get_messages(
                        chat_id, participant_id, after=after, limit=limit
                    )
                    if last_page.messages:
                        return last_page
                    await asyncio.sleep(max(self._poll_interval, 0.001))
        except TimeoutError:
            if last_page is not None:
                return last_page
            raise CoreClientError(
                "Chat polling timed out before receiving a valid response"
            ) from None

    async def get_transcript(
        self, chat_id: str, *, after: int | None = None, limit: int | None = None
    ) -> MessagePage:
        """Read the retained operator transcript explicitly; server audits this access."""
        _chat_pagination(after, limit)
        page = await self._validated(
            self._api.transcript(chat_id, after=after, limit=limit, token=self._operator())
        )
        if page.chat_id != chat_id:
            raise CoreClientError("Transcript does not match the requested chat")
        return page

    async def get_chat_audit(
        self, episode_id: str, *, after: int | None = None, limit: int | None = None
    ) -> ChatAuditReport:
        """Read operator-only usage flags and metadata; this response has no message bodies."""
        _chat_pagination(after, limit)
        report = await self._validated(
            self._api.audit(episode_id, after=after, limit=limit, token=self._operator())
        )
        if report.episode_id != episode_id or any(
            event.episode_id != episode_id for event in report.events
        ):
            raise CoreClientError("Chat audit does not match the requested episode")
        return report

    async def send_forum_message(
        self,
        episode_id: str,
        sender_id: str,
        content: str,
        *,
        idempotency_key: str,
        round_num: int | None = None,
    ) -> ForumMessage:
        """Publish exact UTF-8 as the participant; caller-supplied rounds are annotations."""
        message = await self._validated(
            self._api.send_forum_message(
                episode_id,
                ForumSendMessage(content=content, round_num=round_num),
                token=self._participant(sender_id),
                idempotency_key=_key(idempotency_key),
            )
        )
        if (
            message.sender_id != sender_id
            or message.content != content
            or message.round_num != round_num
        ):
            raise CoreClientError(
                "Forum message does not match the submitted sender, content, or round"
            )
        return message

    @staticmethod
    def _forum_page(page: ForumMessagePage, episode_id: str, after: int | None) -> ForumMessagePage:
        cursor = 0 if after is None else after
        sequences = [message.sequence for message in page.messages]
        if (
            page.episode_id != episode_id
            or any(sequence <= cursor for sequence in sequences)
            or sequences != sorted(set(sequences))
            or page.next_after != (sequences[-1] if sequences else cursor)
            or (page.has_more and not sequences)
        ):
            raise CoreClientError("Forum history identity or pagination is inconsistent")
        return page

    async def get_forum_messages(
        self,
        episode_id: str,
        participant_id: str,
        *,
        after: int | None = None,
        limit: int | None = None,
    ) -> ForumMessagePage:
        """Read shared episode history under the participant's audited identity."""
        _chat_pagination(after, limit)
        page = await self._validated(
            self._api.get_forum_messages(
                episode_id, after=after, limit=limit, token=self._participant(participant_id)
            )
        )
        return self._forum_page(page, episode_id, after)

    async def get_forum_transcript(
        self, episode_id: str, *, after: int | None = None, limit: int | None = None
    ) -> ForumMessagePage:
        """Read as evaluator without recording a participant read."""
        _chat_pagination(after, limit)
        page = await self._validated(
            self._api.get_forum_transcript(
                episode_id, after=after, limit=limit, token=self._operator()
            )
        )
        return self._forum_page(page, episode_id, after)

    async def get_forum_audit(
        self, episode_id: str, *, after: int | None = None, limit: int | None = None
    ) -> ForumAuditReport:
        """Read operator-only usage metadata; pagination never changes all-time totals."""
        _chat_pagination(after, limit)
        report = await self._validated(
            self._api.get_forum_audit(episode_id, after=after, limit=limit, token=self._operator())
        )
        cursor = 0 if after is None else after
        sequences = [event.sequence for event in report.events]
        if (
            report.episode_id != episode_id
            or any(event.episode_id != episode_id for event in report.events)
            or any(sequence <= cursor for sequence in sequences)
            or sequences != sorted(set(sequences))
            or report.next_after != (sequences[-1] if sequences else cursor)
            or (report.has_more and not sequences)
        ):
            raise CoreClientError("Forum audit identity or pagination is inconsistent")
        return report

    async def get_operation(self, operation_id: str) -> OperationView:
        operation = await self._validated(self._api.operation(operation_id, token=None))
        if operation.operation_id != operation_id:
            raise CoreClientError("Operation identity changed during lookup")
        return operation

    @staticmethod
    def _identity(operation: OperationView) -> tuple[str, str, str, str]:
        return operation.operation_id, operation.episode_id, operation.actor_id, operation.kind

    @classmethod
    def _same_operation(cls, previous: OperationView, current: OperationView) -> bool:
        if cls._identity(previous) != cls._identity(current):
            return False
        saved = previous.transaction
        observed = current.transaction
        return saved is None or (
            observed is not None
            and (saved.transaction_hash, saved.sender, saved.nonce)
            == (observed.transaction_hash, observed.sender, observed.nonce)
        )

    async def reconcile_operation(
        self, operation: OperationView | str, *, idempotency_key: str | None = None
    ) -> OperationView:
        operation_id = operation if isinstance(operation, str) else operation.operation_id
        key = (
            hashlib.sha256(f"reconcile\0{operation_id}".encode()).hexdigest()
            if idempotency_key is None
            else idempotency_key
        )
        result = await self._validated(
            self._api.reconcile(
                operation_id, EmptyRequest(), token=self._operator(), idempotency_key=_key(key)
            )
        )
        if result.operation_id != operation_id or (
            not isinstance(operation, str) and not self._same_operation(operation, result)
        ):
            raise CoreClientError("Operation identity changed during reconciliation")
        return result

    @staticmethod
    def _confirmed(operation: OperationView) -> OperationView | None:
        if operation.status in {"failed", "reverted"}:
            raise CoreOperationError(operation)
        if operation.status == "confirmed":
            transaction = operation.transaction
            if (
                transaction is None
                or transaction.receipt is None
                or not transaction.receipt.success
                or not transaction.receipt.confirmed
                or transaction.receipt.transaction_hash != transaction.transaction_hash
            ):
                raise CoreClientError(
                    "Confirmed operation is missing a matching successful confirmed receipt"
                )
            return operation
        return None

    async def wait_operation(
        self,
        operation: OperationView | str,
        *,
        timeout: float | None = None,  # noqa: ASYNC109 -- resumable polling API
    ) -> OperationView:
        """Resume a saved handle or ID; operator credentials enable reconciliation.

        A participant-only client polls public evidence. An operator client also
        reconciles durable transactions, including rebroadcasting their original
        signed bytes when the Rust recovery mechanism decides that is necessary.
        """
        operation_id = operation if isinstance(operation, str) else operation.operation_id
        current = None if isinstance(operation, str) else operation
        try:
            async with asyncio.timeout(self._operation_timeout if timeout is None else timeout):
                if current is None:
                    current = await self.get_operation(operation_id)
                while True:
                    if confirmed := self._confirmed(current):
                        return confirmed
                    await asyncio.sleep(self._poll_interval)
                    previous = current
                    current = (
                        await self.reconcile_operation(current)
                        if self._operator_token is not None
                        else await self.get_operation(operation_id)
                    )
                    if not self._same_operation(previous, current):
                        raise CoreClientError("Operation identity changed while waiting")
        except TimeoutError:
            raise CoreOperationTimeout(operation_id, current) from None
        except CoreTransportError as error:
            error.operation = current
            raise
