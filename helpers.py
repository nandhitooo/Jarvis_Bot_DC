"""Shared embed builders and color constants for consistent bot responses."""

import discord

COLOR_ERROR = 0xFF3333
COLOR_OK = 0x2ECC71
COLOR_WARN = 0xF1C40F
COLOR_INFO = 0x00E5FF
COLOR_DANGER = 0xE74C3C


def err(text: str, title: str | None = None) -> discord.Embed:
    """Return a red error embed with the given description."""
    return discord.Embed(title=title, description=text, color=COLOR_ERROR)


def ok(text: str, title: str | None = None) -> discord.Embed:
    """Return a green success embed with the given description."""
    return discord.Embed(title=title, description=text, color=COLOR_OK)


def warn(text: str, title: str | None = None) -> discord.Embed:
    """Return a yellow warning embed with the given description."""
    return discord.Embed(title=title, description=text, color=COLOR_WARN)


def info(text: str, title: str | None = None) -> discord.Embed:
    """Return a cyan informational embed with the given description."""
    return discord.Embed(title=title, description=text, color=COLOR_INFO)
