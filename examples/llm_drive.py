"""Demo: an LLM drives Hydra to a goal — the decision layer over the generic page map.

Hydra maps the page (`snapshot`) and acts (`click`/`scroll`) with no site knowledge; Claude
reads the map each step and picks the id — dismissing overlays, telling a real match from a
nav link or a pools game, in any language. That's what turns the flaky regex driver reliable.
Every click captures the APIs it fires, so the run ends with the discovered odds endpoints.

Setup:
  pip install anthropic
  export ANTHROPIC_API_KEY=sk-...

Run (headful so you watch it think + click):
  python examples/llm_drive.py "<start_url>" "<goal>"
  python examples/llm_drive.py "https://www.sisal.it/scommesse-matchpoint" \
      "open a football (Calcio) match and load its odds"

Needs proxies.txt at the repo root for geo-locked sites.
"""
import os
import random
import sys

ROOT = __file__.rsplit("/examples/", 1)[0]
sys.path.insert(0, ROOT)
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(ROOT, ".env"))
except Exception:
    pass
from hydra import Hydra
from hydra.pilot import claude_decider, openai_decider, pilot

PROXIES = os.path.join(ROOT, "proxies.txt")


def pick_decider():
    """OpenAI-compatible key wins (portable, no extra dep); else native Claude."""
    model = os.environ.get("HYDRA_MODEL")
    if os.environ.get("OPENAI_API_KEY"):
        return openai_decider(model=model or "gpt-4o-mini")
    if os.environ.get("ANTHROPIC_API_KEY"):
        return claude_decider(model=model or "claude-sonnet-4-6")
    return None


def main():
    if len(sys.argv) < 3:
        print('usage: python examples/llm_drive.py "<start_url>" "<goal>"')
        return
    url, goal = sys.argv[1], sys.argv[2]
    decide = pick_decider()
    if decide is None:
        print("set OPENAI_API_KEY (any OpenAI-compatible provider) or ANTHROPIC_API_KEY in .env")
        return

    proxies = PROXIES if os.path.exists(PROXIES) else None
    with Hydra(proxies=proxies, seed=random.randint(1, 99999), headful=True) as h:
        print(f"→ {url}\n  goal: {goal}\n")
        h.open(url, wait_ms=6000)
        pilot(h, goal, decide, max_steps=16)

        print("\n── APIs discovered along the way (tagged by the step that fired them) ──")
        for x in sorted(h.context, key=lambda x: -(x.get("size") or 0))[:12]:
            print(f"  {x['fired_on']:<26} {x['method']} {x['status']} "
                  f"{str(x['shape']):11} {x['size']:>9}b  {x['url'][:78]}")
        h.session.page.wait_for_timeout(6000)


if __name__ == "__main__":
    main()
