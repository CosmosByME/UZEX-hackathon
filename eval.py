"""Ask questions without Telegram.

    python eval.py "2025-yilda nechta bitim bo'lgan?"     # one question
    python eval.py                                         # all questions from questions.txt
    python eval.py questions.txt --trace                   # also print every tool call

Prints answer, basis, time, steps and the verifier verdict. Check every answer against your own SQL!
"""
import asyncio
import sys
import time

from agent import Agent


async def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    trace = "--trace" in sys.argv
    if args and not args[0].endswith(".txt"):
        questions = [" ".join(args)]
    else:
        path = args[0] if args else "questions.txt"
        questions = [l.strip() for l in open(path, encoding="utf-8") if l.strip() and not l.startswith("#")]
    ag = Agent()
    slow, unverified, t_all = 0, 0, time.time()
    for i, q in enumerate(questions, 1):
        print(f"\n{'=' * 90}\n[{i}/{len(questions)}] {q}")
        try:
            r = await asyncio.wait_for(ag.answer(q), timeout=90)
        except asyncio.TimeoutError:
            print("!!! TIMEOUT (>90 s)")
            slow += 1
            continue
        except Exception as e:
            print(f"!!! ERROR: {type(e).__name__}: {str(e)[:400]}")
            continue
        if trace:
            for t in r.trace:
                print(f"  -> {t['tool']}: {t['args']}\n     {t['result'][:600]}")
        print("-" * 90 + "\n" + r.answer)
        print(f"  [basis] {r.basis}")
        flag = "" if r.verified else f"   !!! UNVERIFIED: {r.unverified}"
        print(f"  [{r.elapsed:.1f}s, {r.steps} tool calls]{flag}")
        slow += r.elapsed > 60
        unverified += not r.verified
    print(f"\nDone: {len(questions)} questions in {time.time() - t_all:.0f}s; >60s: {slow}; unverified: {unverified}")


if __name__ == "__main__":
    asyncio.run(main())