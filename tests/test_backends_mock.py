"""Checks both LLM backends end-to-end against a local mock API server (no real key needed).
Validates that tool calls / tool results are sent back in the correct wire format.
    python tests/test_backends_mock.py"""
import asyncio
import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
import config  # noqa: E402

SEEN = []


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        SEEN.append(body)
        msgs = body["messages"]
        if self.path.endswith("/messages"):          # Anthropic
            has_result = any(isinstance(m["content"], list) and any(c.get("type") == "tool_result" for c in m["content"]) for m in msgs)
            # strict alternation check
            roles = [m["role"] for m in msgs]
            assert all(a != b for a, b in zip(roles, roles[1:])), roles
            if not has_result:
                content = [{"type": "tool_use", "id": "tu1", "name": "sql", "input": {"query": "SELECT count(*) n FROM deals"}}]
                stop = "tool_use"
            else:
                res = [c for m in msgs if isinstance(m["content"], list) for c in m["content"] if c.get("type") == "tool_result"][0]
                n = res["content"].split("\n")[1]
                content = [{"type": "text", "text": f"Всего **{n}** сделок.\n@@BASIS@@\ndeals, все годы"}]
                stop = "end_turn"
            out = {"id": "m1", "type": "message", "role": "assistant", "model": body["model"], "content": content,
                   "stop_reason": stop, "stop_sequence": None, "usage": {"input_tokens": 1, "output_tokens": 1}}
        else:                                        # OpenAI
            tool_msgs = [m for m in msgs if m["role"] == "tool"]
            if not tool_msgs:
                msg = {"role": "assistant", "content": None, "tool_calls": [{"id": "c1", "type": "function", "function": {
                    "name": "sql", "arguments": json.dumps({"query": "SELECT count(*) n FROM deals"})}}]}
            else:
                n = tool_msgs[0]["content"].split("\n")[1]
                msg = {"role": "assistant", "content": f"Jami **{n}** ta bitim.\n@@BASIS@@\ndeals"}
            out = {"id": "x", "object": "chat.completion", "created": 0, "model": body["model"],
                   "choices": [{"index": 0, "message": msg, "finish_reason": "stop"}],
                   "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}}
        data = json.dumps(out).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


async def main():
    srv = HTTPServer(("127.0.0.1", 8765), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    import os
    os.environ["ANTHROPIC_BASE_URL"] = "http://127.0.0.1:8765"
    import agent as A
    for prov in ("anthropic", "openai"):
        config.LLM_PROVIDER = prov
        config.ANTHROPIC_API_KEY = "test"
        config.OPENAI_API_KEY = "test"
        config.OPENAI_BASE_URL = "http://127.0.0.1:8765/v1"
        ag = A.Agent(Path(__file__).parent / "fake.duckdb")
        r = await ag.answer("Сколько всего сделок?")
        print(prov, "->", r.answer, "| verified:", r.verified, "| sql:", r.queries)
        assert r.verified and r.queries
    srv.shutdown()
    print("backends ok")


asyncio.run(main())
