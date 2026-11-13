"""All user-facing text (HTML parse mode). Uzbek UI, English game words."""
from html import escape

from .db import UserProfile
from .engine import Outcome, Reject
from .levels import BOT_TURN_SECONDS, LEVEL_TITLES, Level

HINT_BTN = "💡 Yordam"
RESIGN_BTN = "🏳️ Taslim bo'lish"
DIVIDER = "━━━━━━━━━━━━━━"


def esc(text: str) -> str:
    return escape(text, quote=False)


def lvl(level: Level | int) -> str:
    return Level(level).name


def word_tag(word: str, level: Level | None) -> str:
    return f"<b>{esc(word.capitalize())}</b>" + (f" <i>({level.name})</i>" if level is not None else "")


def pct(wins: int, games: int) -> str:
    return f"{round(100 * wins / games)}%" if games else "—"


# ------------------------------------------------------------------ menus

def welcome(p: UserProfile) -> str:
    return (
        f"👋 Salom, <b>{esc(p.display_name)}</b>!\n\n"
        "🔤 <b>Word Chain</b> — inglizcha so'z zanjiri o'yini.\n"
        "Har bir so'z oldingi so'zning <b>oxirgi harfi</b> bilan boshlanadi:\n"
        "<i>apple → egg → green → nice → ...</i>\n\n"
        f"Darajangiz: <b>{lvl(p.level)}</b> · ⭐ Reyting: <b>{p.rating}</b>\n\n"
        "O'yin turini tanlang 👇"
    )


def rules(settings_pvp_seconds: int, max_strikes: int, max_hints: int, min_len: int) -> str:
    times = " · ".join(f"{lv.name} {s}s" for lv, s in BOT_TURN_SECONDS.items())
    return (
        "📖 <b>O'yin qoidalari</b>\n\n"
        "1️⃣ Har bir so'z oldingi so'zning <b>oxirgi harfi</b> bilan boshlanadi.\n"
        f"2️⃣ Faqat inglizcha so'zlar, kamida <b>{min_len}</b> harf. Ismlar, shahar va davlat nomlari"
        " qabul qilinmaydi (hafta kunlari, oylar va tillar mumkin).\n"
        "3️⃣ Bitta o'yinda so'z <b>takrorlanmaydi</b>.\n"
        f"4️⃣ Har bir yurishga vaqt beriladi:\n    🤖 {times}\n    👥 Odam bilan: {settings_pvp_seconds}s\n"
        f"5️⃣ <b>{max_strikes}</b> marta noto'g'ri so'z yozsangiz, yutqazasiz.\n"
        f"6️⃣ Bot bilan o'yinda <b>{max_hints}</b> marta 💡 yordam olishingiz mumkin.\n\n"
        "🤖 <b>Bot qanday o'ynaydi?</b>\n"
        "Bot faqat o'z darajasidagi so'zlarni biladi. U odamga o'xshab o'ylaydi,"
        " charchaydi va adashadi, shuning uchun uni yutish mumkin. Yuqori darajadagi bot"
        " esa sizga ataylab qiyin harflarni qoldiradi 😈\n\n"
        "⭐ <b>Reyting</b> (Elo) faqat odam bilan o'ynalgan o'yinlarda o'zgaradi."
    )


def level_picker(current: Level) -> str:
    lines = "\n".join(
        f"{'✅' if lv == current else '▫️'} <b>{lv.name}</b> — {LEVEL_TITLES[lv]}" for lv in Level
    )
    return (
        "<b>Ingliz tili darajangizni tanlang</b>\n\n"
        f"{lines}\n\n"
        "Bot sizning darajangizga moslashadi va raqib ham shu darajadan qidiriladi."
    )


def level_set(level: Level) -> str:
    return f"✅ Darajangiz: <b>{level.name}</b> — {LEVEL_TITLES[level]}"


def bot_difficulty(level: Level) -> str:
    return (
        "🤖 <b>Bot bilan o'yin</b>\n\n"
        f"Sizning darajangiz: <b>{level.name}</b>\n"
        "Bot qanday darajada o'ynasin?"
    )


