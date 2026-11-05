"""Build a clean DuckDB database from the exchange CSV files.

    python loader.py            # reads DATA_DIR, writes DB_PATH

Cleaning done here (so the LLM never has to):
  * numbers like "78 356 027.52" -> DOUBLE, dates "03.01.2026" -> DATE, "10 %" -> 10
  * English snake_case column names
  * contract currency, product attributes and classification joined onto every deal
  * USD rate of the deal date joined; amount_uzs computed for every deal
  * volume = qty_lots * lot_size, unit_price = amount / volume
  * seller/buyer/broker names joined; regions normalised to one spelling (Uzbek + Russian)
  * product_key: one key for spelling variants of the same product ("1 сорт" / "1-сорта")
"""
import csv
import glob
import os
import sys
import time

import duckdb
import pandas as pd

import config
from textnorm import canon_region, compact_key, norm_company, norm_product

DEALS = {
    "номерсделки": "deal_id", "датасделки": "deal_date_raw", "времясделки": "deal_time", "типторгов": "trade_type",
    "количество": "qty_raw", "суммасделки": "amount_raw", "стартоваяцена": "start_price_raw",
    "номерконтракта": "contract_id_raw", "наименованиетовара": "product_full", "лот": "lot_raw",
    "единицаизмерения": "unit", "регион": "region_raw", "типконтракта": "contract_type",
    "формаконтракта": "contract_form", "состояниесделки": "status", "иннпродавца": "seller_inn",
    "иннпокупателя": "buyer_inn", "брокерпродавца": "seller_broker", "брокерпокупателя": "buyer_broker",
    "датаоплаты": "pay_date_raw", "датапоставки": "delivery_date_raw", "поставлено": "delivered_raw",
}
CONTRACTS = {
    "номерконтракта": "contract_id_raw", "наименованиепродукта": "product_name", "маркатовара": "brand",
    "размертовара": "size", "сорттовара": "grade", "типтовара": "ptype", "класстовара": "pclass",
    "кодтнвэд": "hs_code", "группатовара": "product_group", "категориятовара": "category",
    "отрасльпромышленности": "industry", "единицаизмерения": "unit", "лот": "lot_raw", "валюта": "currency_raw",
    "базиснаяцена": "base_price_raw", "суммазалога": "deposit_raw", "базиспоставки": "delivery_basis",
    "регион": "region_raw", "адресклада": "warehouse_address", "адрессклада": "warehouse_address",
    "типторгов": "trade_type", "типконтракта": "contract_type", "формаконтракта": "contract_form",
    "срокоплаты": "pay_term_raw", "срокпоставки": "delivery_term_raw", "упаковка": "packaging",
    "иннпродавца": "seller_inn", "датарегистрации": "reg_date_raw", "действуетдо": "valid_until_raw",
}
PARTICIPANTS = {"инн": "inn", "наименование": "name", "регион": "region_raw", "виддеятельности": "activity",
                "роль": "role", "плательщикндс": "vat_payer"}
BROKERS = {"кодброкера": "broker_code", "наименование": "name", "инн": "inn", "регион": "region_raw"}
RATES = {"дата": "date_raw", "курс": "rate_raw"}


def _key(h: str) -> str:
    return "".join(h.lower().replace("ё", "е").split()).strip("﻿\"")


def _find(pattern_list):
    files = []
    for p in pattern_list:
        files += glob.glob(str(config.DATA_DIR / p))
    # case-insensitive fallback
    if not files:
        names = os.listdir(config.DATA_DIR) if config.DATA_DIR.exists() else []
        for p in pattern_list:
            stem = p.replace("*", "").lower()
            files += [str(config.DATA_DIR / n) for n in names if n.lower().startswith(stem.split(".")[0]) and n.lower().endswith(".csv")]
    return sorted(set(files))


def _select_list(path, mapping):
    with open(path, encoding="utf-8-sig", newline="") as f:
        header = next(csv.reader(f))
    cols, seen = [], set()
    for h in header:
        k = _key(h)
        if k in mapping and mapping[k] not in seen:
            seen.add(mapping[k])
            cols.append(f'"{h}" AS {mapping[k]}')
    missing = set(mapping.values()) - seen
    return ", ".join(cols), missing


