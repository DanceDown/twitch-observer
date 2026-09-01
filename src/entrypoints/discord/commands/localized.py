"""Helpers for localized Discord slash-command metadata."""

from __future__ import annotations

import discord

from src.localization import LocalizationError, Localizer

_COMMAND_SCOPE = "discord.commands"
_GERMAN_LOCALES = {discord.Locale.german}


class CommandCatalogTranslator(discord.app_commands.Translator):
    """Translate Discord command metadata through the same JSON catalogs as runtime UI text."""

    def __init__(self, localizer: Localizer) -> None:
        """Create a translator backed by the shared localizer."""
        self._localizer = localizer

    async def translate(
        self,
        string: discord.app_commands.locale_str,
        locale: discord.Locale,
        context: discord.app_commands.TranslationContextTypes,
    ) -> str | None:
        """Return a localized Discord command string when this catalog owns it."""
        _ = context
        key = string.extras.get("key")
        if not isinstance(key, str) or not key.startswith(f"{_COMMAND_SCOPE}."):
            return None

        language = "german" if locale in _GERMAN_LOCALES else self._localizer.default_language
        if language == self._localizer.default_language:
            return None
        try:
            return self._localizer.text(key, language=language)
        except LocalizationError:
            return None


def command_text(localizer: Localizer, key: str) -> discord.app_commands.locale_str:
    """Resolve default command metadata and attach the catalog key for Discord translations."""
    translation_key = f"{_COMMAND_SCOPE}.{key}"
    default_text = localizer.text(translation_key, language=localizer.default_language)
    return discord.app_commands.locale_str(default_text, key=translation_key)


def command_descriptions(
    localizer: Localizer,
    **keys_by_parameter: str,
) -> dict[str, discord.app_commands.locale_str]:
    """Resolve slash-command parameter descriptions without inline visible copy."""
    return {parameter_name: command_text(localizer, key) for parameter_name, key in keys_by_parameter.items()}
