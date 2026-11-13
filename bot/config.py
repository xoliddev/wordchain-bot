import os
from dataclasses import dataclass, field
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
WORDS_FILE = Path(__file__).resolve().parent / "data" / "words.txt"


def _load_dotenv(path: Path) -> None:
    """Minimal .env loader; real environment variables take precedence."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip("'\""))


@dataclass(frozen=True)
class Settings:
    bot_token: str
    admin_ids: frozenset[int] = field(default_factory=frozenset)
    db_path: Path = BASE_DIR / "data" / "wordchain.db"
    required_channel: str | None = None      # e.g. @python_telegram_bots
    required_channel_link: str | None = None
    pvp_turn_seconds: int = 45
    max_strikes: int = 3
    min_word_length: int = 3
    max_hints: int = 2
    translate: bool = True                   # Uzbek translations in the game summary

    @property
    def channel_link(self) -> str | None:
        if self.required_channel_link:
            return self.required_channel_link
        if self.required_channel and self.required_channel.startswith("@"):
            return f"https://t.me/{self.required_channel[1:]}"
        return None


def load_settings() -> Settings:
    _load_dotenv(BASE_DIR / ".env")
    token = os.getenv("BOT_TOKEN", "").strip()
    if not token:
        raise SystemExit("BOT_TOKEN is not set. Copy .env.example to .env and fill it in.")
    admins = frozenset(int(x) for x in os.getenv("ADMIN_IDS", "").replace(" ", "").split(",") if x)
    db_path = Path(os.getenv("DB_PATH", str(BASE_DIR / "data" / "wordchain.db")))
    return Settings(
        bot_token=token,
        admin_ids=admins,
        db_path=db_path if db_path.is_absolute() else BASE_DIR / db_path,
        required_channel=os.getenv("REQUIRED_CHANNEL") or None,
        required_channel_link=os.getenv("REQUIRED_CHANNEL_LINK") or None,
        pvp_turn_seconds=int(os.getenv("PVP_TURN_SECONDS", "45")),
        max_strikes=int(os.getenv("MAX_STRIKES", "3")),
        max_hints=int(os.getenv("MAX_HINTS", "2")),
        translate=os.getenv("TRANSLATE", "1").strip().lower() not in ("0", "false", "no", "off"),
    )
