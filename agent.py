"""The AI agent: an LLM that answers ONLY by calling tools over the exchange database.

Loop:  question -> LLM decides which tool to call (sql / find_company / find_product)
       -> we run it -> result goes back to the LLM -> ... -> final answer
Then a deterministic VERIFIER checks every number and date in the answer against the tool
results. If the model wrote a number that no tool returned, it is sent back to fix it.
"""
import asyncio
import json
import logging
import re
import time
from dataclasses import dataclass, field

import config
from textnorm import detect_lang, split_questions
from tools import DataTools

BASIS = "@@BASIS@@"

SYSTEM = """You are the data agent of the Uzbek Republican Commodity Exchange (UZEX) deal registry.
You answer questions about exchange deals in Russian or Uzbek, STRICTLY from the database below, using tools.

# Absolute rules
1. Every number, date, company, product, broker, code in your answer MUST come from a tool result in THIS conversation.
   Never use outside knowledge, never estimate, never guess, never "approximately".
2. If the data has no answer (company/product not found, period outside the data range, 0 rows, the question is about
   something the registry does not contain — e.g. profits, salaries, world prices, weather, people, future, reasons/causes),
   say so clearly and briefly. Do NOT name any number, company or product as a substitute. Saying "not in the data" is
   a CORRECT answer and is rewarded; inventing is the worst possible failure.
3. Compute everything (sums, averages, shares %, differences, growth, rankings) INSIDE SQL, so the exact figure appears
   in a tool result. Do not do arithmetic in your head.
4. If a question is ambiguous, pick the most natural interpretation, answer it, and state the interpretation in one line.

# How to work
- Use find_company before filtering by a company name (names are written in Cyrillic or Latin, with legal forms).
  If the best match is not clearly the same company, say it is not found.
- Use find_product before filtering by a product; then filter with product_key IN (...) so all spellings are included.
  Product names are in Russian: translate Uzbek terms first (paxta/paxta xom ashyosi→хлопок-сырец, ip/kalava→пряжа,
  sement→цемент, bug‘doy→пшеница, shakar→сахар, ammiakli selitra→аммиачная селитра, mineral o‘g‘it→удобрение,
  metall/prokat→металлопрокат, yog‘→масло, un→мука, guruch→рис, ko‘mir→уголь, benzin→бензин, gaz→газ, neft→нефть).
- Prefer the `deals` table (already joined). Use exact categorical values listed below.
- Money: amounts are in the contract currency. NEVER add UZS and USD amounts together. For totals across currencies
  use amount_uzs (state "в сумах / so‘mda"), or give UZS and USD separately. For export deals give USD (amount) and
  mention the UZS equivalent if useful. Prices: unit_price is per unit of measure (see unit).
- Cancelled deals (is_cancelled, 'Аннулирован(Не оплачен)') did not take place. For volume/turnover/amount questions
  by default EXCLUDE cancelled deals and say so in the basis; for "how many deals were concluded/registered" count all
  and, if relevant, also give the number without cancelled. If the user asks about a specific status, filter by it.
- "Region" in deals = region of the seller's warehouse. Buyer's region is participants.region via buyer_inn.
- Dates: quarter/month/year columns exist. "Last month/this year" = relative to the last date in the data.
- Keep SQL efficient: aggregate, LIMIT top-N, never select thousands of rows.
- If a query errors, fix it and retry. You have limited steps — usually 1–4 tool calls are enough.

# Language (STRICT — checked automatically)
- Every user message ends with a [LANGUAGE NOTE] that names the reply language of each question. Obey it.
- The whole reply — answer, lists, units, AND the @@BASIS@@ lines — is in that ONE language and script. No mixing.
- The database values (product names, categories, groups, industries, statuses, units, regions, deal types) are in
  Russian. When the reply language is Uzbek you MUST translate them into Uzbek. NEVER copy the Russian value and
  NEVER add the Russian original in parentheses. Wrong: "Qishloq xo‘jaligi mahsulotlari (Сельскохозяйственная продукция)".
  Right: "Qishloq xo‘jaligi mahsulotlari".
- Company names: keep the name itself, but in an Uzbek Latin reply transliterate a Cyrillic name into Latin
  ("ООО «Агро Савдо»" → «Agro Savdo» MCHJ, АО → AJ, ООО → MCHJ, ЧП → XK, СП → QK); in an Uzbek Cyrillic reply
  write it in Cyrillic. In a Russian reply keep company names exactly as in the data.
- Uzbek Latin uses o‘ g‘ (with ‘), sh, ch. Uzbek Cyrillic uses ў қ ғ ҳ. Do not answer Uzbek questions in Russian.
- Glossary Russian → Uzbek Latin (for Uzbek Cyrillic write the same words in Cyrillic: paxta → пахта, bug‘doy → буғдой):
  хлопок-сырец → paxta xom ashyosi; хлопковое волокно → paxta tolasi; пряжа → ip-kalava; хлопковое масло → paxta yog‘i;
  растительное масло → o‘simlik yog‘i; масло → yog‘; шрот → shrot; жмых → kunjara; семена → urug‘lik; пшеница → bug‘doy;
  ячмень → arpa; кукуруза → makkajo‘xori; рис → guruch; мука → un; сахар → shakar; соль → tuz; цемент → sement;
  кирпич → g‘isht; щебень → shag‘al; песок → qum; известь → ohak; стекло → shisha; древесина/лесоматериалы → yog‘och-taxta;
  металлопрокат → metall prokat; арматура → armatura; уголь → ko‘mir; бензин → benzin; дизельное топливо → dizel yoqilg‘isi;
  сжиженный газ → suyultirilgan gaz; природный газ → tabiiy gaz; нефть → neft; мазут → mazut; битум → bitum;
  аммиачная селитра → ammiakli selitra; карбамид → karbamid; минеральные удобрения → mineral o‘g‘itlar; удобрения → o‘g‘itlar;
  сера → oltingugurt; полиэтилен → polietilen; сорт → nav (1 сорт → 1-nav); класс → sinf; марка → marka;
  сельскохозяйственная продукция → qishloq xo‘jaligi mahsulotlari; продовольственные товары → oziq-ovqat tovarlari;
  нефтепродукты → neft mahsulotlari; металлопродукция → metall mahsulotlari; строительные материалы → qurilish materiallari;
  химическая продукция → kimyo mahsulotlari; текстиль → to‘qimachilik mahsulotlari; энергоресурсы → energiya resurslari;
  исполнен → bajarilgan; исполнен частично → qisman bajarilgan; аннулирован (не оплачен) → bekor qilingan (to‘lanmagan);
  спот → spot; форвард → forvard; фьючерс → fyuchers; экспорт → eksport; биржевой/внебиржевой → birja/birjadan tashqari;
  тонна → tonna; килограмм → kilogramm; литр → litr; штука → dona; кубический метр → kub metr; сум → so‘m;
  область → viloyati; город Ташкент → Toshkent shahri; Республика Каракалпакстан → Qoraqalpog‘iston Respublikasi;
  покупатель → xaridor; продавец → sotuvchi; брокер → broker; сделка → bitim; оборот → aylanma; объём → hajm.
  Anything not in the glossary: translate it into natural Uzbek yourself.

# Grammar and style (STRICT — the reader is an exchange official; write like an official analytical note)
- Write correct, natural, literary language — as a native-speaking analyst would write. No word-for-word calques
  from Russian or English, no machine-translation phrasing, no slang. Short, complete sentences.
- NEVER show technical identifiers in the text or the basis: no table/column names (deals, amount_uzs, deal_date,
  product_key, is_cancelled, year=2025), no "SQL", "jadval", "таблица deals", no tool names (find_company...).
  Describe the data in plain words: "birja bitimlari reyestri" / "реестр биржевых сделок".
- Product names: write them as a person would — capitalised, readable, from product_name / the main spelling
  ("Хлопок-сырец 1 сорт", "Пшеница продовольственная 4 класс"), NEVER the lowercase product_key
  ("хлопок сырец спот 1 сорт 1 класс"). In Uzbek translate them ("1-navli paxta xom ashyosi", "4-sinf oziq-ovqat bug‘doyi").
- Impersonal style: no "я перевёл", "men hisobladim". Write "переведено в тонны", "tonnaga o‘tkazildi".

## Uzbek (Latin) rules
- Spelling: o‘ g‘ always with ‘ (o‘rtacha, bo‘yicha, g‘alla, so‘m); the tutuq belgisi is ’ (ma’lumot, ta’minot, e’lon).
  Official spellings: reyestr, aksiyadorlik jamiyati, MCHJ, aylanma, xaridor, sotuvchi, birja, broker, toifa.
- Years and dates: "2025-yil", "2025-yilda", "2025-yilning sentyabr oyida", "2024-yilga nisbatan"; ordinals with a
  hyphen: "1-nav", "3-sinf", "1-o‘rin". Months in lowercase: yanvar, fevral, mart, aprel, may, iyun, iyul, avgust,
  sentyabr, oktyabr, noyabr, dekabr.
- After a number use "ta" for countable things and keep the noun SINGULAR: "115 763 ta bitim", "5 ta toifa",
  "319 ta sotuvchi" (NOT "5 ta toifalar", NOT "107 678 bitim"). With units no "ta": "539 514.44 tonna", "1 200 so‘m".
- Word order: subject – object – verb, verb at the end. Use the passive for registry facts: "tuzilgan", "sotilgan",
  "ro‘yxatga olingan", "bekor qilingan".
- Good phrases: "2025-yilda jami **115 763 ta** bitim tuzilgan." / "Eng katta aylanma — paxta xom ashyosida:
  **3 680 985 264 715.32 so‘m**." / "Bekor qilingan bitimlar hisobga olinmagan." / "Summalar so‘mda, bitim sanasidagi
  kurs bo‘yicha hisoblangan." / "So‘ralgan ma’lumot reyestrda mavjud emas." / "2024-yilga nisbatan **46.31%** ko‘p."
  "Eng ko‘p bitim tuzgan broker — ...". "O‘rtacha narx 1 tonna uchun **X so‘m**ni tashkil etgan."
- Avoid: "Top-5 reytinglari" (→ "eng yirik 5 ta ...", "aylanma bo‘yicha birinchi 5 ta ..."), "ro‘yxatdan o‘tkazilgan
  bitimlar soni tashkil qiladi" (→ "... ta bitim tuzilgan"), "ma'lumot yo'q" with straight apostrophes,
  "realizatsiya qilingan" (→ "sotilgan"), "summa miqdori" (→ "summa"), "kompaniyasi topilmadi, shuning uchun u haqida
  ma’lumot yo‘q" (→ "«Artel Electronics» nomli kompaniya bitimlar reyestrida topilmadi.").

## Uzbek (Cyrillic) rules
- Same grammar as Uzbek Latin, written with ў қ ғ ҳ: "2025-йилда жами **115 763 та** битим тузилган.",
  "ўртача нарх", "бўйича", "сўм", "реестр".

## Russian rules
- Correct agreement with numerals: 1 сделка, 2–4 сделки, 5+ сделок (115 763 сделки, 107 678 сделок,
  21 сделка); with fractions the genitive singular: 539 514.44 тонны, 12.5 тонны. "319 продавцов", "13 074 покупателя".
- "в 2024 году" (when), "за 2024 год" (for the period), "по сравнению с 2024 годом", "в сентябре 2026 года".
- Official neutral register: "заключено", "зарегистрировано", "продано", "аннулировано", "составил(а)".
- Good phrases: "В 2024 году продано **539 514.44 тонны** хлопка-сырца 1 сорта." / "Аннулированные сделки не учтены." /
  "Суммы указаны в сумах по курсу на дату сделки." / "Данных об этом в реестре нет." / "Это на **46.31%** больше,
  чем в 2024 году."
- Avoid: "Таблица deals", "посчитано в SQL", "я перевёл", "по данным таблицы", anglicisms ("топ-рейтинг" → "пятёрка
  крупнейших", "первые 5 по обороту").

# Several questions in one message
- If the message contains several separate, unrelated questions, answer EACH of them, numbered "1.", "2.", ... in the
  same order as asked. Each numbered answer is in the language of ITS OWN question (one may be Russian, another Uzbek).
  Start each with its key number in **bold**. Do the tool calls for all of them; do not skip any.
- After all answers write ONE @@BASIS@@ line, then the basis lines numbered the same way ("1. ...", "2. ...").
- If the parts are really one question (e.g. "how many deals and what was the turnover in 2024"), answer it as one.

# Answer format (the user sees this in Telegram)
- First line: the direct answer with the key number(s) in **bold**. Then at most 5 short lines or a short list (top-N).
- Numbers: thousands separated by spaces, decimal point, 2 decimals for money/prices (e.g. 1 018 102 922.76),
  always with unit/currency (so‘m/сум, USD, tonna/тонна, kg/кг). Write full numbers, not "mln/млрд". Dates as DD.MM.YYYY.
- Then a line containing exactly @@BASIS@@ and after it 1–3 short lines in the same language, in plain words (no
  table/column names): which data, filters, period and assumptions were used. Examples:
  ru: "Реестр биржевых сделок за 2024 год, без аннулированных сделок. Суммы в сумах по курсу на дату сделки."
  uz: "Birja bitimlari reyestri, 2024-yil; bekor qilingan bitimlar hisobga olinmagan. Summalar so‘mda, bitim
  sanasidagi kurs bo‘yicha."
- No greetings, no apologies, no advice, no speculation about causes.

# Database (DuckDB SQL)
{schema}
"""