def _read(con, name, files, mapping):
    sel, missing = _select_list(files[0], mapping)
    flist = "[" + ", ".join("'" + f.replace("'", "''") + "'" for f in files) + "]"
    con.execute(f"""CREATE OR REPLACE TABLE {name} AS SELECT {sel}
        FROM read_csv({flist}, all_varchar=true, header=true, delim=',', quote='"', escape='"',
                      union_by_name=true, encoding='utf-8')""")
    for m in missing:  # keep schema stable even if a column is absent
        con.execute(f"ALTER TABLE {name} ADD COLUMN {m} VARCHAR")
    n = con.execute(f"SELECT count(*) FROM {name}").fetchone()[0]
    print(f"  {name}: {n:,} rows from {len(files)} file(s)" + (f"  (missing columns: {sorted(missing)})" if missing else ""))


MACROS = r"""
CREATE OR REPLACE MACRO num(x) AS TRY_CAST(replace(regexp_replace(coalesce(x,''), '[\s\x{00A0}\x{202F}%]', '', 'g'), ',', '.') AS DOUBLE);
CREATE OR REPLACE MACRO dt(x)  AS TRY_STRPTIME(trim(x), '%d.%m.%Y')::DATE;
CREATE OR REPLACE MACRO txt(x) AS nullif(trim(x), '');
"""


