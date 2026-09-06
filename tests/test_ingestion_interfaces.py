"""Тесты интерфейсов источников данных."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime

import pytest

from app.ingestion.dtos import RawListingDTO
from app.ingestion.interfaces import (
    AsyncIngestionSource,
    IngestionSource,
    IngestionSourceProtocol,
)


def _make_raw(source_id: str, ext_id: str) -> RawListingDTO:
    return RawListingDTO(
        source_id=source_id,
        source_listing_id=ext_id,
        fetched_at=datetime.now(UTC),
        raw_data={"id": ext_id},
    )


# ---------------------------------------------------------------------------
# Sync IngestionSource
# ---------------------------------------------------------------------------


def test_ingestion_source_is_abstract() -> None:
    with pytest.raises(TypeError):
        IngestionSource()  # type: ignore[abstract]


def test_dummy_sync_source_implements_interface() -> None:
    class DummySource(IngestionSource):
        @property
        def source_id(self) -> str:
            return "dummy.de"

        @property
        def country_code(self) -> str:
            return "DE"

        def fetch_raw_listings(self, *, limit: int | None = None) -> Iterable[RawListingDTO]:
            items = [_make_raw("dummy.de", "1"), _make_raw("dummy.de", "2")]
            if limit is not None:
                return items[:limit]
            return items

    src = DummySource()
    assert src.source_id == "dummy.de"
    assert src.country_code == "DE"
    assert src.is_active is True
    assert src.health_check() is True

    all_items = list(src.fetch_raw_listings())
    assert len(all_items) == 2
    assert all_items[0].source_listing_id == "1"

    limited = list(src.fetch_raw_listings(limit=1))
    assert len(limited) == 1

    # fetch_raw_listing ищет по ID через базовую реализацию
    found = src.fetch_raw_listing("2")
    assert found is not None
    assert found.source_listing_id == "2"

    assert src.fetch_raw_listing("nonexistent") is None
    assert src.fetch_raw_listing("   ") is None

    # Protocol check — структурная совместимость
    assert isinstance(src, IngestionSourceProtocol)


def test_sync_source_protocol_duck_typing() -> None:
    class DuckSource:
        source_id = "duck.de"
        country_code = "DE"

        def fetch_raw_listings(self, *, limit: int | None = None) -> Iterable[RawListingDTO]:
            return []

    duck = DuckSource()
    # runtime_checkable Protocol
    assert isinstance(duck, IngestionSourceProtocol)

    class Incomplete:
        source_id = "incomplete"

        def fetch_raw_listings(self) -> Iterable[RawListingDTO]:  # type: ignore[no-untyped-def]
            return []

    incomplete = Incomplete()
    assert not isinstance(incomplete, IngestionSourceProtocol)


def test_sync_source_inactive_health_check() -> None:
    class InactiveSource(IngestionSource):
        @property
        def source_id(self) -> str:
            return "inactive.de"

        @property
        def country_code(self) -> str:
            return "DE"

        @property
        def is_active(self) -> bool:
            return False

        def fetch_raw_listings(self, *, limit: int | None = None) -> Iterable[RawListingDTO]:
            return []

    src = InactiveSource()
    assert src.health_check() is False


# ---------------------------------------------------------------------------
# Async IngestionSource
# ---------------------------------------------------------------------------


def test_async_source_is_abstract() -> None:
    with pytest.raises(TypeError):
        AsyncIngestionSource()  # type: ignore[abstract]


def test_dummy_async_source() -> None:
    import asyncio

    class DummyAsync(AsyncIngestionSource):
        @property
        def source_id(self) -> str:
            return "async.de"

        @property
        def country_code(self) -> str:
            return "DE"

        async def fetch_raw_listings(self, *, limit: int | None = None) -> list[RawListingDTO]:
            items = [_make_raw("async.de", "a"), _make_raw("async.de", "b")]
            if limit is not None:
                return items[:limit]
            return items

    async def _run() -> None:
        src = DummyAsync()
        assert src.source_id == "async.de"
        items = await src.fetch_raw_listings()
        assert len(items) == 2

        limited = await src.fetch_raw_listings(limit=1)
        assert len(limited) == 1

        found = await src.fetch_raw_listing("b")
        assert found is not None
        assert found.source_listing_id == "b"

        assert await src.fetch_raw_listing("missing") is None
        assert await src.health_check() is True

    asyncio.run(_run())