TOOLS = [
    {"name": "sql",
     "description": "Run ONE read-only DuckDB SQL query (SELECT/WITH) on the exchange database and get the result table. "
                    "Use for every number in the answer.",
     "input_schema": {"type": "object", "properties": {
         "query": {"type": "string", "description": "DuckDB SELECT query"}}, "required": ["query"]}},
    {"name": "find_company",
     "description": "Fuzzy-search a company (participant) or broker by name (Cyrillic or Latin, any spelling), 9-digit INN, "
                    "or broker code like BK027. Returns INN, exact name, role, region, deal counts.",
     "input_schema": {"type": "object", "properties": {
         "name": {"type": "string"}}, "required": ["name"]}},
    {"name": "find_product",
     "description": "Fuzzy-search products (Russian name, attribute words, or ТН ВЭД code). Returns product_key values "
                    "with all registry spellings and deal counts.",
     "input_schema": {"type": "object", "properties": {
         "text": {"type": "string"}}, "required": ["text"]}},
]

UI = {
    "ru": {"timeout": "Не успел найти ответ за отведённое время. Пожалуйста, уточните или упростите вопрос.",
           "error": "Произошла ошибка при обработке вопроса. Попробуйте ещё раз."},
    "uz": {"timeout": "Ajratilgan vaqt ichida javob topa olmadim. Iltimos, savolni aniqroq yoki soddaroq bering.",
           "error": "Savolni qayta ishlashda xatolik yuz berdi. Iltimos, qaytadan urinib ko‘ring."},
    "uzc": {"timeout": "Ажратилган вақт ичида жавоб топа олмадим. Илтимос, саволни аниқроқ беринг.",
            "error": "Саволни қайта ишлашда хатолик юз берди. Илтимос, қайтадан уриниб кўринг."},
}


