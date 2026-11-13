"""Thin wrapper over the Bot API so the game manager can be tested without Telegram."""
import asyncio
import logging
from typing import Protocol

from aiogram import Bot
from aiogram.enums import ChatAction
from aiogram.exceptions import TelegramAPIError, TelegramForbiddenError, TelegramRetryAfter
from aiogram.types import ReactionTypeEmoji

log = logging.getLogger(__name__)


class Notifier(Protocol):
    async def send(self, chat_id: int, text: str, markup=None) -> bool: ...
    async def typing(self, chat_id: int) -> None: ...
    async def react(self, chat_id: int, message_id: int, emoji: str) -> bool: ...


class TelegramNotifier:
    def __init__(self, bot: Bot) -> None:
        self.bot = bot

    async def send(self, chat_id: int, text: str, markup=None) -> bool:
        for _ in range(2):
            try:
                await self.bot.send_message(chat_id, text, reply_markup=markup)
                return True
            except TelegramRetryAfter as e:
                await asyncio.sleep(e.retry_after)
            except TelegramForbiddenError:
                log.info("user %s blocked the bot", chat_id)
                return False
            except TelegramAPIError as e:
                log.warning("send to %s failed: %s", chat_id, e)
                return False
        return False

    async def typing(self, chat_id: int) -> None:
        try:
            await self.bot.send_chat_action(chat_id, ChatAction.TYPING)
        except TelegramAPIError:
            pass

    async def react(self, chat_id: int, message_id: int, emoji: str) -> bool:
        try:
            await self.bot.set_message_reaction(chat_id, message_id, reaction=[ReactionTypeEmoji(emoji=emoji)])
            return True
        except TelegramAPIError:
            return False
