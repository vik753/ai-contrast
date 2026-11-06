"""S9-T0: the optional ``essential`` field of a catalog topic (ADR 0019 point 3.4)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from app.topics.catalog import CatalogError, load_catalog
from tests.topics.helpers import mutated

SHIPPED = Path(__file__).resolve().parents[3] / "shared" / "topics"
Edit = Any


def _set_essential(value: Any) -> Any:
    def edit(kasko: Edit) -> None:
        kasko["topics"][0]["essential"] = value

    return edit


def test_catalog_essential_valid_loads(tmp_path: Path) -> None:
    catalog = load_catalog(mutated(tmp_path, _set_essential({"insured": True, "insurer": False})))

    kasko = next(d for d in catalog.domains if d.id == "kasko")
    assert kasko.topics[0].essential == {"insured": True, "insurer": False}


def test_catalog_essential_may_name_one_side(tmp_path: Path) -> None:
    catalog = load_catalog(mutated(tmp_path, _set_essential({"insured": True})))

    kasko = next(d for d in catalog.domains if d.id == "kasko")
    assert kasko.topics[0].essential == {"insured": True}


def test_catalog_essential_absent_means_none(tmp_path: Path) -> None:
    catalog = load_catalog(mutated(tmp_path, lambda kasko: None))

    kasko = next(d for d in catalog.domains if d.id == "kasko")
    assert all(topic.essential is None for topic in kasko.topics)


def test_catalog_essential_unknown_side_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(CatalogError):
        load_catalog(mutated(tmp_path, _set_essential({"landlord": True})))


def test_catalog_essential_known_and_unknown_side_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(CatalogError):
        load_catalog(mutated(tmp_path, _set_essential({"insured": True, "nobody": True})))


def test_catalog_essential_empty_dict_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(CatalogError):
        load_catalog(mutated(tmp_path, _set_essential({})))


@pytest.mark.parametrize("value", ["yes", 1, 0, "true", None])
def test_catalog_essential_non_bool_value_is_rejected(tmp_path: Path, value: Any) -> None:
    with pytest.raises(CatalogError):
        load_catalog(mutated(tmp_path, _set_essential({"insured": value})))


def test_catalog_essential_not_a_dict_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(CatalogError):
        load_catalog(mutated(tmp_path, _set_essential(["insured"])))


def test_catalog_shipped_files_load_with_four_domains() -> None:
    catalog = load_catalog(SHIPPED)

    assert sorted(d.id for d in catalog.domains) == [
        "kasko",
        "lease",
        "osago",
        "property_insurance",
    ]


def test_catalog_shipped_essential_side_ids_exist() -> None:
    catalog = load_catalog(SHIPPED)

    flagged = 0
    for domain in catalog.domains:
        side_ids = {side.id for side in domain.sides}
        for topic in domain.topics:
            if topic.essential is None:
                continue
            flagged += 1
            assert topic.essential
            assert set(topic.essential) <= side_ids
            assert all(isinstance(v, bool) for v in topic.essential.values())
    assert flagged >= 10