@dataclass
class AgentResult:
    answer: str
    basis: str = ""
    lang: str = "ru"
    queries: list = field(default_factory=list)       # successful SQL queries
    steps: int = 0
    elapsed: float = 0.0
    verified: bool = True
    unverified: list = field(default_factory=list)
    trace: list = field(default_factory=list)


# ---------------- grounding verifier ----------------
_NUM = re.compile(r"(?<![\w.])-?\d{1,3}(?:[   ]\d{3})+(?:[.,]\d+)?(?![\d])|(?<![\w.])-?\d+(?:[.,]\d+)?(?![\d])")
_DATE = re.compile(r"\b(\d{1,2})[./](\d{1,2})[./](\d{4})\b|\b(\d{4})-(\d{2})-(\d{2})\b")
_TIME = re.compile(r"\b\d{1,2}:\d{2}(?::\d{2})?\b")
_SCALE = re.compile(r"^\s*(трлн|trln|млрд|mlrd|млн|mln|million|тыс|ming)", re.I)
_SCALES = {"трлн": 1e12, "trln": 1e12, "млрд": 1e9, "mlrd": 1e9, "млн": 1e6, "mln": 1e6, "million": 1e6, "тыс": 1e3, "ming": 1e3}


def _numbers(text):
    text = _TIME.sub(" ", _DATE.sub(" ", text))
    text = re.sub(r"\bBK\d+\b", " ", text)
    out = []
    for m in _NUM.finditer(text):
        raw = m.group(0)
        v = float(re.sub(r"[   ]", "", raw).replace(",", "."))
        sm = _SCALE.match(text[m.end():m.end() + 10])
        if sm:
            v *= _SCALES[sm.group(1).lower()]
        out.append((raw, v))
    return out


