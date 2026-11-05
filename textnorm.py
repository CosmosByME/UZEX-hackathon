"""Normalization helpers: company names (Cyrillic/Latin Uzbek), product names, regions, language detection."""
import re

APOS = "‘’ʻʼ`´'ʹ′"

_CYR = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "yo", "ж": "j", "з": "z", "и": "i",
    "й": "y", "к": "k", "л": "l", "м": "m", "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t",
    "у": "u", "ф": "f", "х": "x", "ц": "ts", "ч": "ch", "ш": "sh", "щ": "sh", "ъ": "", "ы": "i", "ь": "",
    "э": "e", "ю": "yu", "я": "ya", "ў": "o", "қ": "q", "ғ": "g", "ҳ": "h",
}


def translit(s: str) -> str:
    """Cyrillic (Uzbek/Russian) -> Uzbek Latin, lowercased, apostrophes removed (o‘ -> o)."""
    s = (s or "").lower()
    out = "".join(_CYR.get(ch, ch) for ch in s)
    for a in APOS:
        out = out.replace(a, "")
    return out


_LEGAL = re.compile(
    r"\b(mas\s*uliyati\s+cheklangan\s+jamiyati|masuliyati\s+cheklangan\s+jamiyati|mchj|mchjsi|oaj|aj|xk|qk|"
    r"xususiy\s+korxona(si)?|xorijiy\s+korxona|qo?shma\s+korxona|aksiyadorlik\s+jamiyati|"
    r"ooo|oao|zao|ao|ip|chp|llc|ltd|jsc|inc|unitar\s+korxona|davlat\s+unitar\s+korxonasi|duk|"
    r"obshestvo\s+s\s+ogranichennoy\s+otvetstvennostyu|fermer\s+xo?jaligi|fx|stir)\b"
)


