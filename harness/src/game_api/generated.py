"""Generated from Rust OpenAPI. Run python scripts/generate-core-client.py; do not edit."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Annotated, Any, Literal, Never
from urllib.parse import quote, urlencode

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter


class WireModel(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", frozen=True,
                              hide_input_in_errors=True)


ChatAuditKind = Literal['chat_created', 'message_sent', 'messages_read', 'chats_listed', 'transcript_read', 'access_denied']


ForumAuditKind = Literal['message_sent', 'messages_read', 'transcript_read', 'access_denied']


Verdict = Literal['CREATOR_SUPPORTED', 'CHALLENGER_SUPPORTED']


class ApiProblem(WireModel):
    code: str
    message: str


class BalancesView(WireModel):
    entitlements: dict[str, Annotated[str, Field(pattern='^(0|[1-9][0-9]*)$')]]
    episode_id: str
    withdrawal_credits: dict[str, Annotated[str, Field(pattern='^(0|[1-9][0-9]*)$')]]


class BlockRange(WireModel):
    from_block: Annotated[int, Field(ge=0)]
    to_block: Annotated[int, Field(ge=0)]


class ChallengeRequest(WireModel):
    evidence: str


class ChatActorUsage(WireModel):
    actor_id: str
    created_chats: Annotated[int, Field(ge=0)]
    denied_requests: Annotated[int, Field(ge=0)]
    messages_returned: Annotated[int, Field(ge=0)]
    prohibited_read_requests: Annotated[int, Field(ge=0)]
    prohibited_sent_messages: Annotated[int, Field(ge=0)]
    read_requests: Annotated[int, Field(ge=0)]
    sent_messages: Annotated[int, Field(ge=0)]


class ChatAuditEvent(WireModel):
    actor_id: str
    actor_is_operator: bool
    chat_id: str | None
    communication_prohibited: bool
    created_at_ms: Annotated[int, Field(ge=0)]
    episode_id: str
    kind: ChatAuditKind
    message_bytes: Annotated[int, Field(ge=0)] | None
    message_hash: str | None
    message_sequence: Annotated[int, Field(ge=0)] | None
    policy_violation: bool
    recipient_id: str | None
    returned_sequences: list[Annotated[int, Field(ge=0)]]
    sequence: Annotated[int, Field(ge=0)]


class ChatAuditReport(WireModel):
    actors: list[ChatActorUsage]
    chat_count: Annotated[int, Field(ge=0)]
    chat_used: bool
    communication_used: bool
    episode_id: str
    events: list[ChatAuditEvent]
    has_more: bool
    message_count: Annotated[int, Field(ge=0)]
    next_after: Annotated[int, Field(ge=0)]
    prohibited_communication_used: bool


class ChatMessage(WireModel):
    content: str
    content_hash: str
    created_at_ms: Annotated[int, Field(ge=0)]
    message_id: str
    recipient_id: str
    sender_id: str
    sequence: Annotated[int, Field(ge=0)]


class ChatPage(WireModel):
    chats: list[ChatView]
    has_more: bool
    next_after: str | None


class ChatView(WireModel):
    chat_id: str
    created_at_ms: Annotated[int, Field(ge=0)]
    episode_id: str
    history_enabled: bool
    participant_ids: Annotated[list[str], Field(min_length=2, max_length=2)]


class ClaimRequest(WireModel):
    content: str


class CommitmentRequest(WireModel):
    assessment: str
    verdict: Verdict


class CreateChat(WireModel):
    communication_prohibited: bool = True
    history_enabled: bool = False
    participant_ids: Annotated[list[str], Field(min_length=2, max_length=2)]


class DeploymentView(WireModel):
    abi_version: Annotated[int, Field(ge=0)]
    chain_id: Annotated[int, Field(ge=0)]
    code_hash: str
    confirmation_depth: Annotated[int, Field(ge=0)]
    contract_address: str
    finality_policy: str


class EmptyRequest(WireModel):
    pass


class EpisodeView(WireModel):
    challenge_deadline: Annotated[int, Field(ge=0)]
    challenger_votes: Annotated[int, Field(ge=0)]
    commit_deadline: Annotated[int, Field(ge=0)]
    configuration: RegisterEpisode
    configuration_hash: str
    content: str | None
    content_hash: str | None
    creator_votes: Annotated[int, Field(ge=0)]
    deployment: DeploymentView
    episode_id: str
    evidence: str | None
    evidence_hash: str | None
    juror_bond_wei: Annotated[str, Field(pattern='^(0|[1-9][0-9]*)$')]
    jurors: list[JurorView]
    locked_liability_wei: Annotated[str, Field(pattern='^(0|[1-9][0-9]*)$')]
    onchain_episode_id: str
    phase: Literal['REGISTERED', 'OPEN', 'COMMIT', 'REVEAL', 'SETTLED_CREATOR', 'SETTLED_CHALLENGER', 'ABORTED', 'EXPIRED_UNCHALLENGED', 'EXPIRED_UNFUNDED']
    posting_deadline: Annotated[int, Field(ge=0)]
    required_votes: Annotated[int, Field(ge=0)]
    reveal_deadline: Annotated[int, Field(ge=0)]
    total_credited_wei: Annotated[str, Field(pattern='^(0|[1-9][0-9]*)$')]
    total_deposited_wei: Annotated[str, Field(pattern='^(0|[1-9][0-9]*)$')]


class ErrorResponse(WireModel):
    error: ApiProblem


class ForumActorUsage(WireModel):
    actor_id: str
    denied_requests: Annotated[int, Field(ge=0)]
    messages_returned: Annotated[int, Field(ge=0)]
    read_requests: Annotated[int, Field(ge=0)]
    sent_bytes: Annotated[int, Field(ge=0)]
    sent_messages: Annotated[int, Field(ge=0)]


class ForumAuditEvent(WireModel):
    actor_id: str
    actor_is_operator: bool
    created_at_ms: Annotated[int, Field(ge=0)]
    episode_id: str
    kind: ForumAuditKind
    message_bytes: Annotated[int, Field(ge=0)] | None
    message_hash: str | None
    message_sequence: Annotated[int, Field(ge=0)] | None
    returned_sequences: list[Annotated[int, Field(ge=0)]]
    round_num: Annotated[int, Field(ge=0)] | None
    sequence: Annotated[int, Field(ge=0)]


class ForumAuditReport(WireModel):
    active_sender_count: Annotated[int, Field(ge=0)]
    actors: list[ForumActorUsage]
    communication_used: bool
    episode_id: str
    events: list[ForumAuditEvent]
    first_message_at_ms: Annotated[int, Field(ge=0)] | None
    forum_used: bool
    has_more: bool
    last_message_at_ms: Annotated[int, Field(ge=0)] | None
    message_count: Annotated[int, Field(ge=0)]
    next_after: Annotated[int, Field(ge=0)]
    total_message_bytes: Annotated[int, Field(ge=0)]


class ForumMessage(WireModel):
    content: str
    content_hash: str
    created_at_ms: Annotated[int, Field(ge=0)]
    message_id: str
    round_num: Annotated[int, Field(ge=0)] | None
    sender_id: str
    sequence: Annotated[int, Field(ge=0)]


class ForumMessagePage(WireModel):
    episode_id: str
    has_more: bool
    messages: list[ForumMessage]
    next_after: Annotated[int, Field(ge=0)]


class ForumSendMessage(WireModel):
    content: str
    round_num: Annotated[int, Field(ge=1)] | None = None


class HealthResponse(WireModel):
    api_version: Annotated[str, Field(pattern='^v1$')]
    deployment: DeploymentView
    status: Annotated[str, Field(pattern='^ok$')]


class JurorView(WireModel):
    actor_id: str
    assessment_hash: str | None
    commitment: str | None
    revealed: bool
    verdict: None | Verdict


class MessagePage(WireModel):
    chat_id: str
    has_more: bool
    messages: list[ChatMessage]
    next_after: Annotated[int, Field(ge=0)]


class OperationView(WireModel):
    actor_id: str
    episode_id: str
    error: str | None
    kind: str
    operation_id: str
    status: Literal['accepted', 'prepared', 'submitted', 'included', 'confirmed', 'reverted', 'failed']
    transaction: None | TransactionView


class ParticipantView(WireModel):
    actor_id: str
    address: str


class ProtocolParameters(WireModel):
    beta_wei: Annotated[str, Field(pattern='^[1-9][0-9]*$')]
    challenge_duration_secs: Annotated[int, Field(ge=1, le=9007199254740991)]
    commit_duration_secs: Annotated[int, Field(ge=1, le=9007199254740991)]
    gamma_bps: Annotated[int, Field(ge=1, le=9999)]
    juror_bps: Annotated[int, Field(ge=0, le=10000)] = 3000
    posting_duration_secs: Annotated[int, Field(ge=1, le=9007199254740991)]
    protocol_bps: Annotated[int, Field(ge=0, le=10000)] = 1000
    reveal_duration_secs: Annotated[int, Field(ge=1, le=9007199254740991)]
    winner_bps: Annotated[int, Field(ge=0, le=10000)] = 6000


class ReceiptView(WireModel):
    block_hash: str
    block_number: Annotated[int, Field(ge=0)]
    confirmations: Annotated[int, Field(ge=0)]
    confirmed: bool
    effective_gas_price: Annotated[str, Field(pattern='^(0|[1-9][0-9]*)$')]
    gas_used: Annotated[str, Field(pattern='^(0|[1-9][0-9]*)$')]
    success: bool
    transaction_hash: str


class RegisterEpisode(WireModel):
    challenger_id: str
    creator_id: str
    episode_id: str
    experiment_id: str = ''
    juror_ids: list[str]
    parameters: ProtocolParameters
    provenance: dict[str, str] = {}
    scenario_id: str = ''
    treasury_id: str


class ReplayResponse(WireModel):
    events_recorded: Annotated[int, Field(ge=0)]
    from_block: Annotated[int, Field(ge=0)]
    to_block: Annotated[int, Field(ge=0)]


class SendMessage(WireModel):
    content: str


class SettlementView(WireModel):
    deployment: DeploymentView
    episode_id: str
    final_votes: dict[str, Verdict]
    forfeited_bonds: dict[str, Annotated[str, Field(pattern='^(0|[1-9][0-9]*)$')]]
    juror_payouts: dict[str, Annotated[str, Field(pattern='^(0|[1-9][0-9]*)$')]]
    outcome: Literal['REGISTERED', 'OPEN', 'COMMIT', 'REVEAL', 'SETTLED_CREATOR', 'SETTLED_CHALLENGER', 'ABORTED', 'EXPIRED_UNCHALLENGED', 'EXPIRED_UNFUNDED']
    protocol_fee: Annotated[str, Field(pattern='^(0|[1-9][0-9]*)$')]
    refunds: dict[str, Annotated[str, Field(pattern='^(0|[1-9][0-9]*)$')]]
    total_credited: Annotated[str, Field(pattern='^(0|[1-9][0-9]*)$')]
    total_deposited: Annotated[str, Field(pattern='^(0|[1-9][0-9]*)$')]
    winner_id: str | None
    winner_payout: Annotated[str, Field(pattern='^(0|[1-9][0-9]*)$')]


class TransactionView(WireModel):
    nonce: Annotated[int, Field(ge=0)]
    receipt: None | ReceiptView
    sender: str
    transaction_hash: str


class TransferRequest(WireModel):
    amount_wei: Annotated[str, Field(pattern='^[1-9][0-9]*$')]
    recipient_id: str


# Resolve references after all component models have been declared.
ApiProblem.model_rebuild()
BalancesView.model_rebuild()
BlockRange.model_rebuild()
ChallengeRequest.model_rebuild()
ChatActorUsage.model_rebuild()
ChatAuditEvent.model_rebuild()
ChatAuditReport.model_rebuild()
ChatMessage.model_rebuild()
ChatPage.model_rebuild()
ChatView.model_rebuild()
ClaimRequest.model_rebuild()
CommitmentRequest.model_rebuild()
CreateChat.model_rebuild()
DeploymentView.model_rebuild()
EmptyRequest.model_rebuild()
EpisodeView.model_rebuild()
ErrorResponse.model_rebuild()
ForumActorUsage.model_rebuild()
ForumAuditEvent.model_rebuild()
ForumAuditReport.model_rebuild()
ForumMessage.model_rebuild()
ForumMessagePage.model_rebuild()
ForumSendMessage.model_rebuild()
HealthResponse.model_rebuild()
JurorView.model_rebuild()
MessagePage.model_rebuild()
OperationView.model_rebuild()
ParticipantView.model_rebuild()
ProtocolParameters.model_rebuild()
ReceiptView.model_rebuild()
RegisterEpisode.model_rebuild()
ReplayResponse.model_rebuild()
SendMessage.model_rebuild()
SettlementView.model_rebuild()
TransactionView.model_rebuild()
TransferRequest.model_rebuild()


class GeneratedAPI:
    """Typed endpoint calls; transport owns credentials, sessions, and HTTP errors."""

    def __init__(self, request: Callable[..., Awaitable[Any]]):
        self._request = request

    async def events(self, *, from_block: Annotated[int, Field(ge=0)], to_block: Annotated[int, Field(ge=0)], token: str | None = None) -> str:
        path = '/v1/chain/events'
        query = {key: value for key, value in {'from_block': from_block, 'to_block': to_block}.items() if value is not None}
        if query:
            path += '?' + urlencode(query)
        data = await self._request('GET', path, token=token, response_format='text')
        return TypeAdapter(str).validate_python(data, strict=True)

    async def replay(self, body: BlockRange, *, token: str | None = None) -> ReplayResponse:
        path = '/v1/chain/replay'
        body = BlockRange.model_validate(body)
        data = await self._request('POST', path, token=token, body=body.model_dump())
        return TypeAdapter(ReplayResponse).validate_python(data, strict=True)

    async def messages(self, id: str, *, after: Annotated[int, Field(ge=0)] | None = None, limit: Annotated[int, Field(ge=0)] | None = None, token: str | None = None) -> MessagePage:
        path = '/v1/chats/{id}/messages'.replace('{id}', quote(id, safe=''))
        query = {key: value for key, value in {'after': after, 'limit': limit}.items() if value is not None}
        if query:
            path += '?' + urlencode(query)
        data = await self._request('GET', path, token=token)
        return TypeAdapter(MessagePage).validate_python(data, strict=True)

    async def send(self, id: str, body: SendMessage, *, token: str | None = None, idempotency_key: str) -> ChatMessage:
        path = '/v1/chats/{id}/messages'.replace('{id}', quote(id, safe=''))
        body = SendMessage.model_validate(body)
        data = await self._request('POST', path, token=token, body=body.model_dump(), idempotency_key=idempotency_key)
        return TypeAdapter(ChatMessage).validate_python(data, strict=True)

    async def transcript(self, id: str, *, after: Annotated[int, Field(ge=0)] | None = None, limit: Annotated[int, Field(ge=0)] | None = None, token: str | None = None) -> MessagePage:
        path = '/v1/chats/{id}/transcript'.replace('{id}', quote(id, safe=''))
        query = {key: value for key, value in {'after': after, 'limit': limit}.items() if value is not None}
        if query:
            path += '?' + urlencode(query)
        data = await self._request('GET', path, token=token)
        return TypeAdapter(MessagePage).validate_python(data, strict=True)

    async def docs(self, *, token: str | None = None) -> str:
        path = '/v1/docs'
        data = await self._request('GET', path, token=token, response_format='text')
        return TypeAdapter(str).validate_python(data, strict=True)

    async def register(self, body: RegisterEpisode, *, token: str | None = None, idempotency_key: str) -> OperationView:
        path = '/v1/episodes'
        body = RegisterEpisode.model_validate(body)
        data = await self._request('POST', path, token=token, body=body.model_dump(), idempotency_key=idempotency_key)
        return TypeAdapter(OperationView).validate_python(data, strict=True)

    async def episode(self, id: str, *, token: str | None = None) -> EpisodeView:
        path = '/v1/episodes/{id}'.replace('{id}', quote(id, safe=''))
        data = await self._request('GET', path, token=token)
        return TypeAdapter(EpisodeView).validate_python(data, strict=True)

    async def balances(self, id: str, *, token: str | None = None) -> BalancesView:
        path = '/v1/episodes/{id}/balances'.replace('{id}', quote(id, safe=''))
        data = await self._request('GET', path, token=token)
        return TypeAdapter(BalancesView).validate_python(data, strict=True)

    async def challenge(self, id: str, body: ChallengeRequest, *, token: str | None = None, idempotency_key: str) -> OperationView:
        path = '/v1/episodes/{id}/challenges'.replace('{id}', quote(id, safe=''))
        body = ChallengeRequest.model_validate(body)
        data = await self._request('POST', path, token=token, body=body.model_dump(), idempotency_key=idempotency_key)
        return TypeAdapter(OperationView).validate_python(data, strict=True)

    async def audit(self, id: str, *, after: Annotated[int, Field(ge=0)] | None = None, limit: Annotated[int, Field(ge=0)] | None = None, token: str | None = None) -> ChatAuditReport:
        path = '/v1/episodes/{id}/chat-audit'.replace('{id}', quote(id, safe=''))
        query = {key: value for key, value in {'after': after, 'limit': limit}.items() if value is not None}
        if query:
            path += '?' + urlencode(query)
        data = await self._request('GET', path, token=token)
        return TypeAdapter(ChatAuditReport).validate_python(data, strict=True)

    async def list(self, id: str, *, after: str | None = None, limit: Annotated[int, Field(ge=0)] | None = None, token: str | None = None) -> ChatPage:
        path = '/v1/episodes/{id}/chats'.replace('{id}', quote(id, safe=''))
        query = {key: value for key, value in {'after': after, 'limit': limit}.items() if value is not None}
        if query:
            path += '?' + urlencode(query)
        data = await self._request('GET', path, token=token)
        return TypeAdapter(ChatPage).validate_python(data, strict=True)

    async def create(self, id: str, body: CreateChat, *, token: str | None = None, idempotency_key: str) -> ChatView:
        path = '/v1/episodes/{id}/chats'.replace('{id}', quote(id, safe=''))
        body = CreateChat.model_validate(body)
        data = await self._request('POST', path, token=token, body=body.model_dump(), idempotency_key=idempotency_key)
        return TypeAdapter(ChatView).validate_python(data, strict=True)

    async def claim(self, id: str, body: ClaimRequest, *, token: str | None = None, idempotency_key: str) -> OperationView:
        path = '/v1/episodes/{id}/claims'.replace('{id}', quote(id, safe=''))
        body = ClaimRequest.model_validate(body)
        data = await self._request('POST', path, token=token, body=body.model_dump(), idempotency_key=idempotency_key)
        return TypeAdapter(OperationView).validate_python(data, strict=True)

    async def commitment(self, id: str, body: CommitmentRequest, *, token: str | None = None, idempotency_key: str) -> OperationView:
        path = '/v1/episodes/{id}/commitments'.replace('{id}', quote(id, safe=''))
        body = CommitmentRequest.model_validate(body)
        data = await self._request('POST', path, token=token, body=body.model_dump(), idempotency_key=idempotency_key)
        return TypeAdapter(OperationView).validate_python(data, strict=True)

    async def expire(self, id: str, body: EmptyRequest, *, token: str | None = None, idempotency_key: str) -> OperationView:
        path = '/v1/episodes/{id}/expire'.replace('{id}', quote(id, safe=''))
        body = EmptyRequest.model_validate(body)
        data = await self._request('POST', path, token=token, body=body.model_dump(), idempotency_key=idempotency_key)
        return TypeAdapter(OperationView).validate_python(data, strict=True)

    async def get_forum_audit(self, id: str, *, after: Annotated[int, Field(ge=0)] | None = None, limit: Annotated[int, Field(ge=0)] | None = None, token: str | None = None) -> ForumAuditReport:
        path = '/v1/episodes/{id}/forum-audit'.replace('{id}', quote(id, safe=''))
        query = {key: value for key, value in {'after': after, 'limit': limit}.items() if value is not None}
        if query:
            path += '?' + urlencode(query)
        data = await self._request('GET', path, token=token)
        return TypeAdapter(ForumAuditReport).validate_python(data, strict=True)

    async def get_forum_messages(self, id: str, *, after: Annotated[int, Field(ge=0)] | None = None, limit: Annotated[int, Field(ge=0)] | None = None, token: str | None = None) -> ForumMessagePage:
        path = '/v1/episodes/{id}/forum/messages'.replace('{id}', quote(id, safe=''))
        query = {key: value for key, value in {'after': after, 'limit': limit}.items() if value is not None}
        if query:
            path += '?' + urlencode(query)
        data = await self._request('GET', path, token=token)
        return TypeAdapter(ForumMessagePage).validate_python(data, strict=True)

    async def send_forum_message(self, id: str, body: ForumSendMessage, *, token: str | None = None, idempotency_key: str) -> ForumMessage:
        path = '/v1/episodes/{id}/forum/messages'.replace('{id}', quote(id, safe=''))
        body = ForumSendMessage.model_validate(body)
        data = await self._request('POST', path, token=token, body=body.model_dump(), idempotency_key=idempotency_key)
        return TypeAdapter(ForumMessage).validate_python(data, strict=True)

    async def get_forum_transcript(self, id: str, *, after: Annotated[int, Field(ge=0)] | None = None, limit: Annotated[int, Field(ge=0)] | None = None, token: str | None = None) -> ForumMessagePage:
        path = '/v1/episodes/{id}/forum/transcript'.replace('{id}', quote(id, safe=''))
        query = {key: value for key, value in {'after': after, 'limit': limit}.items() if value is not None}
        if query:
            path += '?' + urlencode(query)
        data = await self._request('GET', path, token=token)
        return TypeAdapter(ForumMessagePage).validate_python(data, strict=True)

    async def reveal(self, id: str, body: EmptyRequest, *, token: str | None = None, idempotency_key: str) -> OperationView:
        path = '/v1/episodes/{id}/reveals'.replace('{id}', quote(id, safe=''))
        body = EmptyRequest.model_validate(body)
        data = await self._request('POST', path, token=token, body=body.model_dump(), idempotency_key=idempotency_key)
        return TypeAdapter(OperationView).validate_python(data, strict=True)

    async def settle(self, id: str, body: EmptyRequest, *, token: str | None = None, idempotency_key: str) -> OperationView:
        path = '/v1/episodes/{id}/settle'.replace('{id}', quote(id, safe=''))
        body = EmptyRequest.model_validate(body)
        data = await self._request('POST', path, token=token, body=body.model_dump(), idempotency_key=idempotency_key)
        return TypeAdapter(OperationView).validate_python(data, strict=True)

    async def settlement(self, id: str, *, token: str | None = None) -> SettlementView:
        path = '/v1/episodes/{id}/settlement'.replace('{id}', quote(id, safe=''))
        data = await self._request('GET', path, token=token)
        return TypeAdapter(SettlementView).validate_python(data, strict=True)

    async def transfer(self, id: str, body: TransferRequest, *, token: str | None = None, idempotency_key: str) -> OperationView:
        path = '/v1/episodes/{id}/transfers'.replace('{id}', quote(id, safe=''))
        body = TransferRequest.model_validate(body)
        data = await self._request('POST', path, token=token, body=body.model_dump(), idempotency_key=idempotency_key)
        return TypeAdapter(OperationView).validate_python(data, strict=True)

    async def withdraw(self, id: str, body: EmptyRequest, *, token: str | None = None, idempotency_key: str) -> OperationView:
        path = '/v1/episodes/{id}/withdrawals'.replace('{id}', quote(id, safe=''))
        body = EmptyRequest.model_validate(body)
        data = await self._request('POST', path, token=token, body=body.model_dump(), idempotency_key=idempotency_key)
        return TypeAdapter(OperationView).validate_python(data, strict=True)

    async def health(self, *, token: str | None = None) -> HealthResponse:
        path = '/v1/health'
        data = await self._request('GET', path, token=token)
        return TypeAdapter(HealthResponse).validate_python(data, strict=True)

    async def openapi_document(self, *, token: str | None = None) -> dict[str, Any]:
        path = '/v1/openapi.json'
        data = await self._request('GET', path, token=token)
        return TypeAdapter(dict[str, Any]).validate_python(data, strict=True)

    async def operation(self, id: str, *, token: str | None = None) -> OperationView:
        path = '/v1/operations/{id}'.replace('{id}', quote(id, safe=''))
        data = await self._request('GET', path, token=token)
        return TypeAdapter(OperationView).validate_python(data, strict=True)

    async def reconcile(self, id: str, body: EmptyRequest, *, token: str | None = None, idempotency_key: str) -> OperationView:
        path = '/v1/operations/{id}/reconcile'.replace('{id}', quote(id, safe=''))
        body = EmptyRequest.model_validate(body)
        data = await self._request('POST', path, token=token, body=body.model_dump(), idempotency_key=idempotency_key)
        return TypeAdapter(OperationView).validate_python(data, strict=True)

    async def participants(self, *, token: str | None = None) -> list[ParticipantView]:
        path = '/v1/participants'
        data = await self._request('GET', path, token=token)
        return TypeAdapter(list[ParticipantView]).validate_python(data, strict=True)
