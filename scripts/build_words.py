"""Builds bot/data/words.txt from the `wordfreq` package.

    python scripts/build_words.py                 # auto-detects a system dictionary
    python scripts/build_words.py --dict en_US.dic

The file lists one word per line, most frequent first; the line number is the
word's rank, and ranks map to CEFR-like levels (bot/levels.py).

wordfreq alone cannot tell "sheep" from "samuel" (it is lowercased), so if a
Hunspell .dic or a plain word list is available, words are kept only when the
dictionary knows them (directly or via a simple suffix rule) and dropped when
it lists them only capitalized (proper nouns). On Debian/Ubuntu:
    sudo apt install hunspell-en-us      ->  /usr/share/hunspell/en_US.dic

After rebuilding, delete the `words` table (or the whole database) so the bot
re-seeds it on the next start.
"""
import argparse
import re
from pathlib import Path

from wordfreq import top_n_list, zipf_frequency

SCRIPTS = Path(__file__).resolve().parent
OUT = SCRIPTS.parent / "bot" / "data" / "words.txt"
EXTRA_FILE = SCRIPTS / "extra_words.txt"         # always allowed (modern words, irregular forms)
BLOCKED_FILE = SCRIPTS / "blocked_words.txt"     # never allowed (profanity, slang)
REVIEW_FILE = SCRIPTS / "rejected_review.txt"
SYSTEM_DICTS = [
    Path("/usr/share/hunspell/en_US.dic"),
    Path("/usr/share/myspell/en_US.dic"),
    Path("/usr/share/hunspell/en_GB.dic"),
    Path("/usr/share/dict/words"),
]

WORD_RE = re.compile(r"^[a-z]{3,20}$")
HAS_VOWEL = re.compile(r"[aeiouy]")
# frequent tokens that are not dictionary words
BLACKLIST = {
    "www", "http", "https", "com", "org", "net", "html", "php", "url", "pdf",
    "lol", "omg", "wtf", "lmao", "btw", "imo", "ppl", "pls", "thx", "gonna",
    "wanna", "gotta", "ain", "doesn", "didn", "isn", "wasn", "couldn",
    "wouldn", "shouldn", "hasn", "haven", "aren", "weren", "don",
    "ive", "youre", "thats", "theres", "dont", "cant", "wont", "didnt",
    "doesnt", "isnt", "wasnt", "arent", "werent", "couldnt", "wouldnt",
    "shouldnt", "hasnt", "havent", "hadnt", "ver", "von", "und", "les",
    "que", "una", "het", "los", "las", "der", "die", "das", "del", "dos",
    "por", "para", "est", "pas", "bla", "jpg", "png", "gif", "faq",
    "xxx", "aaa", "ooo", "hmm", "ugh", "yep", "nope", "nah",
}
SUFFIXES = [
    ("ies", "y"), ("ied", "y"), ("ier", "y"), ("iest", "y"), ("ily", "y"),
    ("ing", ""), ("ing", "e"), ("ings", ""), ("ed", ""), ("ed", "e"), ("d", ""),
    ("es", ""), ("s", ""), ("er", ""), ("er", "e"), ("ers", ""), ("ers", "e"),
    ("est", ""), ("est", "e"), ("ly", ""), ("ness", ""), ("ment", ""),
]


def load_lexicon(path: Path) -> tuple[set[str], set[str]]:
    """(lowercase words, proper nouns) from a Hunspell .dic or a plain list."""
    lower: set[str] = set()
    capital: set[str] = set()
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        w = line.split("/", 1)[0].strip()
        if not w.isalpha():
            continue
        (lower if w.islower() else capital).add(w.lower())
    return lower, capital - lower


def in_lexicon(word: str, lex: set[str]) -> bool:
    if word in lex:
        return True
    for suffix, repl in SUFFIXES:
        if word.endswith(suffix) and len(word) - len(suffix) >= 2:
            stem = word[: -len(suffix)]
            if stem + repl in lex:
                return True
            if not repl and len(stem) >= 3 and stem[-1] == stem[-2] and stem[:-1] in lex:
                return True  # running -> run, stopped -> stop
    return False


def load_english_words() -> tuple[set[str], set[str]] | None:
    """Lexicon from the `english-words` package. Only Webster's web2 is used: it keeps
    capitalization, so proper nouns are recognizable (GCIDE capitalizes every headword)."""
    try:
        from english_words import get_english_words_set
    except ImportError:
        return None
    web2 = get_english_words_set(["web2"], lower=False, alpha=True)
    lower = {w for w in web2 if w.islower()}
    proper = {w.lower() for w in web2 if not w.islower()} - lower
    return lower, proper


def load_word_file(path: Path) -> set[str]:
    """Whitespace-separated words; '#' starts a comment."""
    words: set[str] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        words.update(line.split("#", 1)[0].lower().split())
    return words


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dict", type=Path, help="Hunspell .dic or plain word list used as a filter")
    parser.add_argument("--min-zipf", type=float, default=2.4, help="lower = bigger dictionary (default 2.4)")
    parser.add_argument("--review-zipf", type=float, default=3.8,
                        help="frequent words rejected by the lexicon are listed in rejected_review.txt")
    parser.add_argument("--max-words", type=int, default=90_000)
    args = parser.parse_args()

    allowed = load_word_file(EXTRA_FILE)
    blocked = load_word_file(BLOCKED_FILE)

    lexicon = proper = None
    dict_path = args.dict or next((p for p in SYSTEM_DICTS if p.exists()), None)
    if dict_path:
        lexicon, proper = load_lexicon(dict_path)
        print(f"filtering with {dict_path} ({len(lexicon)} words, {len(proper)} proper nouns)")
    elif (loaded := load_english_words()) is not None:
        lexicon, proper = loaded
        print(f"filtering with english-words ({len(lexicon)} words, {len(proper)} proper nouns)")
    else:
        print("no dictionary found: proper nouns will not be filtered (pip install english-words, or --dict)")

    words: list[str] = []
    review: list[str] = []   # frequent but rejected: candidates for extra_words.txt
    for w in top_n_list("en", 400_000, wordlist="best"):
        zipf = zipf_frequency(w, "en")
        if zipf < args.min_zipf:
            break  # the list is sorted by frequency
        if (not WORD_RE.match(w) or w in BLACKLIST or w in blocked
                or not HAS_VOWEL.search(w) or len(set(w)) == 1):
            continue
        # "kids" is also a surname in web2, but it derives from "kid", so it passes here
        if lexicon is not None and w not in allowed and not in_lexicon(w, lexicon):
            if zipf >= args.review_zipf and w not in proper:
                review.append(w)
            continue
        words.append(w)
        if len(words) >= args.max_words:
            break

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(words) + "\n", encoding="utf-8")
    print(f"{len(words)} words -> {OUT}")
    REVIEW_FILE.write_text("\n".join(review) + "\n", encoding="utf-8")
    print(f"{len(review)} frequent words rejected -> {REVIEW_FILE.name} (add real ones to {EXTRA_FILE.name})")


if __name__ == "__main__":
    main()