def stats(p: UserProfile, position: int | None, vocab: dict[Level, int]) -> str:
    vocab_line = " · ".join(f"{lv.name} {vocab.get(lv, 0)}" for lv in Level)
    unique = sum(vocab.values())
    pos = f" (#{position})" if position else ""
    return (
        f"📊 <b>Statistika — {esc(p.display_name)}</b>\n{DIVIDER}\n"
        f"Daraja: <b>{lvl(p.level)}</b> · ⭐ Reyting: <b>{p.rating}</b>{pos}\n\n"
        f"🤖 Bot bilan: <b>{p.bot_games}</b> o'yin · {p.bot_wins} g'alaba ({pct(p.bot_wins, p.bot_games)})\n"
        f"👥 Odam bilan: <b>{p.pvp_games}</b> o'yin · {p.pvp_wins} g'alaba ({pct(p.pvp_wins, p.pvp_games)})\n"
        f"🔥 G'alaba seriyasi: <b>{p.streak}</b> (rekord: {p.best_streak})\n\n"
        f"📝 Yozilgan so'zlar: <b>{p.words_played}</b> · takrorlanmas: <b>{unique}</b>\n"
        f"📏 Eng uzun so'z: <b>{esc(p.longest_word) or '—'}</b>\n\n"
        f"📚 <b>Lug'atingiz darajalar bo'yicha:</b>\n{vocab_line}"
    )


MEDALS = {1: "🥇", 2: "🥈", 3: "🥉"}


def leaderboard(players: list[UserProfile], wordsmiths: list[UserProfile], me: UserProfile,
                position: int | None) -> str:
    out = [f"🏆 <b>Reyting jadvali</b> (odam bilan o'yinlar)\n{DIVIDER}"]
    if players:
        for i, p in enumerate(players, 1):
            out.append(f"{MEDALS.get(i, f'{i}.')} {esc(p.display_name)} — <b>{p.rating}</b>"
                       f" <i>({p.pvp_wins}/{p.pvp_games})</i>")
    else:
        out.append("Hali hech kim odam bilan o'ynamagan. Birinchi bo'ling! 💪")
    if wordsmiths:
        out.append(f"\n📝 <b>Eng ko'p so'z yozganlar</b>\n{DIVIDER}")
        for i, p in enumerate(wordsmiths[:5], 1):
            out.append(f"{MEDALS.get(i, f'{i}.')} {esc(p.display_name)} — <b>{p.words_played}</b>")
    out.append(f"\n👤 Siz: ⭐ <b>{me.rating}</b>" + (f" · #{position}" if position else " · hali reytingda emassiz"))
    return "\n".join(out)


# ------------------------------------------------------------- matchmaking

QUEUE_WAITING = "🔎 <b>Raqib qidirilmoqda...</b>\n\nSizga mos darajadagi o'yinchi topilishi bilan o'yin boshlanadi."
QUEUE_ALREADY = "🔎 Siz allaqachon navbatdasiz, raqib qidirilmoqda..."
QUEUE_OFFER = ("😴 Hozircha bo'sh raqib yo'q.\n\nKutishda davom etishingiz yoki hozircha"
               " bot bilan o'ynab turishingiz mumkin.")
QUEUE_LEFT = "❌ Qidiruv bekor qilindi."
BUSY = "🎮 Siz hozir o'yindasiz! Avval uni tugating yoki 🏳️ taslim bo'ling."
NOTHING_TO_CANCEL = "Bekor qilinadigan narsa yo'q."
NOT_IN_GAME = "🤔 Hozir o'yinda emassiz. Menyudan o'yin turini tanlang 👇"
WAITING_IN_QUEUE = "🔎 Raqib qidirilmoqda, biroz kuting..."


