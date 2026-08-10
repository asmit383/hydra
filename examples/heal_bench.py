"""Measure it: does self-healing actually beat a static baseline?

Runs N trials of each strategy against a target that blocks, and reports the
recovery-rate gap. That gap IS the proof the adaptive loop is worth it.

    PROXIES_FILE=./proxies.txt python examples/heal_bench.py <url> --trials 10

A trial "recovers" if any attempt in its budget comes back un-blocked.
  - static  : one exit, reused across the trial's attempts (rotation OFF)
  - adaptive: a fresh exit each attempt (rotation ON)
Keep --max-attempts equal so both strategies get the same budget.
"""
import argparse

from hydra.stealth import resilient_capture


def run(url, *, rotate, trials, max_attempts, proxies_file):
    wins = 0
    used = 0
    for t in range(1, trials + 1):
        r = resilient_capture(url, proxy_mode="file", proxies_file=proxies_file,
                              max_attempts=max_attempts, rotate=rotate)
        used += r.tries
        if r.recovered:
            wins += 1
        tag = "recovered" if r.recovered else "blocked"
        print(f"  trial {t:>2}/{trials}  {tag:<9} in {r.tries} attempt(s)")
    return wins, used


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("url")
    ap.add_argument("--trials", type=int, default=10)
    ap.add_argument("--max-attempts", type=int, default=3)
    ap.add_argument("--proxies-file")
    args = ap.parse_args()

    print(f"\n=== STATIC baseline (one exit, reused) — {args.trials} trials ===")
    s_wins, s_used = run(args.url, rotate=False, trials=args.trials,
                         max_attempts=args.max_attempts, proxies_file=args.proxies_file)

    print(f"\n=== ADAPTIVE (rotate exit each attempt) — {args.trials} trials ===")
    a_wins, a_used = run(args.url, rotate=True, trials=args.trials,
                         max_attempts=args.max_attempts, proxies_file=args.proxies_file)

    print("\n" + "=" * 48)
    print(f"static   recovery-rate: {s_wins}/{args.trials} = {s_wins/args.trials:.0%}"
          f"   ({s_used} attempts spent)")
    print(f"adaptive recovery-rate: {a_wins}/{args.trials} = {a_wins/args.trials:.0%}"
          f"   ({a_used} attempts spent)")
    gap = (a_wins - s_wins) / args.trials
    print(f"self-healing lift: {gap:+.0%}")


if __name__ == "__main__":
    main()
