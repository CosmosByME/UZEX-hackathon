"""The tools the agent can call. All answers come from these — never from the model's memory."""
import datetime as _dt
import re
import threading

import duckdb
from rapidfuzz import fuzz, process

import config
from textnorm import norm_company, norm_product, product_query_ru

FORBIDDEN = re.compile(
    r"\b(insert|update|delete|drop|create|alter|attach|detach|copy|export|import|install|load|pragma|"
    r"set|reset|call|checkpoint|vacuum|read_csv\w*|read_parquet|read_json\w*|read_text|read_blob|glob|httpfs)\b",
    re.I,
)

# ---------- schema description given to the model ----------
COLUMNS_DOC = """
TABLE deals — one row per exchange deal (сделка / bitim). The main table; already joined with contract card, names, USD rate.
  deal_id BIGINT            — Номер сделки
  deal_date DATE, deal_time VARCHAR 'HH:MM:SS', deal_ts TIMESTAMP, year, quarter, month INT
  trade_type                — Тип торгов: values below
  contract_type             — Тип контракта: 'Внутренний' (domestic) | 'Экспортный' (export)
  contract_form             — Форма контракта: 'Спот' | 'Форвард' | 'Фьючерс'
  status                    — Состояние сделки: values below
  is_cancelled BOOL         — status = 'Аннулирован(Не оплачен)' (deal did NOT happen)
  is_executed BOOL          — status in ('Исполнен','Исполнен(Частично)')
  contract_id BIGINT        — Номер контракта
  product_full              — Наименование товара exactly as in the registry (name + attributes in one string)
  product_key               — normalised product name: spelling variants of the same product share one key
  product_name              — Наименование продукта from contract card (base name without attributes)
  brand, size, grade, ptype, pclass — Марка, Размер, Сорт, Тип, Класс (often NULL: then they are inside product_full)
  hs_code VARCHAR           — Код ТН ВЭД
  product_group, category, industry — Группа товара, Категория товара, Отрасль промышленности
  unit                      — Единица измерения (e.g. 'килограмм', 'тонна')
  lot_size DOUBLE           — units of measure in one lot
  qty_lots DOUBLE           — Количество (number of lots bought)
  volume DOUBLE             — qty_lots * lot_size, in `unit` (USE THIS for "how many tonnes/kg sold")
  currency                  — 'UZS' or 'USD' (contract currency; export deals are usually USD)
  amount DOUBLE             — Сумма сделки in `currency`
  start_price DOUBLE        — Стартовая цена per ONE unit of measure, in `currency`
  unit_price DOUBLE         — amount / volume, in `currency`
  usd_rate DOUBLE           — UZS per 1 USD on deal_date
  amount_uzs DOUBLE         — amount converted to UZS (= amount if UZS; amount*usd_rate if USD)
  amount_usd DOUBLE         — amount converted to USD
  region, region_ru         — region of the seller's warehouse (Uzbek Latin / Russian). Values below
  seller_inn, seller_name   — ИНН / name of seller
  buyer_inn, buyer_name     — ИНН / name of buyer
  seller_broker, seller_broker_name, buyer_broker, buyer_broker_name — broker code (e.g. 'BK027') and name
  pay_date DATE, delivery_date DATE — NULL if not yet paid / delivered
  delivered_lots, delivered_volume  — Поставлено (lots / units actually delivered)
  days_to_pay INT (pay_date - deal_date), days_to_deliver INT (delivery_date - pay_date)
  pay_term_days, delivery_term_days — Срок оплаты (days from deal date), Срок поставки (days from payment date)
  base_price, delivery_basis        — from the contract card

TABLE contracts — contract cards (карточки контрактов): contract_id, product_name, brand, size, grade, ptype, pclass,
  hs_code, product_group, category, industry, unit, lot_size, currency ('UZS'|'USD'), base_price (per unit, at registration),
  deposit_pct (Сумма залога, % of deal amount), delivery_basis, region, region_ru, warehouse_address, trade_type,
  contract_type, contract_form, pay_term_days, delivery_term_days, packaging, seller_inn, reg_date DATE, valid_until DATE
TABLE participants — companies: inn, name, region, region_ru, activity (Вид деятельности), role ('Продавец'|'Покупатель'), vat_payer ('Да'|'Нет')
TABLE brokers — broker_code, name, inn, region, region_ru
TABLE usd_rates — date DATE, rate DOUBLE (UZS per 1 USD, every calendar day)
TABLE product_search — product_key, product_name, product_group, category, hs_code, unit, variants (list of spellings), n_deals, first_deal, last_deal
"""


