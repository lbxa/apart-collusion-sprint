"""Follow running sessions live: agent reasoning, commands, and gateway actions.

    veracity-harness-watch harness/results/<campaign> [--width 600]

Reads the files sessions already write (model-call traces and gateway audits) as they
grow, so watching never changes a run.
"""

import argparse
import json
import time
from pathlib import Path

ACTIONS = {
    "claims",
    "challenges",
    "commitments",
    "reveals",
    "withdrawals",
    "transfers",
    "messages",
    "chats",
}


class Follower:
    def __init__(self, root: Path, width: int = 600):
        self.root = root
        self.width = width
        self.offsets: dict[Path, int] = {}

    def clip(self, text: str) -> str:
        text = " ".join(text.split())
        return text if len(text) <= self.width else text[: self.width] + " …"

    def manifest(self, path: Path) -> dict:
        run = next((parent for parent in path.parents if (parent / "run.json").exists()), None)
        return json.loads((run / "run.json").read_text()) if run else {}

    def model(self, path: Path, actor: str) -> str:
        models = self.manifest(path).get("models") or {}
        return f" ({models[actor]})" if actor in models else ""

    def scripted(self, path: Path, actor: str) -> bool:
        config = self.manifest(path).get("config") or {}
        return (
            config.get(actor) == "scripted"
            if actor in {"creator", "challenger"}
            else actor == config.get("scripted_peer") or actor in (config.get("peer_offers") or {})
        )

    def new_lines(self, path: Path) -> list[str]:
        start = self.offsets.get(path, 0)
        with path.open("rb") as file:
            file.seek(start)
            data = file.read()
        complete = data[: data.rfind(b"\n") + 1]
        self.offsets[path] = start + len(complete)
        return [line for line in complete.decode().splitlines() if line.strip()]

    def calls(self, path: Path) -> list[str]:
        case, actor = path.parent.name, path.name.split(".")[0]
        who = f"{case} {actor}{self.model(path, actor)}"
        shown = []
        lines = self.new_lines(path)
        if self.scripted(path, actor):
            return []  # Scripted parties repeat fixed commands; their actions show in audits.
        for line in lines:
            event = json.loads(line)
            if event.get("event") != "model_end":
                continue
            for generation in event["response"]["generations"]:
                for item in generation:
                    message = item["message"]
                    reasoning = message.get("additional_kwargs", {}).get("reasoning_content")
                    if isinstance(reasoning, str) and reasoning.strip():
                        shown.append(f"{who} thinks: {self.clip(reasoning)}")
                    if isinstance(message.get("content"), str) and message["content"].strip():
                        shown.append(f"{who} says: {self.clip(message['content'])}")
                    for call in message.get("tool_calls") or []:
                        command = call.get("args", {}).get("command") or json.dumps(call["args"])
                        shown.append(f"{who} runs: {self.clip(command)}")
        return shown

    def audit(self, path: Path) -> list[str]:
        case = path.parent.parent.name
        shown = []
        for line in self.new_lines(path):
            event = json.loads(line)
            if event.get("event") != "response" or event.get("method") != "POST":
                continue
            if event.get("endpoint") in ACTIONS:
                shown.append(
                    f"{case} {event['actor_id']} POST {event['endpoint']} -> {event['status']}"
                )
        return shown

    def poll(self) -> list[str]:
        shown = []
        live = [path for path in self.root.glob("**/*.jsonl") if "excluded" not in path.parts]
        for path in sorted(p for p in live if p.name.endswith(".trace.calls.jsonl")):
            shown += self.calls(path)
        for path in sorted(p for p in live if p.name == "access.jsonl"):
            shown += self.audit(path)
        return shown


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("results", type=Path)
    parser.add_argument("--width", type=int, default=600, help="Characters per entry")
    parser.add_argument("--from-start", action="store_true", help="Replay what is logged")
    args = parser.parse_args()
    follower = Follower(args.results, args.width)
    if not args.from_start:
        follower.poll()  # Skip history; show only what happens from now on.
    while True:
        for line in follower.poll():
            print(f"{time.strftime('%H:%M:%S')} {line}", flush=True)
        time.sleep(2)


if __name__ == "__main__":
    main()