def invite(link: str) -> str:
    return (
        "🔗 <b>Do'stingizni taklif qiling</b>\n\n"
        "Quyidagi havolani do'stingizga yuboring. U havolani ochishi bilan o'yin boshlanadi:\n\n"
        f"<code>{esc(link)}</code>\n\n⏳ Havola 10 daqiqa amal qiladi."
    )


def invite_share_text() -> str:
    return "Keling, inglizcha so'z zanjiri o'ynaymiz! 🔤⚔️"


INVITE_CANCELLED = "❌ Taklif bekor qilindi."
INVITE_EXPIRED = "⌛ Bu taklif muddati tugagan yoki bekor qilingan."
INVITE_SELF = "😄 O'zingizni o'zingiz taklif qila olmaysiz. Havolani do'stingizga yuboring!"
INVITE_HOST_BUSY = "⏳ Sizni taklif qilgan o'yinchi hozir boshqa o'yinda. Keyinroq urinib ko'ring."


# ----------------------------------------------------------------- in game

def bot_game_started(bot_name: str, level: Level, seconds: float, max_strikes: int, max_hints: int) -> str:
    return (
        f"🎮 <b>O'yin boshlandi!</b>\n{DIVIDER}\n"
        f"🤖 Raqib: <b>{esc(bot_name)}</b> · {level.name}\n"
        f"⏱ Har yurishga: <b>{round(seconds)}s</b> · ❌ Xato chegarasi: {max_strikes}\n"
        f"💡 Yordam: {max_hints} ta\n\n"
        "✍️ <b>Siz boshlaysiz</b> — istalgan inglizcha so'zni yozing!"
    )


def pvp_started(opponent: str, opp_level: Level, opp_rating: int, your_turn: bool, seconds: float,
                max_strikes: int) -> str:
    turn = ("✍️ <b>Siz boshlaysiz</b> — istalgan inglizcha so'zni yozing!" if your_turn
            else "⏳ Raqib boshlaydi, kuting...")
    return (
        f"⚔️ <b>Raqib topildi!</b>\n{DIVIDER}\n"
        f"👤 Raqib: <b>{esc(opponent)}</b> · {opp_level.name} · ⭐ {opp_rating}\n"
        f"⏱ Har yurishga: <b>{round(seconds)}s</b> · ❌ Xato chegarasi: {max_strikes}\n\n{turn}"
    )


def your_turn_line(letter: str, seconds: float) -> str:
    return f"➡️ Sizga: <b>{letter.upper()}</b> harfi · ⏱ {round(seconds)}s"


def bot_move(name: str, word: str, level: Level | None, seconds: float) -> str:
    return f"🤖 <b>{esc(name)}</b>: {word_tag(word, level)}\n{your_turn_line(word[-1], seconds)}"


def opponent_move(name: str, word: str, level: Level | None, seconds: float) -> str:
    return f"👤 <b>{esc(name)}</b>: {word_tag(word, level)}\n{your_turn_line(word[-1], seconds)}"


def bot_says(name: str, phrase: str) -> str:
    return f"🤖 <b>{esc(name)}</b>: <i>{esc(phrase)}</i>"


def accepted(word: str, level: Level | None) -> str:
    return f"✅ {word_tag(word, level)}"


def not_your_turn(name: str) -> str:
    return f"⏳ Hozir <b>{esc(name)}</b> navbati, kuting."


def time_warning(seconds: int) -> str:
    return f"⏳ <b>{seconds} soniya</b> qoldi!"


FORMAT_HINT = "⚠️ Faqat <b>bitta</b> inglizcha so'z yozing (lotin harflarida)."


def rejected(reason: Reject, word: str, letter: str | None, strikes: int, max_strikes: int) -> str:
    w = f"<b>{esc(word)}</b>"
    why = {
        Reject.TOO_SHORT: f"❌ {w} — juda qisqa so'z.",
        Reject.WRONG_LETTER: f"❌ {w} — so'z <b>{(letter or '').upper()}</b> harfi bilan boshlanishi kerak.",
        Reject.USED: f"❌ {w} — bu so'z bu o'yinda allaqachon ishlatilgan.",
        Reject.UNKNOWN: f"❌ {w} — lug'atda bunday so'z topilmadi.",
    }[reason]
    left = max_strikes - strikes
    tail = f"\n⚠️ Xato: <b>{strikes}/{max_strikes}</b>" + (" — ehtiyot bo'ling!" if left == 1 else "")
    return why + tail


