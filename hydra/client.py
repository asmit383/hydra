"""Generated client — replay a discovered API directly, no browser. (v0.1)

Given an ApiCandidate (url, method, headers, params, auth), hit the endpoint with
httpx and return the JSON. This is what makes it fast + deterministic after
discovery.
"""
# TODO(v0.1): build_client(candidate) -> callable that returns the data
