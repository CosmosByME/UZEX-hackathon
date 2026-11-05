"""Shows which models your API key can really use right now.

    python check_models.py           # lists models, then tests the Flash/Lite ones with one tiny request each
    python check_models.py --all     # test every chat model in the list (uses more quota)
"""
import sys

from openai import NotFoundError, OpenAI, RateLimitError

import config

client = OpenAI(api_key=config.OPENAI_API_KEY, base_url=config.OPENAI_BASE_URL, max_retries=0, timeout=30)
TOOL = [{"type": "function", "function": {"name": "sql", "description": "Run SQL",
         "parameters": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}}}]


def err(e):
    import json
    body = getattr(e, "body", None)
    b = body if isinstance(body, str) else json.dumps(body, ensure_ascii=False) if body else ""
    return (str(e) + " " + b)[:300]

try:
    ids = sorted(m.id.removeprefix("models/") for m in client.models.list())
except Exception as e:
    sys.exit(f"Cannot list models: {e}")

skip = ("embedding", "imagen", "veo", "tts", "audio", "image", "aqa", "live", "robotics", "computer-use")
chat = [m for m in ids if not any(s in m for s in skip)]
print(f"{len(ids)} models available for this key; chat models:\n  " + "\n  ".join(chat))

test = chat if "--all" in sys.argv else [m for m in chat if "flash" in m or "lite" in m or "gemma" in m]
print(f"\nTesting {len(test)} models with one tiny request each:\n")
ok = []
for m in test:
    try:
        # the agent needs TOOL CALLING, so test exactly that
        r = client.chat.completions.create(
            model=m, messages=[{"role": "system", "content": "Use the tool."},
                               {"role": "user", "content": "How many deals are there? Use the sql tool."}],
            tools=TOOL, tool_choice="auto")
        if r.choices[0].message.tool_calls:
            print(f"  OK        {m}  (tool calling works)")
            ok.append(m)
        else:
            print(f"  NO TOOLS  {m}  -> answered without calling the tool; not suitable")
    except RateLimitError as e:
        print(f"  LIMIT     {m}  -> {err(e)}")
    except NotFoundError:
        print(f"  NOT FOUND {m}")
    except Exception as e:
        print(f"  ERROR     {m}  -> {err(e)}  (not suitable)")

if ok:
    print("\nWorking models. Put the best one in LLM_MODEL and 1-2 others (comma-separated) in LLM_FALLBACK_MODEL, e.g.:")
    print(f"  LLM_MODEL={ok[0]}")
    if len(ok) > 1:
        print(f"  LLM_FALLBACK_MODEL={','.join(ok[1:3])}")
    print("Also check per-model daily limits at https://aistudio.google.com/rate-limit")