def norm_company(s: str) -> str:
    s = translit(s)
    s = re.sub(r"[«»\"“”„()]", " ", s)
    s = _LEGAL.sub(" ", s)
    s = re.sub(r"[^a-z0-9 ]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


_ROMAN = {"i": "1", "ii": "2", "iii": "3", "iv": "4", "v": "5"}
_ORD = {"перв": "1", "втор": "2", "трет": "3", "четв": "4", "пят": "5"}


def compact_key(norm: str) -> str:
    """Spaces/hyphens removed, so glued typos ('хлопоксырец', 'сырецспот') match the normal spelling."""
    return re.sub(r"[\s\-]", "", norm or "")


def norm_product(s: str) -> str:
    """Canonical key so that '1 сорт', 'Сорт 1 сорт', '1-сорта', 'СОРТ: 1' collapse together."""
    s = (s or "").lower().replace("ё", "е")
    s = re.sub(r"[ ­ -‏ - ⁠﻿]", " ", s)   # invisible / odd spaces
    for a in APOS:
        s = s.replace(a, "")
    s = re.sub(r"[«»\"“”„:;()\[\]{}]", " ", s)
    # word ordinals: 'первый сорт', 'второго класса' -> 1, 2
    s = re.sub(r"\b(перв|втор|трет|четв[её]рт|пят)\w*(?=\s*-?\s*(?:сорт|класс))",
               lambda m: _ORD[m.group(1)[:4]] + " ", s)
    s = re.sub(r"(?<=[а-яa-zўқғҳ])\s*-\s*(?=[а-яa-zўқғҳ])", " ", s)   # 'хлопок-сырец' == 'хлопок сырец'
    s = re.sub(r"(сорт|класс)(?=\d)", r"\1 ", s)                        # 'Сорт1-сорта' == 'Сорт 1-сорта'
    # Roman numerals next to сорт/класс: 'I сорт', 'Iсорт', 'сорт II', 'класс III класс' -> arabic
    s = s.replace("і", "i")                                              # Cyrillic і -> Latin i
    s = re.sub(r"\b(iii|ii|iv|i|v)(?=\s*-?\s*(?:сорт|класс))", lambda m: _ROMAN[m.group(1)] + " ", s)
    s = re.sub(r"(сорт|класс)\s*-?\s*(iii|ii|iv|i|v)\b", lambda m: m.group(1) + " " + _ROMAN[m.group(2)], s)
    s = re.sub(r"(\d+)\s*-?\s*(?:го|ой|й)?\s*(сорт|класс)\w*", r"\1 \2", s)
    s = re.sub(r"\b(сорт|класс)\s+(\d+)\b(?!\s+(?:сорт|класс))", r"\2 \1", s)
    s = re.sub(r"\b(сорт|класс)\s+(?=\d+\s+\1)", "", s)
    s = re.sub(r"\b(марка|размер|тип)\b", " ", s)
    s = re.sub(r"[^0-9a-zа-яўқғҳ.,х\- ]", " ", s)
    s = re.sub(r"(?<!\d)[.,]|[.,](?!\d)", " ", s)
    s = re.sub(r"\s*-\s*", "-", s)
    return re.sub(r"\s+", " ", s).strip(" -.,")


# region -> (canonical Uzbek Latin, Russian)
_REGIONS = [
    (("qoraqalpo", "каракалпак", "қорақалпо", "қорақалпоғ"), "Qoraqalpog‘iston Respublikasi", "Республика Каракалпакстан"),
    (("andijon", "андижан", "андижон"), "Andijon viloyati", "Андижанская область"),
    (("namangan", "наманган"), "Namangan viloyati", "Наманганская область"),
    (("farg", "ферган", "фарғон", "фаргон"), "Farg‘ona viloyati", "Ферганская область"),
    (("samarqand", "самарканд", "самарқанд"), "Samarqand viloyati", "Самаркандская область"),
    (("buxoro", "бухар", "бухоро"), "Buxoro viloyati", "Бухарская область"),
    (("navoiy", "навои", "навоий"), "Navoiy viloyati", "Навоийская область"),
    (("qashqa", "кашкадар", "қашқадар"), "Qashqadaryo viloyati", "Кашкадарьинская область"),
    (("surxon", "сурхандар", "сурхондар"), "Surxondaryo viloyati", "Сурхандарьинская область"),
    (("jizzax", "джизак", "жиззах"), "Jizzax viloyati", "Джизакская область"),
    (("sirdaryo", "сырдар", "сирдар"), "Sirdaryo viloyati", "Сырдарьинская область"),
    (("xorazm", "хорезм", "хоразм"), "Xorazm viloyati", "Хорезмская область"),
]


def canon_region(s: str):
    """Return (uz, ru) canonical region names, or (original, original) if unknown."""
    if not s:
        return None, None
    low = s.lower()
    lat = translit(s)
    for keys, uz, ru in _REGIONS:
        if any(k in low or k in lat for k in keys):
            return uz, ru
    if any(k in low or k in lat for k in ("toshkent", "тошкент", "ташкент", "tashkent")):
        city = any(k in low or k in lat for k in ("shahr", "shahar", "город", "шаҳр", "шахр", "г.", " sh"))
        region = any(k in low or k in lat for k in ("viloyat", "област", "вилоят"))
        if city and not region:
            return "Toshkent shahri", "город Ташкент"
        if region:
            return "Toshkent viloyati", "Ташкентская область"
        return "Toshkent shahri", "город Ташкент"
    return s, s


_UZ_LAT_MARK = re.compile(
    r"\b(nechta|necha|qancha|qaysi|qanday|qachon|yil\w*|oy\w*|bo.?yicha|eng|va|uchun|bilan|kim|nima|edi|"
    r"qil\w*|sot\w*|bitim\w*|narx\w*|o.?rtacha|jami|chiqar\w*|ko.?rsat\w*|ayt\w*|xarid\w*|tuz\w*|"
    r"mahsulot\w*|tovar\w*|kompaniya\w*|korxona\w*|viloyat\w*|summa\w*|hajm\w*|savdo\w*|birja\w*)\b"
    r"|[og][‘’ʻʼ'`]")
_UZ_CYR_MARK = re.compile(
    r"[ўқғҳ]|\b(нечта|неча|қанча|қайси|қандай|йил\w*|бўйича|энг|ва|учун|билан|ким|нима|эди|"
    r"битим\w*|тузил\w*|сотил\w*|нарх\w*|ўртача|жами|ой\w*|маҳсулот\w*|корхона\w*|вилоят\w*)\b")
_RU_MARK = re.compile(
    r"\b(сколько|какой|какая|какие|каков\w*|кто|что|сделк\w*|год\w*|году|месяц\w*|за|по|в|на|и|из|"
    r"самы\w*|средн\w*|цен\w*|покупател\w*|продав\w*|товар\w*|объ[её]м\w*|оборот\w*|был\w*|есть)\b")


def detect_lang(text: str) -> str:
    """'ru', 'uz' (Latin) or 'uzc' (Uzbek Cyrillic). Word-based, so Latin company names inside a Russian
    question ('Сделки Artel Electronics Group') or a Cyrillic product name inside an Uzbek one
    ('2025-yilda цемент narxi') do not flip the language."""
    t = (text or "").lower()
    cyr_words = re.findall(r"[а-яёўқғҳ]{2,}", t)
    lat_words = re.findall(r"[a-z]{2,}", t)
    uz_lat = len(_UZ_LAT_MARK.findall(t))
    if cyr_words:
        uzc = len(_UZ_CYR_MARK.findall(t))
        ru = len(_RU_MARK.findall(t))
        if uz_lat and uz_lat >= max(uzc, ru) and len(lat_words) >= len(cyr_words) / 2:
            return "uz"
        if uzc or ru or len(cyr_words) >= len(lat_words):
            return "uzc" if uzc > ru or re.search(r"[ўқғҳ]", t) else "ru"
    return "uz"


def split_questions(text: str) -> list:
    """Rough split of a message into separate questions (by lines, numbering, '?'). The LLM makes the final call
    on whether they are really independent; this is only used for the language hint and the step budget."""
    t = (text or "").strip()
    parts = []
    for line in re.split(r"\n+", t):
        line = re.sub(r"^\s*(?:\d+[.)]|[-•*])\s*", "", line).strip()
        parts += [p.strip() for p in re.split(r"(?<=\?)\s+", line) if p.strip()]
    parts = [p for p in parts if len(re.findall(r"\w+", p)) >= 2]
    return parts or ([t] if t else [])


# ---------------- Uzbek (Latin / Cyrillic) and English product words -> Russian registry words ----------------
# keys are in the translit() form: lowercase Latin, apostrophes removed (o‘ -> o, g‘ -> g), Cyrillic Uzbek converted
_PROD_UZ_RU = {
    # cotton & textile
    "paxta xom ashyosi": "хлопок-сырец", "xom ashyo paxta": "хлопок-сырец", "xom paxta": "хлопок-сырец",
    "paxta tolasi": "хлопковое волокно", "paxta yogi": "хлопковое масло", "paxta shroti": "шрот хлопковый",
    "paxta chigiti": "семена хлопчатника", "chigit": "семена хлопчатника", "paxta": "хлопок",
    "ip kalava": "пряжа", "ip-kalava": "пряжа", "kalava": "пряжа", "ip": "пряжа", "tola": "волокно",
    "raw cotton": "хлопок-сырец", "cotton fiber": "хлопковое волокно", "cotton": "хлопок", "yarn": "пряжа",
    # grain & food
    "bugdoy": "пшеница", "arpa": "ячмень", "makkajoxori": "кукуруза", "guruch": "рис", "un": "мука",
    "shakar": "сахар", "tuz": "соль", "osimlik yogi": "масло растительное", "kungaboqar yogi": "масло подсолнечное",
    "kungaboqar": "подсолнечник", "soya": "соя", "yog": "масло", "kunjara": "жмых", "shrot": "шрот",
    "urugligi": "семена", "uruglik": "семена", "urug": "семена", "gosht": "мясо", "sut": "молоко", "tuxum": "яйцо",
    "kartoshka": "картофель", "piyoz": "лук", "sabzi": "морковь", "choy": "чай", "makaron": "макарон",
    "wheat": "пшеница", "barley": "ячмень", "corn": "кукуруза", "maize": "кукуруза", "rice": "рис", "flour": "мука",
    "sugar": "сахар", "salt": "соль", "vegetable oil": "масло растительное",
    # construction
    "sement": "цемент", "gisht": "кирпич", "shagal": "щебень", "qum": "песок", "ohak": "известь", "gips": "гипс",
    "shisha": "стекло", "yogoch": "лесоматериал", "taxta": "пиломатериал", "armatura": "арматура",
    "metall prokat": "металлопрокат", "prokat": "прокат", "metall": "металл", "cement": "цемент", "brick": "кирпич",
    # metals
    "mis": "медь", "alyuminiy": "алюминий", "temir": "железо", "polat": "сталь", "rux": "цинк", "qorgoshin": "свинец",
    "oltin": "золото", "kumush": "серебро", "copper": "медь", "steel": "сталь",
    # fuel & energy
    "komir": "уголь", "benzin": "бензин", "dizel yoqilgisi": "топливо дизельное", "dizel": "дизельное",
    "suyultirilgan gaz": "сжиженный газ", "tabiiy gaz": "природный газ", "gaz": "газ", "neft": "нефть",
    "mazut": "мазут", "bitum": "битум", "kerosin": "керосин", "moy": "масло", "motor moyi": "масло моторное",
    "coal": "уголь", "gasoline": "бензин", "petrol": "бензин", "diesel": "дизельное", "oil": "масло",
    # chemistry & fertilisers
    "ammiakli selitra": "аммиачная селитра", "selitra": "селитра", "karbamid": "карбамид", "mochevina": "карбамид",
    "mineral ogitlar": "удобрения", "mineral ogit": "удобрения", "ogitlar": "удобрения", "ogit": "удобрения",
    "oltingugurt": "сера", "polietilen": "полиэтилен", "polipropilen": "полипропилен", "ammiak": "аммиак",
    "kaustik soda": "сода каустическая", "soda": "сода", "kislota": "кислота", "sulfat": "сульфат",
    "superfosfat": "суперфосфат", "ammofos": "аммофос", "kaliy": "калий", "spirt": "спирт", "qogoz": "бумага",
    "urea": "карбамид", "ammonium nitrate": "аммиачная селитра", "sulfur": "сера", "fertilizer": "удобрения",
    # grades
    "nav": "сорт", "navli": "сорт", "sinf": "класс", "sinfli": "класс",
}
_UZ_SUFFIX = ("larining", "larini", "laridan", "larida", "lariga", "ларнинг", "ning", "dagi", "dan", "lar", "ni",
              "ga", "da", "si", "ini", "i")
_PHRASES = sorted(_PROD_UZ_RU, key=lambda k: -len(k.split()))


def _uz_token_ru(tok: str):
    if tok in _PROD_UZ_RU:
        return _PROD_UZ_RU[tok]
    for suf in _UZ_SUFFIX:
        if tok.endswith(suf) and len(tok) - len(suf) >= 3 and tok[:-len(suf)] in _PROD_UZ_RU:
            return _PROD_UZ_RU[tok[:-len(suf)]]
    return None


def product_query_ru(text: str) -> str:
    """'paxta xom ashyosining 1-navi' -> 'хлопок-сырец 1 сорт'; 'буғдой' -> 'пшеница'. Returns '' if nothing was translated."""
    t = translit(text)
    t = re.sub(r"(\d+)\s*-\s*", r"\1 ", t)                       # '1-nav' -> '1 nav'
    toks = re.findall(r"[a-z0-9\-]+", t)
    out, i, changed = [], 0, False
    while i < len(toks):
        for n in (3, 2):                                           # multi-word phrases first
            if i + n <= len(toks):
                ph = " ".join(toks[i:i + n])
                last = _uz_token_ru(toks[i + n - 1])
                base = " ".join(toks[i:i + n - 1])
                hit = _PROD_UZ_RU.get(ph)
                if hit is None:                                    # suffix on the last word of the phrase
                    for k in _PHRASES:
                        if len(k.split()) == n and k.startswith(base + " ") and toks[i + n - 1].startswith(k.split()[-1]):
                            hit = _PROD_UZ_RU[k]
                            break
                if hit:
                    out.append(hit); i += n; changed = True
                    break
        else:
            ru = _uz_token_ru(toks[i])
            out.append(ru or toks[i]); changed |= ru is not None; i += 1
    return " ".join(out) if changed else ""
