"""Detection diagnosis — which fingerprint layer leaked? (v0.2)

When blocked, diff Hydra's fingerprint/behavior vs a real-browser baseline
(probe a detection-test endpoint), identify the offending signal. LLM-Doc/kdoc
DNA, applied to anti-detection.
"""
# TODO(v0.2): diagnose(page) -> LeakReport (which of TLS/fingerprint/behavior/IP)
