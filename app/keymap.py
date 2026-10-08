"""
Karakter -> tuş eşlemeleri.

uinput "fiziksel tuş" gönderir; ekranda hangi harfin çıkacağına tahtadaki
klavye düzeni (xkb) karar verir. Bu yüzden telefondan gelen her karakteri,
tahtada seçili düzende o karakteri üreten tuş + değiştirici (Shift/AltGr)
kombinasyonuna çeviriyoruz.

Desteklenen düzenler: "tr" (Türkçe Q - Pardus varsayılanı) ve "us".
Her girdi: karakter -> (tuş_adı, [değiştiriciler], ölü_tuş_mu)
Ölü tuşlarda (ör. TR-Q'da ^) karakterin çıkması için ardından Boşluk basılır.
"""

from string import ascii_lowercase

# Telefon klavyelerinin "akıllı noktalama" ile ürettiği karakterleri sadeleştir
NORMALIZE = {
    "‘": "'", "’": "'", "‚": "'", "′": "'",
    "“": '"', "”": '"', "„": '"', "«": '"', "»": '"',
    "–": "-", "—": "-", "−": "-",
    "…": "...",
    " ": " ", " ": " ", " ": " ",
    "\r\n": "\n", "\r": "\n",
}

# Özel tuşlar (telefon arayüzündeki butonlar bunları isimle gönderir)
SPECIAL_KEYS = {
    "enter": "KEY_ENTER", "backspace": "KEY_BACKSPACE", "tab": "KEY_TAB",
    "esc": "KEY_ESC", "space": "KEY_SPACE", "delete": "KEY_DELETE",
    "insert": "KEY_INSERT",
    "up": "KEY_UP", "down": "KEY_DOWN", "left": "KEY_LEFT", "right": "KEY_RIGHT",
    "home": "KEY_HOME", "end": "KEY_END",
    "pageup": "KEY_PAGEUP", "pagedown": "KEY_PAGEDOWN",
    "ctrl": "KEY_LEFTCTRL", "alt": "KEY_LEFTALT", "shift": "KEY_LEFTSHIFT",
    "super": "KEY_LEFTMETA", "altgr": "KEY_RIGHTALT", "menu": "KEY_COMPOSE",
    "print": "KEY_SYSRQ",
    "volup": "KEY_VOLUMEUP", "voldown": "KEY_VOLUMEDOWN", "mute": "KEY_MUTE",
    **{f"f{i}": f"KEY_F{i}" for i in range(1, 13)},
}

SHIFT = "KEY_LEFTSHIFT"
ALTGR = "KEY_RIGHTALT"

_DIGIT_KEYS = {str(d): f"KEY_{d}" for d in range(10)}


def _us():
    m = {}
    for ch in ascii_lowercase:
        k = f"KEY_{ch.upper()}"
        m[ch] = (k, [], False)
        m[ch.upper()] = (k, [SHIFT], False)
    for d, k in _DIGIT_KEYS.items():
        m[d] = (k, [], False)
    base = {
        " ": "KEY_SPACE", "-": "KEY_MINUS", "=": "KEY_EQUAL",
        "[": "KEY_LEFTBRACE", "]": "KEY_RIGHTBRACE", "\\": "KEY_BACKSLASH",
        ";": "KEY_SEMICOLON", "'": "KEY_APOSTROPHE", "`": "KEY_GRAVE",
        ",": "KEY_COMMA", ".": "KEY_DOT", "/": "KEY_SLASH",
    }
    shifted = {
        "!": "KEY_1", "@": "KEY_2", "#": "KEY_3", "$": "KEY_4", "%": "KEY_5",
        "^": "KEY_6", "&": "KEY_7", "*": "KEY_8", "(": "KEY_9", ")": "KEY_0",
        "_": "KEY_MINUS", "+": "KEY_EQUAL", "{": "KEY_LEFTBRACE",
        "}": "KEY_RIGHTBRACE", "|": "KEY_BACKSLASH", ":": "KEY_SEMICOLON",
        '"': "KEY_APOSTROPHE", "~": "KEY_GRAVE", "<": "KEY_COMMA",
        ">": "KEY_DOT", "?": "KEY_SLASH",
    }
    for ch, k in base.items():
        m[ch] = (k, [], False)
    for ch, k in shifted.items():
        m[ch] = (k, [SHIFT], False)
    return m


def _tr_q():
    m = {}
    # i hariç Latin harfleri ABD ile aynı fiziksel yerde
    for ch in ascii_lowercase:
        if ch == "i":
            continue
        k = f"KEY_{ch.upper()}"
        m[ch] = (k, [], False)
        m[ch.upper()] = (k, [SHIFT], False)
    # Türkçe harfler
    tr_letters = {
        "ı": ("KEY_I", "I"),
        "i": ("KEY_APOSTROPHE", "İ"),
        "ğ": ("KEY_LEFTBRACE", "Ğ"),
        "ü": ("KEY_RIGHTBRACE", "Ü"),
        "ş": ("KEY_SEMICOLON", "Ş"),
        "ö": ("KEY_COMMA", "Ö"),
        "ç": ("KEY_DOT", "Ç"),
    }
    for low, (k, up) in tr_letters.items():
        m[low] = (k, [], False)
        m[up] = (k, [SHIFT], False)

    for d, k in _DIGIT_KEYS.items():
        m[d] = (k, [], False)

    base = {
        " ": "KEY_SPACE",
        '"': "KEY_GRAVE",
        "*": "KEY_MINUS",
        "-": "KEY_EQUAL",
        ".": "KEY_SLASH",
        ",": "KEY_BACKSLASH",
        "<": "KEY_102ND",
    }
    shifted = {
        "!": "KEY_1", "'": "KEY_2", "+": "KEY_4", "%": "KEY_5", "&": "KEY_6",
        "/": "KEY_7", "(": "KEY_8", ")": "KEY_9", "=": "KEY_0",
        "?": "KEY_MINUS", "_": "KEY_EQUAL", ":": "KEY_SLASH",
        ";": "KEY_BACKSLASH", ">": "KEY_102ND", "é": "KEY_GRAVE",
    }
    altgr = {
        "@": "KEY_Q", "€": "KEY_E", "#": "KEY_3", "$": "KEY_4",
        "½": "KEY_5", "{": "KEY_7", "[": "KEY_8", "]": "KEY_9",
        "}": "KEY_0", "\\": "KEY_MINUS", "|": "KEY_EQUAL",
        "~": "KEY_RIGHTBRACE", "`": "KEY_BACKSLASH",
    }
    for ch, k in base.items():
        m[ch] = (k, [], False)
    for ch, k in shifted.items():
        m[ch] = (k, [SHIFT], False)
    for ch, k in altgr.items():
        m[ch] = (k, [ALTGR], False)
    # Shift+3 TR-Q'da ölü şapka (^) tuşudur
    m["^"] = ("KEY_3", [SHIFT], True)
    return m


LAYOUTS = {"tr": _tr_q, "us": _us}


def get_layout(name: str) -> dict:
    return LAYOUTS.get((name or "tr").lower(), _tr_q)()


def normalize(text: str) -> str:
    for a, b in NORMALIZE.items():
        text = text.replace(a, b)
    return text