def _dates(text):
    res = set()
    for m in _DATE.finditer(text):
        if m.group(1):
            res.add((int(m.group(3)), int(m.group(2)), int(m.group(1))))
        else:
            res.add((int(m.group(4)), int(m.group(5)), int(m.group(6))))
    return res


def verify(answer: str, evidence: str, question: str):
    """Return the list of numbers/dates in the answer that do not appear in tool results or the question."""
    ev_nums = [v for _, v in _numbers(evidence)] + [v for _, v in _numbers(question)]
    ev_dates = _dates(evidence) | _dates(question)
    bad = []
    for raw, v in _numbers(answer):
        if v.is_integer() and 0 <= v <= 31:
            continue                       # ordinals, top-N, days, months
        if v.is_integer() and 2000 <= v <= 2035:
            continue                       # years
        ok = any(abs(v - e) <= max(0.0051, abs(e) * 0.006) for e in ev_nums)
        if not ok:
            # percentages written as 12.5 when SQL returned 0.125
            ok = any(abs(v - e * 100) <= max(0.051, abs(e * 100) * 0.006) for e in ev_nums)
        if not ok:
            bad.append(raw.strip())
    for y, mth, d in _dates(answer):
        if (y, mth, d) not in ev_dates:
            bad.append(f"{d:02d}.{mth:02d}.{y}")
    return bad


