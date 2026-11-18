#!/usr/bin/env python3
"""Generate the strict Python boundary from the running Rust schema builder.

Only the JSON Schema features used by this API are supported. Unknown features
fail generation, so a schema change cannot silently weaken client validation.
No server, database, chain, network access, or third-party codegen is required.
"""

from __future__ import annotations

import argparse
import json
import keyword
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "docs/openapi.json"
CLIENT_PATH = ROOT / "harness/src/game_api/generated.py"
SUPPORTED = {
    "$ref", "type", "format", "description", "title", "default", "required",
    "properties", "additionalProperties", "propertyNames", "items", "oneOf",
    "enum", "minimum", "maximum", "pattern", "minLength", "maxLength",
    "minItems", "maxItems", "deprecated", "example", "examples",
}
METADATA = {"description", "title", "default", "deprecated", "example", "examples"}


def only(schema: dict, supported: set[str]) -> None:
    unknown = set(schema) - supported - METADATA
    if unknown:
        raise ValueError(f"Unsupported schema features: {sorted(unknown)}")


def identifier(value: str) -> str:
    if not value.isidentifier() or keyword.iskeyword(value):
        raise ValueError(f"Unsupported Python identifier: {value}")
    return value


def annotation(schema: dict) -> str:
    unknown = set(schema) - SUPPORTED
    if unknown:
        raise ValueError(f"Unsupported schema features: {sorted(unknown)}")
    if "$ref" in schema:
        only(schema, {"$ref"})
        if not schema["$ref"].startswith("#/components/schemas/"):
            raise ValueError("Only local component references are supported")
        return identifier(schema["$ref"].rsplit("/", 1)[1])
    if "oneOf" in schema:
        only(schema, {"oneOf"})
        variants = schema["oneOf"]
        if len(variants) != 2 or sum(item.get("type") == "null" for item in variants) != 1:
            raise ValueError("Only nullable oneOf unions are supported")
        return " | ".join(annotation(item) for item in variants)
    kind = schema.get("type", "object")
    if isinstance(kind, list):
        if len(kind) != 2 or "null" not in kind:
            raise ValueError("Only nullable type unions are supported")
        return annotation({**schema, "type": next(item for item in kind if item != "null")}) + " | None"
    if "enum" in schema:
        only(schema, {"type", "enum"})
        if kind != "string" or not all(isinstance(item, str) for item in schema["enum"]):
            raise ValueError("Only string enums are supported")
        return "Literal[" + ", ".join(repr(item) for item in schema["enum"]) + "]"
    if kind == "null":
        only(schema, {"type"})
        return "None"
    if kind == "object":
        only(schema, {"type", "properties", "additionalProperties", "propertyNames"})
        if "properties" in schema:
            raise ValueError("Inline structured objects must become named components")
        names = schema.get("propertyNames", {"type": "string"})
        if names != {"type": "string"}:
            raise ValueError("Constrained map keys are unsupported")
        values = schema.get("additionalProperties", True)
        if values is False:
            return "dict[str, Never]"
        return "dict[str, " + ("Any" if values is True else annotation(values)) + "]"
    if kind == "array":
        only(schema, {"type", "items", "minItems", "maxItems"})
        result = "list[" + annotation(schema["items"]) + "]"
    else:
        constraints_by_kind = {
            "string": {"pattern", "minLength", "maxLength"},
            "integer": {"minimum", "maximum"},
            "number": {"minimum", "maximum"},
            "boolean": set(),
        }
        if kind not in constraints_by_kind:
            raise ValueError(f"Unsupported schema type: {kind}")
        only(schema, {"type", "format"} | constraints_by_kind[kind])
        if "format" in schema and (kind != "integer" or schema["format"] not in {"int32", "int64"}):
            raise ValueError(f"Unsupported schema format: {schema['format']}")
        result = {"string": "str", "integer": "int", "number": "float", "boolean": "bool"}[kind]
    constraints = []
    for source, target in (("minimum", "ge"), ("maximum", "le"), ("pattern", "pattern"),
                           ("minLength", "min_length"), ("maxLength", "max_length"),
                           ("minItems", "min_length"), ("maxItems", "max_length")):
        if source in schema:
            constraints.append(f"{target}={schema[source]!r}")
    if constraints:
        return f"Annotated[{result}, Field({', '.join(constraints)})]"
    return result


def nullable(schema: dict) -> bool:
    return (schema.get("type") == "null"
            or "null" in schema.get("type", [])
            or any(nullable(item) for item in schema.get("oneOf", [])))


