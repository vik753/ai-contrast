"""Helpers of the S7-T1 tests (see README.md)."""

from __future__ import annotations

import copy
import json
import shutil
from pathlib import Path
from typing import Any

from app.pseudo.gate import ConfirmedTopic, confirm_topic
from app.topics.model import AttributeDefinition, TopicDefinition

FIXTURES = Path(__file__).resolve().parent / "fixtures"
CATALOG_OK = FIXTURES / "catalog_ok"
LANGS = ("en", "uk", "ru")
IBAN = "UA363052990000000026007233456"


def definition(**changes: Any) -> TopicDefinition:
    base: dict[str, Any] = {
        "origin": "custom",
        "domain": "kasko",
        "topic_id": "custom_1",
        "title": "Roadside assistance",
        "description": "Towing and help on the road",
        "side": "insured",
    }
    return TopicDefinition(**{**base, **changes})


def attribute(**changes: Any) -> AttributeDefinition:
    base: dict[str, Any] = {"id": "limit", "label": "Towing limit", "type": "amount"}
    if "values" in changes and "value_ids" not in changes:
        changes["value_ids"] = tuple(f"v{n}" for n in range(len(changes["values"])))
    return AttributeDefinition(**{**base, **changes})


def confirmed(**changes: Any) -> ConfirmedTopic:
    return confirm_topic(definition(**changes))


def catalog_data() -> dict[str, dict[str, Any]]:
    """The valid fixture catalog as ``{domain id: file content}`` (deep copies, safe to edit)."""
    return {
        path.stem: json.loads(path.read_text(encoding="utf-8"))
        for path in sorted(CATALOG_OK.glob("*.json"))
    }


def write_catalog(directory: Path, data: dict[str, dict[str, Any]]) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    for name, content in data.items():
        (directory / f"{name}.json").write_text(
            json.dumps(content, ensure_ascii=False), encoding="utf-8"
        )
    return directory


def copy_ok(directory: Path) -> Path:
    shutil.copytree(CATALOG_OK, directory)
    return directory


def mutated(tmp_path: Path, edit: Any) -> Path:
    """Write the fixture catalog after ``edit(kasko_dict)`` changed the ``kasko`` file."""
    data = copy.deepcopy(catalog_data())
    edit(data["kasko"])
    return write_catalog(tmp_path / "cat", data)
