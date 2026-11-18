"""Model providers. Retries are recorded, never hidden."""
import json, os, time, urllib.error, urllib.request


class ProviderError(Exception):
    def __init__(self, message, attempts):
        super().__init__(message)
        self.attempts = attempts


class OpenAICompatible:
    def __init__(self, base=None, key=None, model=None, sleep=time.sleep, max_retries=3, timeout=120):
        self.base = base or os.environ.get("NEUROMESH_BASE_URL", "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions")
        self.key = key or os.environ.get("NEUROMESH_API_KEY")
        self.model = model or os.environ.get("NEUROMESH_MODEL", "gemini-2.5-flash")
        self.sleep, self.max_retries, self.timeout = sleep, max_retries, timeout
        if not self.key:
            raise RuntimeError("Set NEUROMESH_API_KEY before live evaluation")

    def chat(self, messages, tools=None, max_tokens=1800):
        body = {"model": self.model, "messages": messages, "max_tokens": max_tokens}
        if tools: body["tools"] = tools
        req = urllib.request.Request(self.base, data=json.dumps(body).encode(),
                                     headers={"Authorization": f"Bearer {self.key}", "Content-Type": "application/json"})
        attempts, started = [], time.time()
        for n in range(1, self.max_retries + 2):
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as r:
                    data = json.loads(r.read())
                attempts.append({"attempt": n, "ok": True})
                return {"message": data["choices"][0]["message"], "usage": data.get("usage", {}),
                        "latency_seconds": round(time.time() - started, 3), "attempts": attempts}
            except urllib.error.HTTPError as ex:
                attempts.append({"attempt": n, "ok": False, "error": f"HTTP {ex.code}"})
                if ex.code != 429 and not 500 <= ex.code < 600:
                    raise ProviderError(f"HTTP {ex.code}", attempts)
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, KeyError) as ex:
                attempts.append({"attempt": n, "ok": False, "error": type(ex).__name__})
            if n <= self.max_retries:
                self.sleep(2 ** n)
        raise ProviderError("retries exhausted", attempts)


class MockProvider:
    """Scripted provider for tests: fn(messages, tools, call_index) -> message | (message, usage)."""
    model = "mock"

    def __init__(self, fn):
        self.fn, self.n, self.seen = fn, 0, []

    def chat(self, messages, tools=None, max_tokens=1800):
        self.seen.append({"messages": json.loads(json.dumps(messages)), "tools": tools})
        out = self.fn(messages, tools, self.n)
        self.n += 1
        message, usage = out if isinstance(out, tuple) else (out, {"total_tokens": 100})
        return {"message": message, "usage": usage, "latency_seconds": 0.0, "attempts": [{"attempt": 1, "ok": True}]}
