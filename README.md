# UZEX bitimlar agenti — AI agent for the exchange deal registry

Telegram bot that answers questions about exchange deals in **Russian and Uzbek** (Latin and Cyrillic),
**only from the data**, and says plainly when the data has no answer. Under every answer there is an
expandable **"Basis / Основание"** block with the filters, assumptions and the exact SQL query used.

## 1. Quick start (≈15 minutes)

```bash
pip install -r requirements.txt
cp .env.example .env            # put TELEGRAM_TOKEN and ANTHROPIC_API_KEY (or OpenAI-compatible key)
mkdir data                      # copy ALL CSV files from the hackathon folder into data/
python loader.py                # builds exchange.duckdb (~1 min for 500 000 deals) and prints sanity checks
python eval.py "2025-yilda nechta bitim tuzilgan?"     # one question in the terminal
python eval.py                  # all practice questions from questions.txt
python bot.py                   # start the Telegram bot
```

Read the **sanity checks** printed by `loader.py`: every "bad/without" line should be 0 (or explainable),
"unrecognised regions" should be `None`, and deals per year should match the README
(84 299 · 93 985 · 106 647 · 115 763 · 99 306).

Offline tests (no API key): `python tests/make_fake_data.py && DATA_DIR=tests/fake_data DB_PATH=tests/fake.duckdb python loader.py && python tests/test_offline.py`

## 2. How it works

```
question (RU/UZ) ─► LLM agent ──tool calls──► sql(query)        ─► DuckDB (clean, joined tables)
                        ▲                    find_company(name) ─► fuzzy search, Cyrillic↔Latin
                        │                    find_product(text) ─► fuzzy search over all spellings
                        └──── results ◄──────────────┘
final answer ─► VERIFIER: every number/date must exist in a tool result ─► if not, sent back to fix
             ─► Telegram: answer + expandable "Basis" (filters + SQL + time)
```

* **loader.py** cleans the raw CSVs once: `"78 356 027.52"` → number, `03.01.2026` → date, one wide `deals`
  table already joined with the contract card (currency, product attributes, ТН ВЭД, group), USD rate of the
  deal date (`amount_uzs`, `amount_usd`), seller/buyer/broker names, `volume = qty × lot`, `unit_price`,
  `days_to_pay`, `is_cancelled`. Regions get one spelling (deals use Uzbek, contracts use Russian).
  Product spellings ("1 сорт", "1-сорта", "СОРТ 1 СОРТ") collapse into one `product_key`.
* **tools.py** — the only way the model can see data. SQL is read-only (single SELECT, keyword blocklist,
  read-only connection with external access disabled, 15 s timeout, max 60 rows returned).
* **agent.py** — the system prompt holds the schema, the real categorical values (statuses, regions,
  groups…) and the rules: no outside knowledge, compute everything in SQL, exclude cancelled deals from
  turnover, never mix UZS and USD, answer in the question's language, say "no data" when there is none.
  The **verifier** is plain Python (not an LLM): it extracts all numbers and dates from the answer and checks
  each against the tool outputs. This is the main protection against disqualification.
* **Time limit**: the agent stops calling tools after 60 s and must answer; hard limit 82 s (committee: 90 s).
* Works with Claude (`LLM_PROVIDER=anthropic`) or any OpenAI-compatible API (`LLM_PROVIDER=openai`).

## 3. Plan until the deadline (5 Nov, 18:00)

1. **Now** — load the real data, read the sanity checks, fix anything that is not 0.
2. **Run `python eval.py questions.txt --trace`** and check every answer **by hand** with your own SQL
   (e.g. in `python -c "import duckdb; print(duckdb.connect('exchange.duckdb').sql('...'))"`).
   Add your own questions — think like the committee: counts, sums, top-N, averages, a specific deal,
   company, broker, region, month, status, export/USD, exchange rate, delivery/payment terms.
3. Every wrong answer → improve the system prompt rules in `agent.py` (most fixes are one line there).
4. Traps (questions at the end of `questions.txt`) **must** answer "no data". Never relax this.
5. **Deploy by ~15:00** on a machine that stays on (VPS, a server at work, or a PC that won't sleep);
   test from another phone, then submit the form. Do not change the bot after 18:00.
6. During checking: keep the bot running, watch `logs/qa.jsonl`, keep the API account topped up.

Deploy on a Linux VPS with systemd:
```ini
# /etc/systemd/system/uzexbot.service
[Unit]
After=network-online.target
[Service]
WorkingDirectory=/opt/uzex-bot
ExecStart=/usr/bin/python3 bot.py
Restart=always
[Install]
WantedBy=multi-user.target
```
`systemctl enable --now uzexbot` · logs: `journalctl -u uzexbot -f`. Or Docker: `docker build -t uzexbot . && docker run -d --restart=always --env-file .env uzexbot`.

## 4. Files
| File | Purpose |
|---|---|
| `loader.py` | CSV → clean DuckDB database + sanity report |
| `tools.py` | sql / find_company / find_product tools, schema description |
| `agent.py` | LLM agent loop, system prompt, number/date verifier |
| `bot.py` | Telegram bot (aiogram 3), "Basis" block, Q&A log |
| `eval.py`, `questions.txt` | test questions from the terminal |
| `textnorm.py` | Cyrillic↔Latin, company/product/region normalisation, language detection |
| `SOLUTION.md` | text for the "Yechim tavsifi / Описание решения" field of the form |
