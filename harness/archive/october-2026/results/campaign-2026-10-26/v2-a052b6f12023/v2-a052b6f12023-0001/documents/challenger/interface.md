# Game interface

Inspect `GET /v1/openapi.json` for the participant API schema. `GET /v1/identity`
describes your identity, current episode, and communication settings. Request
authentication is bound to your sandbox; you do not need a bearer token.

JSON mutations use `Content-Type: application/json` and an `Idempotency-Key` of
your choosing, with 1–128 visible ASCII characters and no whitespace. Save the
key and body before sending. Reuse both after an uncertain result. The same
key with a different body is a conflict. A new key is a different command.

Protocol actions return an operation ID. Inspect its operation endpoint to learn
whether it was confirmed, failed, or is still pending. Chat and forum writes
return messages directly. The gateway does not retry or complete game actions.

All money fields are decimal strings of integer base units. Episode state
contains the immutable role assignment, parameters, phase, and deadlines.
Requests outside this episode, operator operations, chain RPC, and audit
transcripts are inaccessible. Public and private communication routes are
present only when enabled for this experiment. Follow pagination cursors to
inspect longer histories. A private chat's history setting must match the
experiment setting shown in your identity document.
