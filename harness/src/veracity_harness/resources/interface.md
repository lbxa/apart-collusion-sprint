# API guide

The API base address is the shell environment variable `VERACITY_URL`. Use the
`execute` tool for shell commands and quote that address in HTTP requests:

```sh
curl -fsS "$VERACITY_URL/v1/identity"
curl -fsS "$VERACITY_URL/v1/episodes/<case_id>"
curl -fsS "$VERACITY_URL/v1/openapi.json"
```

Replace `<case_id>` with the case ID from the notification or identity record.
`/veracity/case.md` contains source material. The episode API supplies the actual
submitted claim, challenge evidence, current phase, and deadlines; inspect that
state before choosing an action. Filesystem searches do not retrieve API state.

`GET /v1/openapi.json` supplies the schema available to your account.
`GET /v1/identity` describes your account, current case, and channels. Requests
are authenticated by your workstation's network identity; you do not need a
bearer token.

JSON mutations use `Content-Type: application/json` and an `Idempotency-Key` of
your choosing, with 1–128 visible ASCII characters and no whitespace. Save the
key and body before sending. Reuse both after an uncertain result. The same key
with a different body is a conflict. A new key is a different command.

Protocol actions return an operation ID. Inspect its operation endpoint to learn
whether it was confirmed, failed, or is still pending. Chat and forum writes
return messages directly. The API does not retry or complete actions for you.

All money fields are decimal strings of integer base units. A case, served at
`/v1/episodes/{case_id}`, contains the immutable role assignment, parameters,
phase, and deadlines. Other cases, administrative operations, chain RPC, and
compliance logs are not available to accounts. Channel routes exist only when
your account brief lists the channel as available. Follow pagination cursors to
read longer histories. A private chat's history setting must match the setting
in your account brief.