class DataTools:
    def __init__(self, db_path=None):
        self.con = duckdb.connect(str(db_path or config.DB_PATH), read_only=True,
                                  config={"enable_external_access": "false"})
        cur = self.con.cursor()
        self.companies = cur.execute(
            "SELECT inn, name, role, region, deals_as_seller, deals_as_buyer, name_norm FROM company_search").fetchall()
        self.brokers = cur.execute("SELECT broker_code, name, inn, region, name_norm FROM broker_search").fetchall()
        self.products = cur.execute(
            "SELECT product_key, product_name, product_group, category, hs_code, unit, variants, n_deals FROM product_search").fetchall()
        self._comp_names = [c[6] for c in self.companies]
        self._br_names = [b[4] for b in self.brokers]
        self._prod_keys = [p[0] for p in self.products]

    # ---------- schema / facts for the system prompt ----------
    def schema_doc(self) -> str:
        cur = self.con.cursor()
        def vals(col, table="deals"):
            return ", ".join(f"'{r[0]}'" for r in cur.execute(
                f"SELECT {col}, count(*) FROM {table} WHERE {col} IS NOT NULL GROUP BY 1 ORDER BY 2 DESC").fetchall())
        mn, mx, n = cur.execute("SELECT min(deal_date), max(deal_date), count(*) FROM deals").fetchone()
        per_year = ", ".join(f"{y}: {c}" for y, c in cur.execute("SELECT year, count(*) FROM deals GROUP BY 1 ORDER BY 1").fetchall())
        rmin, rmax = cur.execute("SELECT min(date), max(date) FROM usd_rates").fetchone()
        counts = {t: cur.execute(f"SELECT count(*) FROM {t}").fetchone()[0] for t in ("contracts", "participants", "brokers")}
        return COLUMNS_DOC + f"""
FACTS ABOUT THE DATA
  deals: {n} rows, deal_date from {mn} to {mx} (states as of end of {mx}). Per year: {per_year}
  contracts: {counts['contracts']}, participants: {counts['participants']}, brokers: {counts['brokers']}; usd_rates: {rmin} .. {rmax}
  status values: {vals('status')}
  trade_type values: {vals('trade_type')}
  contract_form values: {vals('contract_form')}; contract_type values: {vals('contract_type')}
  currency values: {vals('currency')}; unit values: {vals('unit')}
  region values (Uzbek / use these in filters): {vals('region')}
  region_ru values: {vals('region_ru')}
  product_group values: {vals('product_group')}
  category values: {vals('category')}
  industry values: {vals('industry')}
  participant activity values: {vals('activity', 'participants')}
"""

    # ---------- tool: sql ----------
    def run_sql(self, query: str, max_rows: int = None) -> str:
        max_rows = max_rows or config.MAX_ROWS
        q = (query or "").strip().rstrip(";").strip()
        q_nocomments = re.sub(r"--[^\n]*|/\*.*?\*/", " ", q, flags=re.S).strip()
        if not re.match(r"^(select|with)\b", q_nocomments, re.I):
            return "ERROR: only a single SELECT/WITH query is allowed."
        if ";" in q_nocomments:
            return "ERROR: only one statement is allowed."
        # check forbidden words outside string literals
        if FORBIDDEN.search(re.sub(r"'(?:[^']|'')*'", "''", q_nocomments)):
            return "ERROR: query contains a forbidden keyword. Only read-only SELECT is allowed."
        cur = self.con.cursor()
        timer = threading.Timer(config.SQL_TIMEOUT, cur.interrupt)
        timer.start()
        try:
            cur.execute(q)
            cols = [d[0] for d in cur.description]
            rows = cur.fetchmany(max_rows + 1)
        except Exception as e:
            msg = str(e).split("\n")[0][:400]
            if "INTERRUPT" in msg.upper():
                msg = f"query took longer than {config.SQL_TIMEOUT}s — simplify it"
            return f"ERROR: {msg}"
        finally:
            timer.cancel()
        more = len(rows) > max_rows
        rows = rows[:max_rows]
        if not rows:
            return f"columns: {', '.join(cols)}\n(0 rows — no data matches this query)"
        lines = [" | ".join(cols)]
        lines += [" | ".join(_fmt(v) for v in r) for r in rows]
        tail = f"\n(showing first {max_rows} rows; there are more — use aggregation or LIMIT)" if more else f"\n({len(rows)} row{'s' if len(rows) != 1 else ''})"
        return "\n".join(lines) + tail

    # ---------- tool: find_company ----------
    def find_company(self, name: str, limit: int = 8) -> str:
        name = (name or "").strip()
        out = []
        digits = re.sub(r"\D", "", name)
        if len(digits) == 9:
            out = [c for c in self.companies if c[0] == digits]
            br = [b for b in self.brokers if b[2] == digits]
            if out or br:
                return _companies_text(out) + _brokers_text(br)
            return f"No participant or broker with INN {digits} in the data."
        if re.fullmatch(r"(?i)bk\d{1,3}", name.replace(" ", "")):
            code = "BK" + re.sub(r"\D", "", name).zfill(3)
            br = [b for b in self.brokers if b[0] == code]
            return _brokers_text(br) if br else f"No broker with code {code} in the data."
        q = norm_company(name)
        if not q:
            return "Empty name."
        hits = process.extract(q, self._comp_names, scorer=fuzz.WRatio, limit=limit, score_cutoff=70)
        out = [self.companies[i] + (round(s),) for _, s, i in hits]
        bh = process.extract(q, self._br_names, scorer=fuzz.WRatio, limit=4, score_cutoff=75)
        br = [self.brokers[i] for _, s, i in bh]
        if not out and not br:
            return (f"NO company or broker resembling '{name}' exists in the data. "
                    "Tell the user this company is not found in the registry.")
        note = ("Scores <90 are only similar names — confirm by meaning before using; if none clearly matches, "
                "say the company is not found.\n")
        return note + _companies_text(out, with_score=True) + _brokers_text(br)

    # ---------- tool: find_product ----------
    def find_product(self, text: str, limit: int = 40) -> str:
        t = (text or "").strip()
        if re.fullmatch(r"\d{4,10}", t):
            hits = [p for p in self.products if (p[4] or "").startswith(t)]
            if not hits:
                return f"No product with ТН ВЭД code starting {t}."
            return _products_text(hits[:limit])
        # the registry is in Russian: also search with the Uzbek/English words translated (paxta -> хлопок, sement -> цемент)
        queries = [norm_product(t)]
        ru = product_query_ru(t)
        if ru and norm_product(ru) not in queries:
            queries.append(norm_product(ru))
        scored = []
        for i, p in enumerate(self.products):
            key = p[0] or ""
            hay = " ".join([key, (p[1] or "").lower(), (p[2] or "").lower(), (p[3] or "").lower()])
            htok = re.split(r"[\s\-]+", hay)
            best = 0
            for q in queries:
                qtok = [w for w in re.split(r"[\s\-]+", q) if w]
                # share of query words found in the product (prefix match, so 'хлоп' finds 'хлопок-сырец')
                hit = sum(1 for w in qtok if any(h == w or (len(w) >= 3 and h.startswith(w[:max(3, len(w) - 2)])) for h in htok))
                cover = hit / len(qtok) if qtok else 0
                s = max(fuzz.token_set_ratio(q, key), 70 + 25 * cover if cover >= 0.5 else 0)
                if q and q in hay:
                    s = max(s, 95)
                best = max(best, s)
            if best >= 72:
                scored.append((best, p[7], i))
        scored.sort(key=lambda x: (-x[0], -x[1]))
        hits = [self.products[i] for _, _, i in scored[:limit]]
        note = f"(searched also as Russian: '{ru}')\n" if ru else ""
        if not hits:
            return (f"NO product resembling '{text}' in the data (product names are in Russian — if you searched in Uzbek, "
                    "retry with the Russian name). If still nothing, tell the user the product is not traded in the data.")
        more = len(scored) - len(hits)
        tail = (f"\n({more} more products also match — search with more specific words, or query product_search with SQL)"
                if more > 0 else "")
        return note + _products_text(hits) + tail


