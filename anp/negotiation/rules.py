"""
ANP · Rules
===========
Estrategias de negociación intercambiables.
Tanto buyer como seller reciben una estrategia al crearse.
"""
from abc import ABC, abstractmethod


class BuyerStrategy(ABC):
    @abstractmethod
    def next_counter(self, current_offer: float, max_price: float, round_n: int) -> float:
        """Dado el precio del vendedor, devuelve contraoferta del comprador."""
        ...

    @abstractmethod
    def should_accept(self, offer: float, max_price: float) -> bool:
        """¿Acepta el comprador esta oferta?"""
        ...


class SellerStrategy(ABC):
    @abstractmethod
    def next_offer(self, last_counter: float | None, min_price: float, start_price: float, round_n: int) -> float:
        """Devuelve la siguiente oferta del vendedor."""
        ...

    @abstractmethod
    def should_reject(self, counter: float, min_price: float) -> bool:
        """¿Rechaza el vendedor esta contraoferta?"""
        ...


# ── Estrategias de comprador ──────────────────────────────────────────────────

class BuyerLinear(BuyerStrategy):
    """Sube el precio en pasos fijos hacia max_price."""
    def __init__(self, step_pct: float = 0.3):
        self.step_pct = step_pct  # sube X% del gap restante por ronda

    def next_counter(self, current_offer: float, max_price: float, round_n: int) -> float:
        gap = max_price - current_offer
        counter = current_offer + gap * self.step_pct
        return round(min(counter, max_price), 2)

    def should_accept(self, offer: float, max_price: float) -> bool:
        return offer <= max_price


class BuyerPatient(BuyerStrategy):
    """Espera N rondas antes de subir, luego salta al máximo."""
    def __init__(self, patience: int = 3):
        self.patience = patience

    def next_counter(self, current_offer: float, max_price: float, round_n: int) -> float:
        if round_n < self.patience:
            # ofrece lo mismo (presión al vendedor para que baje)
            return round(current_offer * 1.01, 2)
        return round(max_price * 0.98, 2)  # casi al límite

    def should_accept(self, offer: float, max_price: float) -> bool:
        return offer <= max_price


class BuyerAggressive(BuyerStrategy):
    """Va directo al máximo desde la primera ronda."""
    def next_counter(self, current_offer: float, max_price: float, round_n: int) -> float:
        return round(max_price, 2)

    def should_accept(self, offer: float, max_price: float) -> bool:
        return offer <= max_price


# ── Estrategias de vendedor ───────────────────────────────────────────────────

class SellerLinear(SellerStrategy):
    """Baja el precio en pasos fijos hacia min_price."""
    def __init__(self, step_pct: float = 0.35):
        self.step_pct = step_pct

    def next_offer(self, last_counter, min_price: float, start_price: float, round_n: int) -> float:
        gap = start_price - min_price
        offer = start_price - gap * self.step_pct * round_n
        return round(max(offer, min_price), 2)

    def should_reject(self, counter: float, min_price: float) -> bool:
        return counter < min_price


class SellerDeadline(SellerStrategy):
    """Baja rápido si el comprador tiene deadline cercano (futuro: usa deadline del BID)."""
    def next_offer(self, last_counter, min_price: float, start_price: float, round_n: int) -> float:
        # Por ahora baja agresivamente cada ronda
        drop = (start_price - min_price) * (0.5 ** round_n)
        return round(max(start_price - drop, min_price), 2)

    def should_reject(self, counter: float, min_price: float) -> bool:
        return counter < min_price * 0.95  # tolera 5% bajo mínimo antes de rechazar


# Defaults exportados
DEFAULT_BUYER_STRATEGY  = BuyerLinear()
DEFAULT_SELLER_STRATEGY = SellerLinear()
