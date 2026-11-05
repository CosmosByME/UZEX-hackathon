"""Offline tests (no API key needed): verifier + agent loop with a scripted fake LLM.
    python tests/test_offline.py"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
import agent as A  # noqa: E402

DB = Path(__file__).parent / "fake.duckdb"


def test_verifier():
    ev = "year | n | s\n2024 | 2266 | 4053734341040.5029\nfirst | 2024-03-05"
    assert A.verify("В 2024 году **2 266** сделок на **4 053 734 341 040.50** сум", ev, "") == []
    assert A.verify("Сделка от 05.03.2024", ev, "") == []
    assert A.verify("Около **4.05 трлн** сум", ev, "") == []
    assert A.verify("Всего **3 100** сделок", ev, "") == ["3 100"]
    assert A.verify("Дата 06.03.2024", ev, "") == ["06.03.2024"]
    assert A.verify("Доля 12.5%", "share\n0.125", "") == []
    print("verifier ok")


class FakeLLM:
    """Step 1: SQL. Step 2: answer with an invented number. Step 3 (after verifier): corrected answer."""
    def __init__(self):
        self.n = 0

    def start(self, history, q):
        return [{"role": "user", "content": q}]

    async def step(self, system, msgs, allow_tools=True):
        self.n += 1
        if self.n == 1:
            return "", [("c1", "sql", {"query": "SELECT count(*) AS n FROM deals WHERE year = 2024"})]
        if self.n == 2:
            return "В 2024 году заключено **9 999** сделок.\n@@BASIS@@\ndeals, 2024", []
        n = [m for m in msgs if m["role"] == "tool"][0]["content"].split("\n")[1]
        return f"В 2024 году заключено **{n}** сделок.\n@@BASIS@@\nРеестр биржевых сделок за 2024 год, все статусы.", []

    def add_results(self, msgs, results):
        for cid, out in results:
            msgs.append({"role": "tool", "tool_call_id": cid, "content": out})

    def add_user(self, msgs, text):
        msgs.append({"role": "user", "content": text})


async def test_agent_loop():
    ag = A.Agent.__new__(A.Agent)
    ag.tools = A.DataTools(DB)
    ag.system = A.SYSTEM.replace("{schema}", ag.tools.schema_doc())
    ag.llm = FakeLLM()
    r = await ag.answer("Сколько сделок было в 2024 году?")
    print(r.answer, "|", r.basis, "| verified:", r.verified, "| steps:", r.steps, f"| {r.elapsed:.2f}s")
    assert r.verified and "9 999" not in r.answer and "сделки" in r.answer and ag.llm.n == 3
    print("agent loop ok (invented number was caught and corrected)")


def test_language_and_style():
    from textnorm import detect_lang, product_query_ru
    assert detect_lang("2025-yilda nechta bitim tuzilgan?") == "uz"
    assert detect_lang("Сделки Artel Electronics Group") == "ru"
    assert detect_lang("2025 йилда нечта битим тузилган?") == "uzc"
    assert detect_lang("2025-yilda цемент narxi qancha?") == "uz"
    assert product_query_ru("paxta xom ashyosining 1-navi") == "хлопок-сырец 1 сорт"
    assert product_query_ru("буғдой") == "пшеница"
    assert A.language_issues("Qishloq xo‘jaligi mahsulotlari (Сельскохозяйственная продукция)", "uz")
    assert A.jargon_issues("`deals` jadvali, amount_uzs bo‘yicha") and not A.jargon_issues("Birja bitimlari reyestri")
    assert A.polish("2025 yil ma'lumot yo'q, reestr", ["uz"]) == "2025-yil ma’lumot yo‘q, reyestr"
    assert A.polish("заключено **2664** сделок, 21 сделки, 115 763 сделок, 13 сделка, из 21 сделки, 539 514.44 тонны", ["ru"]) == \
        "заключено **2664** сделки, 21 сделка, 115 763 сделки, 13 сделок, из 21 сделки, 539 514.44 тонны"
    print("language/style ok")


if __name__ == "__main__":
    test_verifier()
    test_language_and_style()
    asyncio.run(test_agent_loop())