def build(db_path=None):
    t0 = time.time()
    db_path = str(db_path or config.DB_PATH)
    tmp = db_path + ".tmp"
    if os.path.exists(tmp):
        os.remove(tmp)
    con = duckdb.connect(tmp)
    con.execute(MACROS)

    print("Reading CSV files from", config.DATA_DIR)
    deal_files = _find(["deals_*.csv", "deals*.csv"])
    if not deal_files:
        sys.exit(f"No deals_*.csv found in {config.DATA_DIR}")
    _read(con, "raw_deals", deal_files, DEALS)
    _read(con, "raw_contracts", _find(["contracts.csv", "contract*.csv"]), CONTRACTS)
    _read(con, "raw_participants", _find(["participants.csv", "participant*.csv"]), PARTICIPANTS)
    _read(con, "raw_brokers", _find(["brokers.csv", "broker*.csv"]), BROKERS)
    _read(con, "raw_rates", _find(["usd_rates.csv", "usd*.csv", "rate*.csv"]), RATES)

    # ---------- regions: one spelling everywhere ----------
    raw_regions = set()
    for t in ("raw_deals", "raw_contracts", "raw_participants", "raw_brokers"):
        raw_regions |= {r[0] for r in con.execute(f"SELECT DISTINCT region_raw FROM {t} WHERE region_raw IS NOT NULL").fetchall()}
    reg = pd.DataFrame([(r, *canon_region(r)) for r in raw_regions], columns=["region_raw", "region", "region_ru"])
    con.register("reg_df", reg)
    con.execute("CREATE TABLE region_map AS SELECT * FROM reg_df")

    # ---------- dictionaries ----------
    con.execute("""
    CREATE TABLE usd_rates AS
    SELECT dt(date_raw) AS date, num(rate_raw) AS rate FROM raw_rates WHERE dt(date_raw) IS NOT NULL;

    CREATE TABLE participants AS
    SELECT txt(p.inn) AS inn, txt(p.name) AS name, coalesce(m.region, p.region_raw) AS region, m.region_ru,
           txt(p.activity) AS activity, txt(p.role) AS role, txt(p.vat_payer) AS vat_payer
    FROM raw_participants p LEFT JOIN region_map m USING (region_raw);

    CREATE TABLE brokers AS
    SELECT txt(b.broker_code) AS broker_code, txt(b.name) AS name, txt(b.inn) AS inn,
           coalesce(m.region, b.region_raw) AS region, m.region_ru
    FROM raw_brokers b LEFT JOIN region_map m USING (region_raw);

    CREATE TABLE contracts AS
    SELECT TRY_CAST(num(c.contract_id_raw) AS BIGINT) AS contract_id,
           txt(c.product_name) AS product_name, txt(c.brand) AS brand, txt(c.size) AS size, txt(c.grade) AS grade,
           txt(c.ptype) AS ptype, txt(c.pclass) AS pclass, txt(c.hs_code) AS hs_code,
           txt(c.product_group) AS product_group, txt(c.category) AS category, txt(c.industry) AS industry,
           txt(c.unit) AS unit, num(c.lot_raw) AS lot_size,
           CASE WHEN c.currency_raw ILIKE '%доллар%' OR c.currency_raw ILIKE '%usd%' THEN 'USD'
                WHEN c.currency_raw ILIKE '%сум%' OR c.currency_raw ILIKE '%uzs%' OR c.currency_raw ILIKE '%so%m%' THEN 'UZS'
                ELSE txt(c.currency_raw) END AS currency,
           num(c.base_price_raw) AS base_price, num(c.deposit_raw) AS deposit_pct,
           txt(c.delivery_basis) AS delivery_basis, coalesce(m.region, c.region_raw) AS region, m.region_ru,
           txt(c.warehouse_address) AS warehouse_address, txt(c.trade_type) AS trade_type,
           txt(c.contract_type) AS contract_type, txt(c.contract_form) AS contract_form,
           TRY_CAST(num(c.pay_term_raw) AS INTEGER) AS pay_term_days,
           TRY_CAST(num(c.delivery_term_raw) AS INTEGER) AS delivery_term_days,
           txt(c.packaging) AS packaging, txt(c.seller_inn) AS seller_inn,
           dt(c.reg_date_raw) AS reg_date, dt(c.valid_until_raw) AS valid_until
    FROM raw_contracts c LEFT JOIN region_map m USING (region_raw);
    """)

    # ---------- product keys (spelling variants -> one key) ----------
    pk = con.execute("""SELECT product_full, count(*) AS n FROM raw_deals WHERE product_full IS NOT NULL GROUP BY 1""").df()
    pk["norm"] = pk["product_full"].map(norm_product)
    pk["compact"] = pk["norm"].map(compact_key)        # glued typos ('хлопоксырец') join the normal spelling
    # readable key for each group = the normalised spelling with the most deals
    best = pk.groupby(["compact", "norm"])["n"].sum().reset_index().sort_values("n", ascending=False)
    best = best.drop_duplicates("compact").set_index("compact")["norm"]
    pk["product_key"] = pk["compact"].map(best)
    pk = pk[["product_full", "product_key"]]
    con.register("pk_df", pk)
    con.execute("CREATE TABLE product_keys AS SELECT * FROM pk_df")

    # ---------- deals: one wide, clean table ----------
    con.execute("""
    CREATE TABLE deals AS
    WITH d AS (
      SELECT TRY_CAST(num(deal_id) AS BIGINT) AS deal_id, dt(deal_date_raw) AS deal_date, txt(deal_time) AS deal_time,
             txt(trade_type) AS trade_type, num(qty_raw) AS qty_lots, num(amount_raw) AS amount,
             num(start_price_raw) AS start_price, TRY_CAST(num(contract_id_raw) AS BIGINT) AS contract_id,
             txt(product_full) AS product_full, num(lot_raw) AS lot_size, txt(unit) AS unit, region_raw,
             txt(contract_type) AS contract_type, txt(contract_form) AS contract_form, txt(status) AS status,
             txt(seller_inn) AS seller_inn, txt(buyer_inn) AS buyer_inn,
             txt(seller_broker) AS seller_broker, txt(buyer_broker) AS buyer_broker,
             dt(pay_date_raw) AS pay_date, dt(delivery_date_raw) AS delivery_date, num(delivered_raw) AS delivered_lots
      FROM raw_deals)
    SELECT d.deal_id, d.deal_date, d.deal_time,
           TRY_CAST(strftime(d.deal_date, '%Y-%m-%d') || ' ' || d.deal_time AS TIMESTAMP) AS deal_ts,
           year(d.deal_date) AS year, quarter(d.deal_date) AS quarter, month(d.deal_date) AS month,
           d.trade_type, d.contract_type, d.contract_form, d.status,
           d.status = 'Аннулирован(Не оплачен)' AS is_cancelled,
           d.status IN ('Исполнен', 'Исполнен(Частично)') AS is_executed,
           d.contract_id, d.product_full, pk.product_key,
           c.product_name, c.brand, c.size, c.grade, c.ptype, c.pclass, c.hs_code,
           c.product_group, c.category, c.industry,
           d.unit, d.lot_size, d.qty_lots, d.qty_lots * d.lot_size AS volume,
           coalesce(c.currency, 'UZS') AS currency, d.amount, d.start_price,
           d.amount / nullif(d.qty_lots * d.lot_size, 0) AS unit_price,
           r.rate AS usd_rate,
           CASE WHEN coalesce(c.currency, 'UZS') = 'USD' THEN d.amount * r.rate ELSE d.amount END AS amount_uzs,
           CASE WHEN coalesce(c.currency, 'UZS') = 'USD' THEN d.amount ELSE d.amount / r.rate END AS amount_usd,
           coalesce(m.region, d.region_raw) AS region, m.region_ru,
           d.seller_inn, ps.name AS seller_name, d.buyer_inn, pb.name AS buyer_name,
           d.seller_broker, bs.name AS seller_broker_name, d.buyer_broker, bb.name AS buyer_broker_name,
           d.pay_date, d.delivery_date, d.delivered_lots, d.delivered_lots * d.lot_size AS delivered_volume,
           d.pay_date - d.deal_date AS days_to_pay, d.delivery_date - d.pay_date AS days_to_deliver,
           c.pay_term_days, c.delivery_term_days, c.base_price, c.delivery_basis
    FROM d
    LEFT JOIN contracts c ON c.contract_id = d.contract_id
    LEFT JOIN usd_rates r ON r.date = d.deal_date
    LEFT JOIN region_map m ON m.region_raw = d.region_raw
    LEFT JOIN product_keys pk ON pk.product_full = d.product_full
    LEFT JOIN participants ps ON ps.inn = d.seller_inn
    LEFT JOIN participants pb ON pb.inn = d.buyer_inn
    LEFT JOIN brokers bs ON bs.broker_code = d.seller_broker
    LEFT JOIN brokers bb ON bb.broker_code = d.buyer_broker
    ORDER BY d.deal_id;
    """)

    # ---------- search helpers (used by find_company / find_product tools) ----------
    comp = con.execute("""
      SELECT p.inn, p.name, p.role, p.region,
             coalesce(s.n, 0) AS deals_as_seller, coalesce(b.n, 0) AS deals_as_buyer
      FROM participants p
      LEFT JOIN (SELECT seller_inn AS inn, count(*) n FROM deals GROUP BY 1) s USING (inn)
      LEFT JOIN (SELECT buyer_inn AS inn, count(*) n FROM deals GROUP BY 1) b USING (inn)""").df()
    comp["name_norm"] = comp["name"].map(norm_company)
    con.register("comp_df", comp)
    con.execute("CREATE TABLE company_search AS SELECT * FROM comp_df")

    br = con.execute("SELECT * FROM brokers").df()
    br["name_norm"] = br["name"].map(norm_company)
    con.register("br_df", br)
    con.execute("CREATE TABLE broker_search AS SELECT * FROM br_df")

    con.execute("""
    CREATE TABLE product_search AS
    SELECT product_key, any_value(product_name) AS product_name, any_value(product_group) AS product_group,
           any_value(category) AS category, any_value(hs_code) AS hs_code, any_value(unit) AS unit,
           list(DISTINCT product_full) AS variants, count(*) AS n_deals,
           min(deal_date) AS first_deal, max(deal_date) AS last_deal
    FROM deals GROUP BY product_key;
    """)

    for t in ("raw_deals", "raw_contracts", "raw_participants", "raw_brokers", "raw_rates", "region_map"):
        con.execute(f"DROP TABLE {t}")
    con.execute("CHECKPOINT")

    # sanity report
    print("\nSanity checks:")
    for label, q in [
        ("deals", "SELECT count(*) FROM deals"),
        ("deals with bad date", "SELECT count(*) FROM deals WHERE deal_date IS NULL"),
        ("deals with bad amount", "SELECT count(*) FROM deals WHERE amount IS NULL"),
        ("deals without contract card", "SELECT count(*) FROM deals WHERE product_name IS NULL"),
        ("deals without USD rate", "SELECT count(*) FROM deals WHERE usd_rate IS NULL"),
        ("deals without seller name", "SELECT count(*) FROM deals WHERE seller_name IS NULL"),
        ("deals without buyer name", "SELECT count(*) FROM deals WHERE buyer_name IS NULL"),
        ("unrecognised regions", "SELECT string_agg(DISTINCT region, ', ') FROM deals WHERE region_ru IS NULL"),
        ("deals per year", "SELECT string_agg(y || ': ' || n, ' · ' ORDER BY y) FROM (SELECT year y, count(*) n FROM deals GROUP BY 1)"),
        ("currencies", "SELECT string_agg(currency || ': ' || n, ' · ') FROM (SELECT currency, count(*) n FROM deals GROUP BY 1)"),
        ("product spellings -> keys", "SELECT count(DISTINCT product_full) || ' -> ' || count(DISTINCT product_key) FROM deals"),
        ("keys still with roman/word grades (should be None)",
         "SELECT string_agg(DISTINCT product_key, ' | ') FROM deals WHERE regexp_matches(product_key, '(\\b(i|ii|iii|iv)\\s*(сорт|класс)|(сорт|класс)\\s*(i|ii|iii|iv)\\b|(перв|втор|трет)\\w*\\s*(сорт|класс))')"),
    ]:
        print(f"  {label}: {con.execute(q).fetchone()[0]}")
    con.close()
    os.replace(tmp, db_path)
    if os.path.exists(tmp + ".wal"):
        os.remove(tmp + ".wal")
    print(f"\nBuilt {db_path} in {time.time() - t0:.1f}s")


if __name__ == "__main__":
    build()