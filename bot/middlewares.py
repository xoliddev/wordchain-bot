import logging
import time
from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware, Bot
from aiogram.enums import ChatMemberStatus
from aiogram.exceptions import TelegramAPIError
from aiogram.types import CallbackQuery, Message, TelegramObject, User

from . import keyboards as kb
from . import texts
from .config import Settings
from .db import Database

log = logging.getLogger(__name__)

Handler = Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]]


class UserMiddleware(BaseMiddleware):
    """Registers/refreshes the user and injects `profile` into handlers."""

    async def __call__(self, handler: Handler, event: TelegramObject, data: dict[str, Any]) -> Any:
        user: User | None = data.get("event_from_user")
        if user is None or user.is_bot:
            return None
        db: Database = data["db"]
        data["profile"] = await db.upsert_user(user.id, user.username, user.full_name)
        return await handler(event, data)


class SubscriptionMiddleware(BaseMiddleware):
    """Optional: requires a channel subscription (the bot must be a channel admin)."""

    MEMBER = {ChatMemberStatus.CREATOR, ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.MEMBER}
    TTL = 600

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._ok_until: dict[int, float] = {}

    async def is_member(self, bot: Bot, user_id: int) -> bool:
        if self._ok_until.get(user_id, 0) > time.monotonic():
            return True
        try:
            member = await bot.get_chat_member(self.settings.required_channel, user_id)
        except TelegramAPIError as e:
            log.warning("subscription check failed (is the bot a channel admin?): %s", e)
            return True  # fail open: never lock users out because of our misconfiguration
        ok = member.status in self.MEMBER or getattr(member, "is_member", False)
        if ok:
            self._ok_until[user_id] = time.monotonic() + self.TTL
        return ok

    async def __call__(self, handler: Handler, event: TelegramObject, data: dict[str, Any]) -> Any:
        user: User | None = data.get("event_from_user")
        manager = data.get("manager")
        if (
            user is None
            or user.id in self.settings.admin_ids
            or (manager is not None and manager.session_of(user.id) is not None)  # never interrupt a game
            or await self.is_member(data["bot"], user.id)
        ):
            return await handler(event, data)
        if isinstance(event, Message):
            await event.answer(texts.SUBSCRIBE, reply_markup=kb.subscribe(self.settings.channel_link))
        elif isinstance(event, CallbackQuery):
            await event.answer(texts.SUBSCRIBE_ALERT, show_alert=True)
        return None