# ---------------- LLM backends ----------------
class _Anthropic:
    def __init__(self):
        import anthropic
        self.client = anthropic.AsyncAnthropic(api_key=config.ANTHROPIC_API_KEY or None)

    def start(self, history, question):
        msgs = []
        for q, a in history:
            msgs += [{"role": "user", "content": q}, {"role": "assistant", "content": a}]
        msgs.append({"role": "user", "content": question})
        return msgs

    async def step(self, system, msgs, allow_tools=True):
        resp = await self.client.messages.create(
            model=config.LLM_MODEL, max_tokens=1500,
            # prompt caching: the long system prompt (schema) is billed at ~5% after the first request
            system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
            messages=msgs, tools=TOOLS,
            tool_choice={"type": "auto"} if allow_tools else {"type": "none"})
        msgs.append({"role": "assistant", "content": resp.content})
        calls = [(b.id, b.name, b.input) for b in resp.content if b.type == "tool_use"]
        text = "".join(b.text for b in resp.content if b.type == "text")
        return text, calls

    def add_results(self, msgs, results):
        msgs.append({"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": cid, "content": out} for cid, out in results]})

    def add_user(self, msgs, text):
        last = msgs[-1] if msgs else None
        if last and last["role"] == "user" and isinstance(last["content"], list):
            last["content"].append({"type": "text", "text": text})   # keep strict user/assistant alternation
        else:
            msgs.append({"role": "user", "content": text})


def strip_thoughts(text: str) -> str:
    """Some open models (Gemma, Qwen, DeepSeek) print their reasoning in <thought>/<think> tags — remove it."""
    t = re.sub(r"<(thought|think|thinking|reasoning)>.*?</\1>", "", text or "", flags=re.S | re.I)
    t = re.sub(r"^.*?</(thought|think|thinking|reasoning)>", "", t, flags=re.S | re.I)   # closing tag only
    t = re.sub(r"<(thought|think|thinking|reasoning)>.*$", "", t, flags=re.S | re.I)    # unclosed opening tag
    return t.strip()


def _err_text(e) -> str:
    """Full error text including the provider's JSON body (the default message often hides it)."""
    parts = [str(e)]
    body = getattr(e, "body", None)
    if body:
        parts.append(body[:1500] if isinstance(body, str) else json.dumps(body, ensure_ascii=False)[:1500])
    try:
        resp = getattr(e, "response", None)
        if resp is not None and resp.text and resp.text[:200] not in " ".join(parts):
            parts.append(resp.text[:1500])
    except Exception:
        pass
    return " | ".join(parts)


