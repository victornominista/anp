"""
ANP · Wrappers · Base
=====================
Lógica compartida que todos los wrappers heredan.

El patrón es siempre el mismo:
  1. LLM recibe un "manual" en su system prompt que describe las funciones ANP
  2. LLM genera una llamada estructurada (function call / tool use)
  3. El wrapper traduce esa llamada a frames ANP-Wire
  4. El motor de negociación ejecuta todo en binario (sin más tokens LLM)
  5. El resultado vuelve al LLM como texto limpio

El LLM solo consume tokens en el paso 1 y 5.
Los pasos 2-4 son lógica pura, sin costo de tokens.
"""
from dataclasses import dataclass
from typing import Optional
import time
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from anp.negotiation import (
    NegotiationEngine, BuyerAgent, SellerAgent,
    BuyerLinear, BuyerPatient, BuyerAggressive,
    SellerLinear, SellerDeadline,
)
from anp.oracle import Oracle
from anp.passport import PassportSigner, PassportValidator


# ── Resultado unificado que todos los wrappers devuelven al LLM ───────────────

@dataclass
class ANPResult:
    success:       bool
    final_price:   Optional[float]
    item:          str
    state:         str
    rounds:        int
    bytes_wire:    int
    elapsed_ms:    float
    message:       str
    oracle_status: str = "OK"
    savings_usd:   float = 0.0

    def to_llm_text(self) -> str:
        """Texto limpio que el LLM recibe como resultado de la negociación."""
        if self.success:
            return (
                f"Negociación exitosa. "
                f"Item: {self.item}. "
                f"Precio final: ${self.final_price:.4f}. "
                f"Rondas: {self.rounds}. "
                f"Bytes ANP-Wire: {self.bytes_wire} "
                f"(equivalente JSON: ~{self.bytes_wire * 11} bytes). "
                f"Tiempo: {self.elapsed_ms:.1f}ms."
            )
        return (
            f"Negociación sin acuerdo. "
            f"Estado: {self.state}. "
            f"Motivo: {self.message}."
            + (f" Ahorro del oráculo: ${self.savings_usd:.4f}." if self.savings_usd else "")
        )

    def to_dict(self) -> dict:
        return {
            "success": self.success,
            "final_price": self.final_price,
            "item": self.item,
            "state": self.state,
            "rounds": self.rounds,
            "bytes_wire": self.bytes_wire,
            "elapsed_ms": round(self.elapsed_ms, 2),
            "message": self.message,
            "oracle_status": self.oracle_status,
            "savings_usd": self.savings_usd,
        }


# ── Motor compartido ──────────────────────────────────────────────────────────

class ANPBaseWrapper:
    """
    Motor de negociación reutilizable.
    Todos los wrappers de LLM lo usan internamente.
    """

    BUYER_STRATEGIES = {
        "linear":     BuyerLinear,
        "patient":    lambda: BuyerPatient(patience=3),
        "aggressive": BuyerAggressive,
    }
    SELLER_STRATEGIES = {
        "linear":   SellerLinear,
        "deadline": SellerDeadline,
    }

    def __init__(
        self,
        oracle: Optional[Oracle] = None,
        passport_token: Optional[str] = None,
        passport_validator: Optional[PassportValidator] = None,
    ):
        self.oracle = oracle
        self.passport_token = passport_token
        self.passport_validator = passport_validator

    def negotiate(
        self,
        item: str,
        max_price: float,
        seller_start: float,
        seller_min: float,
        qty: int = 1,
        buyer_strategy: str = "linear",
        seller_strategy: str = "linear",
        validate_oracle: bool = True,
    ) -> ANPResult:
        """Ejecuta la negociación. Este es el método que llaman todos los wrappers."""

        # ── Oracle check ──────────────────────────────────────────────────────
        if validate_oracle and self.oracle:
            val = self.oracle.check_buy(item, max_price, qty)
            if val.blocked:
                return ANPResult(
                    success=False, final_price=None, item=item,
                    state="ORACLE_BLOCKED", rounds=0, bytes_wire=0,
                    elapsed_ms=0, message=val.reason,
                    oracle_status=val.status.value,
                    savings_usd=val.savings_usd,
                )

        # ── Passport check ────────────────────────────────────────────────────
        if self.passport_token and self.passport_validator:
            perm = self.passport_validator.check(
                self.passport_token, item=item, price=max_price, qty=qty,
            )
            if not perm.granted:
                return ANPResult(
                    success=False, final_price=None, item=item,
                    state="PASSPORT_DENIED", rounds=0, bytes_wire=0,
                    elapsed_ms=0, message=perm.reason,
                )

        # ── Build agents ──────────────────────────────────────────────────────
        b_strat = self.BUYER_STRATEGIES.get(buyer_strategy, BuyerLinear)
        s_strat = self.SELLER_STRATEGIES.get(seller_strategy, SellerLinear)

        buyer  = BuyerAgent(0x0001, max_price=max_price,
                            strategy=b_strat() if callable(b_strat) else b_strat)
        seller = SellerAgent(0x0002, start_price=seller_start,
                             min_price=seller_min,
                             strategy=s_strat() if callable(s_strat) else s_strat)

        # ── Run engine ────────────────────────────────────────────────────────
        engine = NegotiationEngine(buyer, seller)
        result = engine.run(
            item=item,
            deadline=int(time.time()) + 60,
            qty=qty,
        )

        return ANPResult(
            success=result.success,
            final_price=result.final_price,
            item=item,
            state=result.state.value,
            rounds=result.rounds,
            bytes_wire=result.bytes_total,
            elapsed_ms=result.elapsed_ms,
            message=(
                f"Trato cerrado a ${result.final_price:.4f}"
                if result.success
                else f"Sin acuerdo: {result.state.value}"
            ),
        )


# ── System prompt compartido ──────────────────────────────────────────────────

ANP_SYSTEM_PROMPT = """Tienes acceso al protocolo ANP (Agent Negotiation Protocol).
Cuando necesites comprar o negociar el precio de un servicio, usa la función `anp_negotiate`.

NO escribas texto de negociación. NO simules una conversación de precios.
Solo llama a la función con los parámetros correctos y recibirás el resultado.

La función ejecuta miles de micro-negociaciones en milisegundos usando un protocolo
binario entre agentes, sin consumir tokens adicionales.

Parámetros clave:
- item: identificador del servicio (ej: "api_access_basic", "hosting_shared_monthly")
- max_price: lo máximo que pagarías en USD (mantén esto razonable)
- seller_start: precio inicial del vendedor (si lo conoces)
- seller_min: precio mínimo del vendedor (si lo conoces, sino estima)
"""
