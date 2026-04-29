"""
ANP · Negotiation Engine
========================
Orquesta buyer y seller a través de una sesión completa.
Es el componente central de M1.

Uso básico:
    engine = NegotiationEngine(buyer, seller)
    result = engine.run(item="api_access", deadline=unix_ts)
    print(result.final_price)
"""
import time
import random
from dataclasses import dataclass, field
from typing import Optional

from ..wire import Op, Frame
from .session import NegotiationSession, SessionState
from .buyer import BuyerAgent
from .seller import SellerAgent


@dataclass
class NegotiationResult:
    success:     bool
    final_price: Optional[float]
    state:       SessionState
    rounds:      int
    bytes_total: int
    elapsed_ms:  float
    frames:      list = field(default_factory=list)

    @property
    def json_equiv_bytes(self) -> int:
        return self.bytes_total * 11

    @property
    def compression_ratio(self) -> str:
        return "10:1"


class NegotiationEngine:
    """
    Motor síncrono de negociación.
    Buyer y seller corren en el mismo proceso (ideal para tests y demos).
    Para uso distribuido: cada agente corre en su propio proceso y
    se comunican por socket/HTTP — el protocolo wire es el mismo.
    """

    def __init__(self, buyer: BuyerAgent, seller: SellerAgent):
        self.buyer = buyer
        self.seller = seller

    def run(
        self,
        item: str,
        deadline: Optional[int] = None,
        qty: int = 1,
        tx_id: Optional[int] = None,
        on_frame=None,           # callback(direction, frame, label) para logging
    ) -> NegotiationResult:
        """
        Ejecuta una negociación completa.
        on_frame: callable opcional que recibe cada frame para logging/display.
        """
        if deadline is None:
            deadline = int(time.time()) + 60
        if tx_id is None:
            tx_id = random.randint(0x1000, 0xFFFF)

        session = NegotiationSession(tx_id=tx_id, item=item)
        frames = []
        t0 = time.time()

        def emit(direction: str, frame: Frame, label: str):
            frames.append((direction, frame, label))
            if on_frame:
                on_frame(direction, frame, label)

        # ── Fase 1: BID ────────────────────────────────────────────────────────
        bid_frame = self.buyer.make_bid(session, deadline=deadline, qty=qty)
        emit("→", bid_frame, f"BID  {item!r}  max=${self.buyer.max_price:.2f}")

        # ── Fase 2: Loop de negociación ────────────────────────────────────────
        # Primero el vendedor responde al BID
        response = self.seller.respond_to_bid(bid_frame, session)
        emit("←", response, f"OFFER  ${session.last_offer:.2f}")

        while not session.is_terminal():
            if response.op == Op.OFFER:
                # Comprador evalúa la oferta
                buyer_response = self.buyer.respond_to_offer(response, session)

                if buyer_response.op == Op.ACCEPT:
                    emit("→", buyer_response, f"ACCEPT  ${session.final_price:.2f}  ✓")
                    break
                elif buyer_response.op == Op.REJECT:
                    emit("→", buyer_response, "REJECT")
                    break
                else:  # COUNTER
                    emit("→", buyer_response, f"COUNTER  ${session.last_counter:.2f}")
                    # Vendedor evalúa la contraoferta
                    response = self.seller.respond_to_counter(buyer_response, session)
                    emit("←", response, f"OFFER  ${session.last_offer:.2f}")

            elif response.op in (Op.REJECT, Op.CANCEL):
                break

        elapsed_ms = (time.time() - t0) * 1000

        return NegotiationResult(
            success=session.state == SessionState.ACCEPTED,
            final_price=session.final_price,
            state=session.state,
            rounds=session.round,
            bytes_total=session.bytes_sent,
            elapsed_ms=elapsed_ms,
            frames=frames,
        )