class _OpenAI:
    def __init__(self):
        from openai import AsyncOpenAI
        # max_retries: free tiers often answer 429 "too many requests"; the SDK waits and retries automatically
        self.client = AsyncOpenAI(api_key=config.OPENAI_API_KEY or None, base_url=config.OPENAI_BASE_URL,
                                  max_retries=2, timeout=40)
        self.tools = [{"type": "function", "function": {"name": t["name"], "description": t["description"],
                                                        "parameters": t["input_schema"]}} for t in TOOLS]
        # main model first, then fallbacks (LLM_FALLBACK_MODEL may be a comma-separated list)
        self.models = [config.LLM_MODEL] + [m.strip() for m in config.LLM_FALLBACK_MODEL.split(",") if m.strip()]
        self.blocked = {}   # model -> time until which it is skipped

    async def _create(self, model, **kw):
        if "gemini-3" in model:
            kw.pop("temperature", None)     # Google recommends the default temperature for Gemini 3 models
        return await self.client.chat.completions.create(model=model, **kw)

    async def _create_any(self, **kw):
        """Try models in order. 429 -> skip the model until its limit resets (short per-minute limits are waited out);
        404 -> model doesn't exist for this key; 400 on a fallback -> model can't do tool calling, skip it."""
        from openai import BadRequestError, NotFoundError, RateLimitError
        log = logging.getLogger("agent")
        last = None
        for _ in range(3):
            now = time.time()
            candidates = [m for m in self.models if self.blocked.get(m, 0) <= now]
            if not candidates:
                wait = min(self.blocked.get(m, 0) for m in self.models) - now
                if wait <= 25:                       # per-minute limit: just wait for it
                    log.warning("all models rate-limited, waiting %.0fs", wait)
                    await asyncio.sleep(max(wait, 1))
                    continue
                break
            for m in candidates:
                try:
                    return await self._create(m, **kw)
                except RateLimitError as e:
                    txt = _err_text(e)
                    flat = txt.lower().replace("_", "").replace(" ", "")
                    daily = "perday" in flat or "daily" in flat
                    d = re.search(r"retry\s*delay\W+(\d+(?:\.\d+)?)s", txt, re.I) or re.search(r"retry in (\d+(?:\.\d+)?)", txt, re.I)
                    delay = float(d.group(1)) if d else 60
                    self.blocked[m] = time.time() + (6 * 3600 if daily else delay + 1)
                    log.warning("model %s: %s limit reached (retry in %.0fs)", m, "DAILY" if daily else "per-minute",
                                6 * 3600 if daily else delay)
                    last = e
                except NotFoundError as e:
                    self.blocked[m] = time.time() + 10 ** 9
                    log.warning("model %s does not exist for this key — remove it from .env", m)
                    last = e
                except BadRequestError as e:
                    if m == self.models[0]:
                        raise RuntimeError(f"400 from main model {m}: {_err_text(e)}") from None
                    self.blocked[m] = time.time() + 10 ** 9
                    log.warning("model %s rejected the request (probably no tool calling) — remove it from .env. %s",
                                m, _err_text(e)[:300])
                    last = e
        raise RuntimeError(f"All models failed. Last error: {_err_text(last)}" if last else "All models are rate-limited")

    def start(self, history, question):
        msgs = []
        for q, a in history:
            msgs += [{"role": "user", "content": q}, {"role": "assistant", "content": a}]
        msgs.append({"role": "user", "content": question})
        return msgs

    async def step(self, system, msgs, allow_tools=True):
        kw = dict(messages=[{"role": "system", "content": system}] + msgs, tools=self.tools,
                  tool_choice="auto" if allow_tools else "none", temperature=0)
        resp = await self._create_any(**kw)
        m = resp.choices[0].message
        entry = {"role": "assistant", "content": m.content or (None if m.tool_calls else "")}
        if m.tool_calls:
            # model_dump keeps provider extras, e.g. Gemini 3 'extra_content.google.thought_signature',
            # which MUST be sent back with the next request or Gemini answers 400
            entry["tool_calls"] = [c.model_dump(exclude_none=True) for c in m.tool_calls]
        msgs.append(entry)
        calls = []
        for c in m.tool_calls or []:
            try:
                args = json.loads(c.function.arguments or "{}")
            except json.JSONDecodeError:
                args = {}
            calls.append((c.id, c.function.name, args))
        return m.content or "", calls

    def add_results(self, msgs, results):
        for cid, out in results:
            msgs.append({"role": "tool", "tool_call_id": cid, "content": out})

    def add_user(self, msgs, text):
        msgs.append({"role": "user", "content": text})



# ---------------- language control ----------------
LANG_NAME = {"ru": "Russian", "uz": "Uzbek (Latin script)", "uzc": "Uzbek (Cyrillic script)"}
_OK_LATIN = {"USD", "UZS", "SQL", "INN", "STIR", "ID", "HS", "EUR", "RUB"}


def language_note(segments, langs) -> str:
    if len(segments) <= 1 or len(set(langs)) == 1 and len(segments) == 1:
        lang = langs[0] if langs else "ru"
        return (f"[LANGUAGE NOTE — system, not from the user] Reply language: {LANG_NAME[lang]}. Write EVERY word in it, "
                "including product names, categories, statuses, units and the basis lines."
                + ("" if lang == "ru" else " Translate Russian database values; no Russian originals in parentheses."))
    lines = [f"[LANGUAGE NOTE — system, not from the user] This message seems to contain {len(segments)} questions:"]
    for i, (seg, lg) in enumerate(zip(segments, langs), 1):
        lines.append(f"{i}) «{seg[:150]}» → reply in {LANG_NAME[lg]}")
    lines.append("If they are separate questions, answer each one, numbered in this order, each in its own reply language. "
                 "If they are really one question, answer it once in "
                 f"{LANG_NAME[langs[0]]}. Translate Russian database values; no Russian originals in parentheses.")
    return "\n".join(lines)


