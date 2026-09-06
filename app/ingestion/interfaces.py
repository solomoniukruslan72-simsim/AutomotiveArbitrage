"""Интерфейсы источников данных для ingestion.

Контракт не выполняет HTTP-запросы и не содержит парсеров — только
абстрактное описание, которое могут реализовать моки/адаптеры.
Совместим с app/models.py:13 Source (source_id, country_code).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterable
from typing import Protocol, runtime_checkable

from app.ingestion.dtos import RawListingDTO


class IngestionSource(ABC):
    """Базовый синхронный интерфейс источника объявлений.

    Реализации должны быть легковесными и не обращаться к сайтам
    в тестах. Для сетевых адаптеров используйте подмену в DI.
    """

    @property
    @abstractmethod
    def source_id(self) -> str:
        """Идентификатор источника, PK из таблицы source (до 50 симв.)."""
        ...

    @property
    @abstractmethod
    def country_code(self) -> str:
        """ISO 3166-1 alpha-2 код страны источника (2 буквы)."""
        ...

    @property
    def is_active(self) -> bool:
        """Активен ли источник. По умолчанию True."""
        return True

    @abstractmethod
    def fetch_raw_listings(self, *, limit: int | None = None) -> Iterable[RawListingDTO]:
        """Вернуть пачку сырых объявлений.

        Args:
            limit: опциональный лимит количества; None — без ограничений.

        Returns:
            Итерируемая коллекция RawListingDTO. Реализация не должна
            выполнять реальные HTTP-запросы в тестах.
        """
        ...

    def fetch_raw_listing(self, source_listing_id: str) -> RawListingDTO | None:
        """Вернуть одно объявление по внешнему ID, если поддерживается.

        Базовая реализация перебирает fetch_raw_listings и ищет совпадение.
        Переопределите для эффективного точечного запроса.
        """
        needle = source_listing_id.strip()
        if not needle:
            return None
        for item in self.fetch_raw_listings():
            if item.source_listing_id == needle:
                return item
        return None

    def health_check(self) -> bool:
        """Лёгкая проверка доступности источника без сети.

        По умолчанию возвращает is_active. Сетевые реализации могут
        переопределить.
        """
        return self.is_active


class AsyncIngestionSource(ABC):
    """Асинхронный вариант интерфейса источника.

    Дублирует IngestionSource для async-контекстов (например, aiohttp).
    """

    @property
    @abstractmethod
    def source_id(self) -> str: ...

    @property
    @abstractmethod
    def country_code(self) -> str: ...

    @property
    def is_active(self) -> bool:
        return True

    @abstractmethod
    async def fetch_raw_listings(self, *, limit: int | None = None) -> list[RawListingDTO]: ...

    async def fetch_raw_listing(self, source_listing_id: str) -> RawListingDTO | None:
        needle = source_listing_id.strip()
        if not needle:
            return None
        items = await self.fetch_raw_listings()
        for item in items:
            if item.source_listing_id == needle:
                return item
        return None

    async def health_check(self) -> bool:
        return self.is_active


@runtime_checkable
class IngestionSourceProtocol(Protocol):
    """Protocol для структурной проверки (duck typing)."""

    @property
    def source_id(self) -> str: ...

    @property
    def country_code(self) -> str: ...

    def fetch_raw_listings(self, *, limit: int | None = None) -> Iterable[RawListingDTO]: ...