def _fmt(v):
    if v is None:
        return "NULL"
    if isinstance(v, float):
        if v != v:
            return "NaN"
        return str(int(v)) if v.is_integer() and abs(v) < 1e15 else f"{v:.4f}".rstrip("0").rstrip(".")
    if isinstance(v, (_dt.date, _dt.datetime)):
        return v.isoformat()
    if isinstance(v, list):
        return "[" + "; ".join(_fmt(x) for x in v[:10]) + (" …" if len(v) > 10 else "") + "]"
    return str(v)


def _companies_text(rows, with_score=False):
    if not rows:
        return ""
    lines = ["COMPANIES: inn | name | role | region | deals_as_seller | deals_as_buyer" + (" | match_score" if with_score else "")]
    for r in rows:
        lines.append(" | ".join(_fmt(x) for x in (r[:6] + ((r[7],) if with_score else ()))))
    return "\n".join(lines) + "\n"


def _brokers_text(rows):
    if not rows:
        return ""
    return "\n".join(["BROKERS: broker_code | name | inn | region"] + [" | ".join(_fmt(x) for x in r[:4]) for r in rows]) + "\n"


def _products_text(rows):
    lines = ["PRODUCTS: product_key | product_name | category | hs_code | unit | n_deals | spellings (count: example)",
             "Filter deals with  product_key IN (...)  listing EVERY key that matches the question "
             "(all forms спот/форвард/фьючерс and all classes, unless the question narrows them). "
             "For a whole product family you may instead use  product_key LIKE 'хлопок сырец%'  (keys are lowercase, "
             "no hyphens, grades written as '1 сорт', '2 класс')."]
    for p in rows:
        variants = p[6] or []
        ex = variants[0] if variants else ""
        lines.append(" | ".join(_fmt(x) for x in (p[0], p[1], p[3], p[4], p[5], p[7])) + f" | {len(variants)}: {ex}")
    return "\n".join(lines)