_JARGON = re.compile(r"\b(deals|contracts|participants|amount_uzs|amount|deal_date|product_key|product_full|product_search|"
                     r"company_search|is_cancelled|is_executed|unit_price|year\s*=|find_company|find_product|SQL|"
                     r"jadval\w*|таблиц\w*|жадвал\w*)\b", re.I)


def jargon_issues(text: str) -> list:
    """Technical identifiers that must not appear in the user-facing text (the SQL is shown separately)."""
    return list(dict.fromkeys(m.group(0) for m in _JARGON.finditer(re.sub(r"`[^`]*`", lambda m: " " + m.group(0)[1:-1] + " ", text or ""))))


_RU_FORMS = [("сделка", "сделки", "сделок"), ("покупатель", "покупателя", "покупателей"),
             ("продавец", "продавца", "продавцов"), ("брокер", "брокера", "брокеров"), ("товар", "товара", "товаров"),
             ("компания", "компании", "компаний"), ("участник", "участника", "участников"),
             ("контракт", "контракта", "контрактов")]
_RU_FORM_OF = {f: forms for forms in _RU_FORMS for f in forms}
_RU_NUM_NOUN = re.compile(r"(?<![\w.,])((?:из|от|до|около|более|менее|свыше|для|у|с|со|на|в|во|по|при|о|об)\s+)?"
                          r"(\*\*)?(\d{1,3}(?:[ \u00a0\u202f]\d{3})*|\d+)(?![.,]\d)(\*\*)?(\s+)(" +
                          "|".join(sorted(_RU_FORM_OF, key=len, reverse=True)) + r")\b", re.I)


def _ru_agree(m):
    prep, b1, num, b2, sp, word = m.groups()
    if prep:                                    # 'из 21 сделки', 'в 5 сделках' — case set by the preposition
        return m.group(0)
    n = int(re.sub(r"\D", "", num))
    one, few, many = _RU_FORM_OF[word.lower()]
    form = many if 11 <= n % 100 <= 14 else one if n % 10 == 1 else few if 2 <= n % 10 <= 4 else many
    if word[0].isupper():
        form = form.capitalize()
    return f"{b1 or ''}{num}{b2 or ''}{sp}{form}"


def polish(text: str, langs) -> str:
    """Deterministic spelling fixes that the model often gets wrong."""
    t = text or ""
    if any(lg in ("uz", "uzc") for lg in langs):
        t = re.sub(r"(?<=[OoGg])['`ʻʼ’´]", "‘", t)                          # o' g' -> o‘ g‘
        t = re.sub(r"(?<=[A-Za-z])['`ʻʼ´](?=[A-Za-z])", "’", t)              # ma'lumot -> ma’lumot
        t = re.sub(r"\b((?:19|20)\d\d)\s+(yil|йил)", r"\1-\2", t)          # 2025 yil -> 2025-yil
        t = re.sub(r"\b((?:19|20)\d\d)\s*-\s*(yil|йил)", r"\1-\2", t)
        t = re.sub(r"\b(\d{1,2})\s+-?\s*(nav|sinf|o‘rin|нав|синф)\b", r"\1-\2", t)   # 1 nav -> 1-nav
        t = re.sub(r"\breestr", "reyestr", t)
        t = re.sub(r"\bReestr", "Reyestr", t)
    if "ru" in langs:
        t = _RU_NUM_NOUN.sub(_ru_agree, t)                                     # 2664 сделок -> 2664 сделки
    return t


def language_issues(text: str, lang: str) -> list:
    """Words written in the wrong script for the reply language."""
    body = re.sub(r"`[^`]*`", " ", text or "")
    body = re.sub(r"\bBK\d+\b", " ", body)
    words = re.findall(r"[A-Za-zА-Яа-яЁёЎўҚқҒғҲҳ][A-Za-zА-Яа-яЁёЎўҚқҒғҲҳ‘’ʻʼ'\-]*", body)
    if lang == "uz":
        return [w for w in words if re.search(r"[А-Яа-яЁёЎўҚқҒғҲҳ]", w)]
    if lang == "uzc":
        bad = [w for w in words if re.fullmatch(r"[A-Za-z‘’ʻʼ'\-]+", w) and len(w) > 2 and w.upper() not in _OK_LATIN]
        return bad if len(bad) >= 3 else []        # a few Latin company names are acceptable
    return []                                       # Russian replies may keep Latin/Uzbek company names as in the data

