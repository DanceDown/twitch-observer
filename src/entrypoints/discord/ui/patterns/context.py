"""Shared context for guided ping form views."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Generic, TypeVar

from src.entrypoints.discord.service_bundle import DiscordServiceBundle
from src.localization import Localizer

_DataProviderT = TypeVar("_DataProviderT")


@dataclass(slots=True, frozen=True)
class PatternViewContext(Generic[_DataProviderT]):
    """Common dependencies for the multi-step ping UI views."""

    owner_id: int
    language: str
    services: DiscordServiceBundle
    data_provider: _DataProviderT
    discord_channel_id: int
    localizer: Localizer
