"""Per-run spend cap.

Off unless SPEND_CAP_USD is set. When on, every GPU pod reserves
`price x SPEND_RESERVE_MINUTES` before it is created, and the reservation is
replaced by `price x actual lifetime` once the pod is deleted. A pod whose
reservation would take spent + reserved past the cap is never created; the
runner reports that job as SKIP, which a sweep reads as "untested", never as
incompatible.

Prices are the catalog's $/hr for the tier the job runs in, captured while
each tier is planned (the catalog is reloaded per tier, so it can't be read
back at run time). It is an estimate of what RunPod bills — disk and partial
minutes aside — which is why the reservation, not the settled figure, is
what gates creation.
"""

from __future__ import annotations

import threading
from typing import Optional

from . import config

_lock = threading.Lock()
_prices: dict[tuple[str, str], float] = {}
_holds: dict[int, tuple[float, float]] = {}  # token -> (hold USD, $/hr)
_spent = 0.0
_next_token = 0


def enabled() -> bool:
    return config.SPEND_CAP_USD > 0


def reset() -> None:
    """Forget prices and spend. For tests."""
    global _spent, _next_token
    with _lock:
        _prices.clear()
        _holds.clear()
        _spent = 0.0
        _next_token = 0


def record_prices(cloud: str, catalog: list[dict]) -> None:
    """Remember each GPU's $/hr in `cloud`, from the catalog just loaded."""
    tier = (cloud or "").upper()
    field = "communityPrice" if tier == "COMMUNITY" else "securePrice"
    with _lock:
        for gpu in catalog:
            name = gpu.get("displayName") or ""
            try:
                price = float(gpu.get(field) or 0)
            except (TypeError, ValueError):
                price = 0.0
            if name and price > 0:
                _prices[(name.lower(), tier)] = price


def price_for(instance: str, cloud: str) -> Optional[float]:
    """$/hr for `instance` in `cloud`.

    A GPU missing from the price map is charged at the highest price known,
    so a catalog gap can't slip a pod past the cap. None only when no price
    is known at all — the caller then refuses to create anything.
    """
    tier = (cloud or config.CLOUD_TYPE or "").upper()
    with _lock:
        price = _prices.get((instance.lower(), tier))
        if price:
            return price
        return max(_prices.values(), default=None)


def reserve(instance: str, cloud: str) -> tuple[Optional[int], str]:
    """Hold money for one pod. Returns (token, "") or (None, reason).

    Token 0 means "cap disabled, nothing held" and is safe to settle.
    """
    global _next_token
    if not enabled():
        return 0, ""
    price = price_for(instance, cloud)
    if price is None:
        return None, (
            "spend cap is set but no GPU prices were loaded from the catalog, "
            "so the cost of a pod can't be bounded"
        )
    hold = price * config.SPEND_RESERVE_MINUTES / 60.0
    cap = config.SPEND_CAP_USD
    with _lock:
        committed = _spent + sum(h for h, _rate in _holds.values())
        if committed + hold > cap + 1e-9:
            return None, (
                f"spend cap reached: ${committed:.2f} of ${cap:.2f} spent or "
                f"held, and this pod would hold ${hold:.2f} "
                f"(${price:.2f}/hr x {config.SPEND_RESERVE_MINUTES:g} min)"
            )
        _next_token += 1
        token = _next_token
        _holds[token] = (hold, price)
    return token, ""


def settle(token: Optional[int], seconds: float) -> None:
    """Replace a hold with what the pod cost over `seconds` of life."""
    global _spent
    if not token:
        return
    with _lock:
        _hold, rate = _holds.pop(token, (0.0, 0.0))
        _spent += rate * max(0.0, seconds) / 3600.0


def release(token: Optional[int]) -> None:
    """Drop a hold for a pod that was never created."""
    if not token:
        return
    with _lock:
        _holds.pop(token, None)


def spent() -> float:
    with _lock:
        return _spent


def estimate(jobs: list[tuple[str, str]]) -> float:
    """Worst-case hold for `(instance, cloud)` pairs if every one ran."""
    total = 0.0
    for instance, cloud in jobs:
        price = price_for(instance, cloud) or 0.0
        total += price * config.SPEND_RESERVE_MINUTES / 60.0
    return total