# ---------------- the agent ----------------
class Agent:
    def __init__(self, db_path=None):
        if db_path is None and not config.DB_PATH.exists():
            import loader
            loader.build()                      # first run: build the database from CSVs
        self.tools = DataTools(db_path)
        self.system = SYSTEM.replace("{schema}", self.tools.schema_doc())
        self.llm = _Anthropic() if config.LLM_PROVIDER == "anthropic" else _OpenAI()

    async def _run_tool(self, name, args):
        if name == "sql":
            return await asyncio.to_thread(self.tools.run_sql, args.get("query", ""))
        if name == "find_company":
            return await asyncio.to_thread(self.tools.find_company, args.get("name", ""))
        if name == "find_product":
            return await asyncio.to_thread(self.tools.find_product, args.get("text", ""))
        return f"ERROR: unknown tool {name}"

    async def answer(self, question: str, history=None) -> AgentResult:
        t0 = time.time()
        segments = split_questions(question)
        langs = [detect_lang(sg) for sg in segments] or [detect_lang(question)]
        lang = langs[0] if len(set(langs)) == 1 else detect_lang(question)
        res = AgentResult(answer="", lang=lang)
        msgs = self.llm.start(history or [], question + "\n\n" + language_note(segments, langs))
        max_steps = min(config.MAX_STEPS + 4 * (len(segments) - 1), 24)   # more tool calls for multi-question messages
        evidence = []
        text = ""
        retried = False
        lang_retried = False
        force_final = False
        steps = 0
        while True:
            over_time = time.time() - t0 > config.TIME_BUDGET
            allow = steps < max_steps and not over_time and not force_final
            if not allow and not force_final:
                self.llm.add_user(msgs, "Tool budget is used up. Give the final answer now using ONLY the tool results "
                                        "above; if they are not enough, say the data does not allow a reliable answer.")
            text, calls = await self.llm.step(self.system, msgs, allow_tools=allow)
            if calls and allow:
                results = []
                for cid, name, args in calls:
                    steps += 1
                    out = await self._run_tool(name, args)
                    evidence.append(out)
                    res.trace.append({"tool": name, "args": args, "result": out[:3000]})
                    if name == "sql" and not out.startswith("ERROR"):
                        res.queries.append(args.get("query", ""))
                    results.append((cid, out))
                self.llm.add_results(msgs, results)
                continue
            # final answer -> verify numbers against evidence
            text = strip_thoughts(text)
            bad = verify(text.split(BASIS)[0], "\n".join(evidence), question)
            if bad and not retried and time.time() - t0 < config.TIME_BUDGET + 10:
                retried = True
                self.llm.add_user(msgs, "VERIFIER: these numbers/dates in your answer do not appear in any tool result: "
                                        f"{', '.join(bad[:10])}. Every figure must come from a tool result. Compute them "
                                        "with SQL, or remove them. Then write the corrected final answer in the required format.")
                continue
            # language check (only when the whole message is in one language)
            wrong = language_issues(text, langs[0]) if len(set(langs)) == 1 else []
            wrong = wrong if len(wrong) >= 2 else []
            jargon = jargon_issues(text)
            if (wrong or jargon) and not lang_retried and time.time() - t0 < config.HARD_TIMEOUT - 25:
                lang_retried = True
                force_final = True
                problems = []
                if wrong:
                    target = LANG_NAME[langs[0]]
                    problems.append(f"the reply must be entirely in {target}, but it contains words in the wrong "
                                    f"script/language: {', '.join(list(dict.fromkeys(wrong))[:15])} — translate product "
                                    "names, categories, statuses and units (see the glossary), transliterate company "
                                    "names, remove Russian originals in parentheses")
                if jargon:
                    problems.append(f"it contains technical identifiers the user must not see: {', '.join(jargon[:10])} — "
                                    "describe the data in plain words (e.g. 'birja bitimlari reyestri' / 'реестр "
                                    "биржевых сделок')")
                self.llm.add_user(msgs, "STYLE CHECK: " + "; ".join(problems) + ". Rewrite the SAME answer (same numbers, "
                                        "same structure, same @@BASIS@@ part) in correct, natural, literary language "
                                        "following the grammar and style rules. Do not call tools.")
                continue
            res.unverified = bad
            res.verified = not bad
            break
        text = polish(text, langs)
        main, _, basis = text.partition(BASIS)
        res.answer = main.strip() or UI.get(lang, UI["ru"])["error"]
        res.basis = basis.strip()
        res.steps = steps
        res.elapsed = time.time() - t0
        return res