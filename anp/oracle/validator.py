"""
ANP · Oracle · Validator
========================
Protección contra sobreprecios para agentes compradores.

Tres capas de protección:
  1. HARD CEILING  — bloqueo absoluto, nunca se puede anular
  2. SOFT TOLERANCE — alerta + requiere confirmación humana (default ±20%)
  3. SAVINGS TRACKING — mide en USD cuánto ahorró el oráculo

Integración x402/MPP:
  El campo `x402_payment_required` en ValidationResult indica si la
  transacción debe pasar por un canal de micropago x402 antes de ejecutarse.
"""
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from .price_feed import PriceFeed, PriceEntry


class ValidationStatus(Enum):
    OK              = "OK"               # oferta dentro de rango normal
    WARN            = "WARN"             # desviación alta, pero dentro de tolerancia
    BLOCKED_CEILING = "BLOCKED_CEILING"  # HARD: supera ceiling absoluto
    BLOCKED_FLOOR   = "BLOCKED_FLOOR"    # HARD: bajo floor absoluto (dumping)
    NEEDS_HUMAN     = "NEEDS_HUMAN"      # desviación > tolerance, espera confirmación
    UNKNOWN_ITEM    = "UNKNOWN_ITEM"     # item no está en el feed de precios


@dataclass
class ValidationResult:
    status:       ValidationStatus
    item:         str
    offered:      float               # precio que el agente quiere pagar/cobrar
    base_price:   Optional[float]     # precio de mercado de referencia
    deviation:    Optional[float]     # 0.0 = igual al mercado, 1.0 = 100% diferente
    deviation_pct: Optional[float]    # en porcentaje legible
    blocked:      bool                # True = la transacción no debe ejecutarse

    # Protección de sobreprecio
    overprice_usd:   float = 0.0      # cuánto USD de sobreprecio se detectó
    savings_usd:     float = 0.0      # cuánto USD ahorró el oráculo al bloquear

    # Integración x402/MPP
    x402_required:   bool = False     # si True, pagar vía canal x402 antes de ejecutar
    x402_endpoint:   Optional[str] = None

    # Para logging
    reason:          str = ""

    @property
    def is_ok(self) -> bool:
        return not self.blocked

    def summary(self) -> str:
        if self.status == ValidationStatus.OK:
            return f"✓ OK  ${self.offered:.4f}  (mercado=${self.base_price:.4f}, dev={self.deviation_pct:.1f}%)"
        if self.status == ValidationStatus.BLOCKED_CEILING:
            return f"✗ BLOQUEADO (sobreprecio)  ${self.offered:.4f} > ceiling ${self.base_price:.4f}  ahorró=${self.savings_usd:.4f}"
        if self.status == ValidationStatus.NEEDS_HUMAN:
            return f"⚠ REQUIERE HUMANO  ${self.offered:.4f}  desviación={self.deviation_pct:.1f}%"
        if self.status == ValidationStatus.UNKNOWN_ITEM:
            return f"? ITEM DESCONOCIDO  '{self.item}'  — no se puede validar"
        return f"{self.status.value}  ${self.offered:.4f}"


# ── Savings Tracker ───────────────────────────────────────────────────────────

@dataclass
class SavingsTracker:
    """
    Lleva la cuenta de cuánto dinero ahorró el oráculo.
    Este número es el "valor medible $" del sistema.
    """
    total_validated:   int   = 0
    total_blocked:     int   = 0
    total_warned:      int   = 0
    total_savings_usd: float = 0.0    # USD ahorrados por bloqueos
    total_overprice_detected: float = 0.0

    def record(self, result: ValidationResult):
        self.total_validated += 1
        if result.blocked:
            self.total_blocked += 1
            self.total_savings_usd += result.savings_usd
            self.total_overprice_detected += result.overprice_usd
        elif result.status == ValidationStatus.WARN:
            self.total_warned += 1

    def report(self) -> dict:
        block_rate = (self.total_blocked / self.total_validated * 100) if self.total_validated else 0
        return {
            "total_validated":      self.total_validated,
            "total_blocked":        self.total_blocked,
            "total_warned":         self.total_warned,
            "block_rate_pct":       round(block_rate, 2),
            "total_savings_usd":    round(self.total_savings_usd, 6),
            "overprice_detected_usd": round(self.total_overprice_detected, 6),
        }

    def summary_line(self) -> str:
        r = self.report()
        return (
            f"Oracle: {r['total_validated']} validadas · "
            f"{r['total_blocked']} bloqueadas ({r['block_rate_pct']:.1f}%) · "
            f"ahorrado=[bold green]${r['total_savings_usd']:.4f} USD[/]"
        )


# ── Validator principal ───────────────────────────────────────────────────────

