"""Нормализация полей ingestion.

Преобразует немецкие значения топлива/КПП в канонические коды
для хранения в Vehicle.engine_type / Vehicle.transmission.
"""

from __future__ import annotations


def _prepare(value: str | None) -> str:
    """Подготовка строки: strip, upper, пустая → ''."""
    if value is None:
        return ""
    if not isinstance(value, str):
        value = str(value)
    return value.strip().upper()


def normalize_fuel(value: str | None) -> str:
    """Нормализует топливо к каноническому виду.

    Бензин: BENZIN → PETROL
    Дизель: DIESEL → DIESEL
    Электро: ELEKTRO → ELECTRIC
    Гибрид: HYBRID → HYBRID
    Автогаз: AUTOGAS (LPG) → LPG
    Эрдгаз: ERDGAS (CNG) → CNG
    Неизвестное → UNKNOWN

    Учитывает регистр, пробелы и пустые значения.
    Приоритет LPG/CNG > HYBRID > ELECTRIC > DIESEL > PETROL,
    чтобы корректно обработать составные строки типа
    'Hybrid (Benzin/Elektro)' или 'Autogas (LPG)'.
    """
    s = _prepare(value)
    if not s:
        return "UNKNOWN"

    # LPG / CNG имеют приоритет — содержат AUTOGAS/ERDGAS с LPG/CNG
    if "LPG" in s or "AUTOGAS" in s:
        return "LPG"
    if "CNG" in s or "ERDGAS" in s:
        return "CNG"
    if "HYBRID" in s:
        return "HYBRID"
    if "ELEKTRO" in s or "ELECTRIC" in s or "ELEKTRISCH" in s:
        return "ELECTRIC"
    if "DIESEL" in s:
        return "DIESEL"
    if "BENZIN" in s or s == "PETROL" or "GASOLINE" in s:
        return "PETROL"
    # Точное совпадение PETROL уже покрыто, но оставляем для явности
    if s in {"PETROL", "BENZIN"}:
        return "PETROL"

    return "UNKNOWN"


def normalize_transmission(value: str | None) -> str:
    """Нормализует КПП к каноническому виду.

    SCHALTGETRIEBE → MANUAL
    AUTOMATIK → AUTOMATIC
    Неизвестное → UNKNOWN

    Учитывает регистр, пробелы и пустые значения.
    """
    s = _prepare(value)
    if not s:
        return "UNKNOWN"

    # Немецкие варианты
    if "SCHALTGETRIEBE" in s or "SCHALT" in s:
        return "MANUAL"
    if "AUTOMATIK" in s or "AUTOMATIC" in s:
        return "AUTOMATIC"

    # Английские варианты (на случай нормализованных данных)
    if s == "MANUAL":
        return "MANUAL"
    if s == "AUTOMATIC":
        return "AUTOMATIC"

    return "UNKNOWN"


class FieldNormalizer:
    """Класс-обёртка для нормализации полей (совместимость с ТЗ).

    Предоставляет методы normalize_fuel / normalize_transmission как
    для инстанса, так и для статического вызова. Функции
    normalize_fuel / normalize_transmission остаются доступными как
    модульные обёртки.
    """

    @staticmethod
    def normalize_fuel(value: str | None) -> str:
        """Делегирует к модульной функции normalize_fuel."""
        return normalize_fuel(value)

    @staticmethod
    def normalize_transmission(value: str | None) -> str:
        """Делегирует к модульной функции normalize_transmission."""
        return normalize_transmission(value)