HINTS_PVP = "💡 Odam bilan o'yinda yordam o'chirilgan — adolatli o'yin! 😉"
HINTS_OVER = "💡 Yordamlar tugadi."
HINT_NOT_FOUND = "💡 Afsus, bu harf uchun maslahat topilmadi."
HINT_WAIT = "💡 Yordamni o'z navbatingizda so'rashingiz mumkin."


def hint(word: str, left: int) -> str:
    shown = 2 if len(word) > 4 else 1
    masked = " ".join(c if i < shown or i == len(word) - 1 else "_" for i, c in enumerate(word))
    return f"💡 Maslahat: <code>{masked}</code> ({len(word)} harf)\nQolgan yordamlar: <b>{left}</b>"


RESIGN_CONFIRM = "🏳️ Rostdan ham taslim bo'lasizmi?"
GAME_ABORTED = "⚠️ Bot qayta ishga tushirilmoqda, o'yin bekor qilindi. Uzr! 🙏"


def _reason(outcome: Outcome, you_lost: bool, opponent: str) -> str:
    o = f"<b>{esc(opponent)}</b>"
    if outcome is Outcome.TIMEOUT:
        return "⏰ Vaqtingiz tugadi" if you_lost else f"⏰ {o} vaqtida javob bermadi"
    if outcome is Outcome.STRIKES:
        return "❌ Juda ko'p xato qildingiz" if you_lost else f"❌ {o} juda ko'p xato qildi"
    if outcome is Outcome.RESIGN:
        return "🏳️ Siz taslim bo'ldingiz" if you_lost else f"🏳️ {o} taslim bo'ldi"
    return f"🤖 {o} so'z topa olmadi"


def game_over(
    *,
    won: bool,
    outcome: Outcome,
    opponent: str,
    total: int,
    mine: int,
    theirs: int,
    longest: str | None,
    rating: tuple[int, int] | None,
    learn: list[tuple[str, Level | None, str | None]],
) -> str:
    head = "🏆 <b>G'ALABA!</b>" if won else "😔 <b>Mag'lubiyat</b>"
    out = [f"{head}\n{_reason(outcome, not won, opponent)}\n{DIVIDER}",
           f"📝 Jami so'zlar: <b>{total}</b> (siz: {mine}, raqib: {theirs})"]
    if longest:
        out.append(f"📏 Eng uzun so'z: <b>{esc(longest)}</b>")
    if rating:
        before, after = rating
        diff = after - before
        out.append(f"⭐ Reyting: {before} → <b>{after}</b> ({'+' if diff >= 0 else ''}{diff})")
    if learn:
        lines = "\n".join(
            f"• <b>{esc(w)}</b>" + (f" <i>({lv.name})</i>" if lv is not None else "")
            + (f" — {esc(uz)}" if uz else "")
            for w, lv, uz in learn
        )
        out.append(f"\n📚 <b>Raqib ishlatgan so'zlar</b> — yodlab oling:\n{lines}")
    return "\n".join(out)


PLAY_AGAIN = "Yana o'ynaymizmi? 👇"


# ------------------------------------------------------------------ misc

SUBSCRIBE = ("📢 Botdan foydalanish uchun kanalimizga obuna bo'ling, so'ng "
             "<b>✅ Tekshirish</b> tugmasini bosing.")
SUBSCRIBE_ALERT = "❗ Avval kanalga obuna bo'ling"
REPORT_THANKS = "Rahmat! Admin ko'rib chiqadi ✅"
REPORT_DUP = "Siz bu so'z haqida allaqachon xabar bergansiz 👍"
REPORT_ALREADY_IN = "Bu so'z allaqachon lug'atda bor ✅"