class OracleValidator:
    """
    Valida ofertas de precio antes de que el agente las acepte o envíe.

    Uso comprador (protección contra sobreprecio):
        result = oracle.validate_buy(item="api_access", offered_price=0.50)
        if result.blocked:
            # NO pagar — el oráculo detectó sobreprecio

    Uso vendedor (protección contra underprice/dumping):
        result = oracle.validate_sell(item="api_access", offered_price=0.001)
        if result.blocked:
            # NO vender — el precio está bajo el floor del mercado
    """

    def __init__(
        self,
        feed: PriceFeed,
        soft_tolerance: float = 0.20,   # ±20% antes de alertar
        warn_tolerance: float = 0.10,   # ±10% antes de warning suave
        x402_endpoint: Optional[str] = None,
        x402_threshold_usd: float = 1.0,  # pagos > $1 pasan por x402
    ):
        self.feed = feed
        self.soft_tolerance = soft_tolerance
        self.warn_tolerance = warn_tolerance
        self.x402_endpoint = x402_endpoint
        self.x402_threshold_usd = x402_threshold_usd
        self.tracker = SavingsTracker()

    def _make_unknown(self, item: str, offered: float) -> ValidationResult:
        r = ValidationResult(
            status=ValidationStatus.UNKNOWN_ITEM,
            item=item, offered=offered,
            base_price=None, deviation=None, deviation_pct=None,
            blocked=False,  # no bloqueamos lo que no conocemos — solo avisamos
            reason=f"Item '{item}' no está en el price feed. Considerar bloquearlo por precaución.",
        )
        self.tracker.record(r)
        return r

    def validate_buy(
        self,
        item: str,
        offered_price: float,
        qty: int = 1,
    ) -> ValidationResult:
        """
        Valida un precio que el agente COMPRADOR está considerando pagar.
        Protege contra sobreprecios y alucinaciones numéricas del LLM.
        """
        entry = self.feed.get(item)
        if entry is None:
            return self._make_unknown(item, offered_price)

        base = entry.price
        total_offered = offered_price * qty
        deviation = abs(offered_price - base) / base
        deviation_pct = deviation * 100

        # ── HARD CEILING ──────────────────────────────────────────────────────
        ceiling = entry.ceiling or base * 3.0  # default: 3x el precio base
        if offered_price > ceiling:
            overprice = (offered_price - ceiling) * qty
            savings = overprice
            r = ValidationResult(
                status=ValidationStatus.BLOCKED_CEILING,
                item=item, offered=offered_price, base_price=ceiling,
                deviation=deviation, deviation_pct=deviation_pct,
                blocked=True,
                overprice_usd=overprice,
                savings_usd=savings,
                x402_required=False,
                reason=(
                    f"Sobreprecio detectado: ${offered_price:.4f} > ceiling ${ceiling:.4f}. "
                    f"Ahorro potencial: ${savings:.4f} USD."
                ),
            )
            self.tracker.record(r)
            return r

        # ── SOFT TOLERANCE (NEEDS_HUMAN) ──────────────────────────────────────
        if deviation > self.soft_tolerance:
            overprice = max(0.0, offered_price - base) * qty
            r = ValidationResult(
                status=ValidationStatus.NEEDS_HUMAN,
                item=item, offered=offered_price, base_price=base,
                deviation=deviation, deviation_pct=deviation_pct,
                blocked=True,   # bloqueamos hasta confirmación humana
                overprice_usd=overprice,
                savings_usd=overprice,
                x402_required=total_offered >= self.x402_threshold_usd,
                x402_endpoint=self.x402_endpoint if total_offered >= self.x402_threshold_usd else None,
                reason=(
                    f"Desviación del {deviation_pct:.1f}% sobre precio de mercado ${base:.4f}. "
                    f"Requiere confirmación humana antes de ejecutar."
                ),
            )
            self.tracker.record(r)
            return r

        # ── WARN suave ────────────────────────────────────────────────────────
        if deviation > self.warn_tolerance:
            r = ValidationResult(
                status=ValidationStatus.WARN,
                item=item, offered=offered_price, base_price=base,
                deviation=deviation, deviation_pct=deviation_pct,
                blocked=False,
                overprice_usd=max(0.0, offered_price - base) * qty,
                savings_usd=0.0,
                x402_required=total_offered >= self.x402_threshold_usd,
                x402_endpoint=self.x402_endpoint if total_offered >= self.x402_threshold_usd else None,
                reason=f"Precio ligeramente elevado ({deviation_pct:.1f}% sobre mercado). Procede con cautela.",
            )
            self.tracker.record(r)
            return r

        # ── OK ────────────────────────────────────────────────────────────────
        r = ValidationResult(
            status=ValidationStatus.OK,
            item=item, offered=offered_price, base_price=base,
            deviation=deviation, deviation_pct=deviation_pct,
            blocked=False,
            x402_required=total_offered >= self.x402_threshold_usd,
            x402_endpoint=self.x402_endpoint if total_offered >= self.x402_threshold_usd else None,
            reason="Precio dentro de rango de mercado.",
        )
        self.tracker.record(r)
        return r

    def validate_sell(
        self,
        item: str,
        offered_price: float,
        qty: int = 1,
    ) -> ValidationResult:
        """
        Valida un precio que el agente VENDEDOR está considerando cobrar.
        Protege contra dumping (vender muy barato por error del LLM).
        """
        entry = self.feed.get(item)
        if entry is None:
            return self._make_unknown(item, offered_price)

        base = entry.price
        floor = entry.floor or base * 0.3

        if offered_price < floor:
            loss = (floor - offered_price) * qty
            r = ValidationResult(
                status=ValidationStatus.BLOCKED_FLOOR,
                item=item, offered=offered_price, base_price=floor,
                deviation=abs(offered_price - base) / base,
                deviation_pct=abs(offered_price - base) / base * 100,
                blocked=True,
                savings_usd=loss,
                reason=(
                    f"Precio bajo floor de protección: ${offered_price:.4f} < floor ${floor:.4f}. "
                    f"Pérdida evitada: ${loss:.4f} USD."
                ),
            )
            self.tracker.record(r)
            return r

        # Reutiliza validate_buy con lógica invertida para el resto
        return self.validate_buy(item, offered_price, qty)
