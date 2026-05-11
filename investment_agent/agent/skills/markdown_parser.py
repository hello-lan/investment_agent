from dataclasses import dataclass
from pathlib import Path


@dataclass
class ParsedSkill:
    name: str
    description: str
    tools: list[str]
    schema: dict
    entry: str | None
    skill_dir: Path
    main_md_path: Path
    body: str


def _parse_frontmatter(text: str) -> tuple[dict, str]:
    if not text.startswith("---"):
        return {}, text

    lines = text.splitlines()
    if not lines:
        return {}, text

    end_index = None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            end_index = i
            break

    if end_index is None:
        return {}, text

    header_lines = lines[1:end_index]
    body = "\n".join(lines[end_index + 1:])

    data: dict = {}
    current_key: str | None = None

    for raw in header_lines:
        line = raw.rstrip()
        if not line.strip() or line.strip().startswith("#"):
            continue

        if line.startswith("  - ") and current_key:
            if not isinstance(data.get(current_key), list):
                data[current_key] = []
            data[current_key].append(line[4:].strip())
            continue

        if ":" not in line:
            current_key = None
            continue

        key, value = line.split(":", 1)
        key = key.strip()
        value = value.strip()

        if not value:
            data[key] = []
            current_key = key
            continue

        current_key = key
        if value.startswith("[") and value.endswith("]"):
            parts = [p.strip().strip('"').strip("'") for p in value[1:-1].split(",") if p.strip()]
            data[key] = parts
        elif value.lower() in ("true", "false"):
            data[key] = value.lower() == "true"
        else:
            data[key] = value.strip('"').strip("'")

    return data, body


def _default_schema(name: str, description: str) -> dict:
    return {
        "name": f"skill_{name}",
        "description": description,
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    }


def parse_skill_markdown(md_path: Path) -> ParsedSkill:
    content = md_path.read_text(encoding="utf-8")
    meta, body = _parse_frontmatter(content)

    name = str(meta.get("name", "")).strip()
    description = str(meta.get("description", "")).strip()
    if not name or not description:
        raise ValueError(f"invalid skill markdown (name/description required): {md_path}")

    tools = meta.get("tools", [])
    if not isinstance(tools, list):
        tools = []

    schema = meta.get("schema")
    if not isinstance(schema, dict):
        schema = _default_schema(name, description)

    schema_name = schema.get("name")
    if not isinstance(schema_name, str) or not schema_name.strip():
        schema["name"] = f"skill_{name}"

    if schema["name"] != f"skill_{name}":
        raise ValueError(f"schema.name must be skill_{name}: {md_path}")

    if not isinstance(schema.get("description"), str):
        schema["description"] = description

    if not isinstance(schema.get("input_schema"), dict):
        schema["input_schema"] = {
            "type": "object",
            "properties": {},
            "required": [],
        }

    entry_raw = str(meta.get("entry", "")).strip()
    entry = entry_raw or None

    return ParsedSkill(
        name=name,
        description=description,
        tools=[str(t) for t in tools],
        schema=schema,
        entry=entry,
        skill_dir=md_path.parent,
        main_md_path=md_path,
        body=body,
    )