def generate(document: dict) -> str:
    if document.get("openapi") != "3.1.0":
        raise ValueError("Expected OpenAPI 3.1.0")
    schemas = document["components"]["schemas"]
    lines = [
        '"""Generated from Rust OpenAPI. Run python scripts/generate-core-client.py; do not edit."""',
        "", "from __future__ import annotations", "",
        "from collections.abc import Awaitable, Callable",
        "from typing import Annotated, Any, Literal, Never",
        "from urllib.parse import quote, urlencode", "",
        "from pydantic import BaseModel, ConfigDict, Field, TypeAdapter", "", "",
        "class WireModel(BaseModel):",
        '    model_config = ConfigDict(strict=True, extra="forbid", frozen=True,',
        "                              hide_input_in_errors=True)",
    ]
    for name, schema in sorted(schemas.items()):
        if schema.get("type") != "object":
            lines += ["", "", f"{identifier(name)} = {annotation(schema)}"]
    models = []
    for name, schema in sorted(schemas.items()):
        if schema.get("type") != "object":
            continue
        unknown = set(schema) - SUPPORTED
        if unknown or schema.get("additionalProperties") not in (None, False):
            raise ValueError(f"Unsupported model definition: {name}: {sorted(unknown)}")
        only(schema, {"type", "required", "properties", "additionalProperties"})
        models.append(identifier(name))
        lines += ["", "", f"class {name}(WireModel):"]
        properties = schema.get("properties", {})
        required = set(schema.get("required", []))
        if not properties:
            lines += ["    pass"]
        for prop, definition in properties.items():
            value_type = annotation(definition)
            default = ""
            if prop not in required:
                if "default" in definition:
                    default = " = " + repr(definition["default"])
                elif nullable(definition):
                    default = " = None"
                else:
                    raise ValueError(f"Optional field needs a documented default: {name}.{prop}")
            lines += [f"    {identifier(prop)}: {value_type}{default}"]
    lines += ["", "", "# Resolve references after all component models have been declared."]
    lines += [f"{name}.model_rebuild()" for name in models]
    lines += ["", "", "class GeneratedAPI:",
              '    """Typed endpoint calls; transport owns credentials, sessions, and HTTP errors."""',
              "", "    def __init__(self, request: Callable[..., Awaitable[Any]]):",
              "        self._request = request"]
    for path, methods in sorted(document["paths"].items()):
        for method, operation in sorted(methods.items()):
            if method not in {"get", "post"}:
                raise ValueError(f"Unsupported HTTP method: {method}")
            name = identifier(operation["operationId"])
            parameters = operation.get("parameters", [])
            path_parameters = [p for p in parameters if p["in"] == "path"]
            query_parameters = [p for p in parameters if p["in"] == "query"]
            headers = [p for p in parameters if p["in"] == "header"]
            if any(p["name"] != "Idempotency-Key" for p in headers):
                raise ValueError(f"Unsupported headers: {name}")
            if len(parameters) != len(path_parameters) + len(query_parameters) + len(headers):
                raise ValueError(f"Unsupported parameter kind: {name}")
            args = ["self"] + [f"{identifier(p['name'])}: {annotation(p['schema'])}" for p in path_parameters]
            body = operation.get("requestBody")
            body_type = None
            if body:
                body_type = annotation(body["content"]["application/json"]["schema"])
                args += [f"body: {body_type}"]
            args += ["*"]
            for parameter in query_parameters:
                argument = identifier(parameter["name"])
                argument_type = annotation(parameter["schema"])
                if parameter.get("required", False):
                    args += [f"{argument}: {argument_type}"]
                else:
                    if not nullable(parameter["schema"]):
                        argument_type += " | None"
                    args += [f"{argument}: {argument_type} = None"]
            args += ["token: str | None = None"]
            if headers:
                args += ["idempotency_key: str"]
            successes = [response["content"] for status, response in operation["responses"].items()
                         if status.isdecimal() and 200 <= int(status) < 300]
            if not successes or any(success != successes[0] for success in successes):
                raise ValueError(f"Expected one success response type: {name}")
            media = successes[0]
            if len(media) != 1:
                raise ValueError(f"Expected one response format: {name}")
            mime, response = next(iter(media.items()))
            result = annotation(response["schema"])
            lines += ["", f"    async def {name}({', '.join(args)}) -> {result}:"]
            expression = repr(path)
            for parameter in path_parameters:
                variable = identifier(parameter["name"])
                expression += f".replace('{{{parameter['name']}}}', quote({variable}, safe=''))"
            lines += [f"        path = {expression}"]
            if query_parameters:
                query = ", ".join(f"{p['name']!r}: {identifier(p['name'])}" for p in query_parameters)
                lines += [f"        query = {{key: value for key, value in {{{query}}}.items() if value is not None}}",
                          "        if query:", "            path += '?' + urlencode(query)"]
            request_args = [repr(method.upper()), "path", "token=token"]
            if body:
                lines += [f"        body = {body_type}.model_validate(body)"]
                request_args += ["body=body.model_dump()"]
            if headers:
                request_args += ["idempotency_key=idempotency_key"]
            if mime != "application/json":
                if result != "str":
                    raise ValueError(f"Unsupported non-JSON response: {name}")
                request_args += ["response_format='text'"]
            lines += [f"        data = await self._request({', '.join(request_args)})",
                      f"        return TypeAdapter({result}).validate_python(data, strict=True)"]
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Fail if committed artifacts are stale")
    args = parser.parse_args()
    result = subprocess.run(
        ["cargo", "run", "--quiet", "--locked", "-p", "veracity-game-service", "--example", "export_openapi"],
        cwd=ROOT, check=True, capture_output=True, text=True,
    )
    document = json.loads(result.stdout)
    artifacts = {SCHEMA_PATH: json.dumps(document, indent=2, sort_keys=True) + "\n",
                 CLIENT_PATH: generate(document)}
    stale = []
    for path, contents in artifacts.items():
        if args.check:
            if not path.is_file() or path.read_text() != contents:
                stale.append(str(path.relative_to(ROOT)))
        else:
            path.write_text(contents)
    if stale:
        print("Generated client is stale: " + ", ".join(stale), file=sys.stderr)
        print("Run python scripts/generate-core-client.py and commit the results.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
