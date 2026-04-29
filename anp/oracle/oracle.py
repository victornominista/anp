"""
ANP · Oracle
============
Fachada principal del módulo oracle.
Conecta PriceFeed + Validator y se engancha al NegotiationEngine.

Integración x402/MPP:
  x402 es el protocolo de micropagos HTTP (EIP-402 / BIP-payment).
  Cuando una transacción supera el threshold, el oráculo devuelve
  x402_required=True y el endpoint donde debe completarse el pago
  antes de que el agente confirme el trato.

  Esto permite que ANP sea compatible con:
  - x402 (Coinbase / Base L2)
  - MPP (Lightning Network micropayments)
  - Cualquier sistema que siga el patrón HTTP 402 Payment Required
"""
from pathlib import Path
from typing import Optional

from .price_feed import PriceFeed, PriceEntry
from .validator import OracleValidator, ValidationResult, ValidationStatus, SavingsTracker


class Oracle:
    """
    Punto de entrada único para el oráculo de precios ANP.

    Uso rápido:
        oracle = Oracle.from_json("feeds/sample_prices.json")
        result = oracle.check_buy("api_access", 0.50)
        if result.blocked:
            print(result.reason)
            print(f"Ahorro: ${result.savings_usd}")
    """

    def __init__(
        self,
        feed: Optional[PriceFeed] = None,
        soft_tolerance: float = 0.20,
        warn_tolerance: float = 0.10,
        x402_endpoint: Optional[str] = None,
        x402_threshold_usd: float = 1.0,
    ):
        self.feed = feed or PriceFeed()
        self.validator = OracleValidator(
            feed=self.feed,
            soft_tolerance=soft_tolerance,
            warn_tolerance=warn_tolerance,
            x402_endpoint=x402_endpoint,
            x402_threshold_usd=x402_threshold_usd,
        )

    @classmethod
    def from_json(
        cls,
        path: str | Path,
        x402_endpoint: Optional[str] = None,
        **kwargs,
    ) -> "Oracle":
        """Crea un Oracle cargando precios desde archivo JSON."""
        feed = PriceFeed()
        n = feed.load_json(path)
        instance = cls(feed=feed, x402_endpoint=x402_endpoint, **kwargs)
        return instance

    @classmethod
    def from_dict(cls, prices: dict, **kwargs) -> "Oracle":
        """Crea un Oracle con precios en memoria (útil para tests)."""
        feed = PriceFeed()
        feed.load_dict(prices)
        return cls(feed=feed, **kwargs)

    # ── API pública ───────────────────────────────────────────────────────────

    def check_buy(self, item: str, price: float, qty: int = 1) -> ValidationResult:
        """Comprador: ¿es seguro pagar este precio?"""
        return self.validator.validate_buy(item, price, qty)

    def check_sell(self, item: str, price: float, qty: int = 1) -> ValidationResult:
        """Vendedor: ¿es seguro cobrar este precio?"""
        return self.validator.validate_sell(item, price, qty)

    def get_base_price(self, item: str) -> Optional[float]:
        return self.feed.get_price(item)

    def try_refresh_x402(self, endpoint: str) -> int:
        """
        Intenta actualizar precios desde endpoint x402/MPP.
        Devuelve número de precios actualizados (0 si falló).
        """
        return self.feed.load_x402(endpoint)

    @property
    def savings(self) -> SavingsTracker:
        return self.validator.tracker

    def savings_report(self) -> dict:
        return self.validator.tracker.report()
