from aiogram import Router

from . import admin, game, menu


def setup_routers() -> list[Router]:
    # order matters: game.router has the catch-all text handler, so it goes last
    return [admin.router, menu.router, game.router]
