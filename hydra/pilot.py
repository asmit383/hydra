"""The decision layer — the optional LLM 'brain' over the SDK's generic map.

The SDK maps the page (`snapshot`) and acts (`click`/`scroll`); it has NO site or language
knowledge. `pilot()` closes the loop: each step it shows the map to a **decider** and executes
the one action it returns — until the decider says `done`. The decider is **injectable**:
- `claude_decider()` asks Claude (Anthropic API) — reads labels in any language, tells a real
  match from a nav link or a pools game (the thing a regex can't).
- any `state -> {"action","id","why"}` function works — used in tests, or to swap models.

This is why the flaky regex driver becomes reliable: judgment moves to the model, while the
loop, the capture, and the safety stay deterministic. `snapshot()` carries **no tokens/headers**,
so nothing sensitive is ever sent to the model.
"""
import json
import re

_ACTIONS = ("click", "scroll", "done", "stop")

_SYSTEM = (
    "You are the navigation brain of a web-scraping agent. You are given a GOAL and the current "
    "page as a list of interactive elements, each with a numeric id. Choose the SINGLE best next "
    "action to make progress toward the goal.\n"
    "- If an overlay is up (cookie bar, popup), dismiss it first by clicking its control.\n"
    "- Prefer real content/navigation toward the goal over ads, promos, or unrelated sections.\n"
    "- If the target isn't in the list, scroll to reveal more.\n"
    "- Say done once the goal page is loaded (e.g. the odds/markets are on screen).\n"
    'Reply with ONLY a JSON object, no prose: {"action":"click","id":N,"why":"..."} or '
    '{"action":"scroll","why":"..."} or {"action":"done","why":"..."}.'
)


def format_state(goal: str, snap: dict, step: int, max_steps: int) -> str:
    """Render a snapshot() into a compact prompt (ids + labels only — no tokens/headers)."""
    lines = [f"GOAL: {goal}", f"STEP {step}/{max_steps}", ""]
    ov = snap.get("overlays") or []
    lines.append("OVERLAYS UP (dismiss before navigating):" if ov else "OVERLAYS: none")
    for e in ov:
        lines.append(f"  [{e['id']}] {e.get('label') or '(icon)'}")
    sc = snap.get("scroll") or {}
    lines.append(f"\nSCROLL: y={sc.get('y', 0)} of {sc.get('height', '?')} · more below = "
                 f"{'yes' if sc.get('hasMore') else 'no'}\n")
    lines.append("ELEMENTS (id · role · label):")
    for e in snap.get("elements") or []:
        lines.append(f"  [{e['id']}] {e['role']} {(e.get('label') or '')[:48]!r}")
    return "\n".join(lines)


def parse_action(text: str) -> dict:
    """Tolerantly pull the JSON action out of a model reply (handles code fences / stray prose)."""
    m = re.search(r"\{.*\}", text or "", re.S)
    if not m:
        return {"action": "stop", "why": "no action parsed"}
    try:
        d = json.loads(m.group(0))
    except Exception:
        return {"action": "stop", "why": "unparseable action"}
    if d.get("action") not in _ACTIONS:
        d["action"] = "stop"
    return d


def pilot(h, goal: str, decide, *, max_steps: int = 14, log=print) -> list[dict]:
    """Drive `h` toward `goal`: snapshot → decide → act, capturing the APIs each click fires.
    `decide(state_text) -> {"action","id","why"}`. Returns `h.context` (the discovered APIs)."""
    for step in range(1, max_steps + 1):
        snap = h.snapshot(limit=40)
        action = decide(format_state(goal, snap, step, max_steps)) or {}
        act, tid, why = action.get("action"), action.get("id"), (action.get("why") or "")[:70]
        log(f"[{step}] {act} {tid if tid is not None else ''} — {why}")
        if act in ("done", "stop"):
            break
        if act == "scroll":
            h.scroll(steps=3)
        elif act == "click" and tid is not None:
            h.act(tid, label=f"llm:{why[:24]}", wait_ms=3500)     # click + capture what it fires
        try:
            h.session.page.wait_for_timeout(400)                  # let the SPA settle
        except Exception:
            pass
    return getattr(h, "context", [])


def claude_decider(model: str = "claude-sonnet-4-6", *, api_key: str | None = None,
                   max_tokens: int = 250):
    """A decider backed by Claude. Lazy-imports `anthropic` so the rest of pilot works without it.
    Needs `pip install anthropic` and ANTHROPIC_API_KEY (or pass api_key=)."""
    import anthropic
    client = anthropic.Anthropic(**({"api_key": api_key} if api_key else {}))

    def decide(state_text: str) -> dict:
        r = client.messages.create(model=model, max_tokens=max_tokens, system=_SYSTEM,
                                   messages=[{"role": "user", "content": state_text}])
        return parse_action("".join(b.text for b in r.content if getattr(b, "type", "") == "text"))

    return decide


__all__ = ["pilot", "claude_decider", "format_state", "parse_action"]
