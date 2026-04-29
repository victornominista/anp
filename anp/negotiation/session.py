"""
ANP · Session
=============
Estado compartido de una negociación.
El engine crea una sesión, buyer y seller la leen y escriben.
"""
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class SessionState(Enum):
    INIT        = "INIT"
    BIDDING     = "BIDDING"
    NEGOTIATING = "NEGOTIATING"
    ACCEPTED    = "ACCEPTED"
    REJECTED    = "REJECTED"
    CANCELLED   = "CANCELLED"
    EXPIRED     = "EXPIRED"


@dataclass
class NegotiationSession:
    tx_id:       int
    item:        str
    created_at:  float = field(default_factory=time.time)
    ttl:         int   = 30          # segundos máximos por sesión
    max_rounds:  int   = 10

    state:       SessionState = SessionState.INIT
    round:       int          = 0

    # Precios en juego (nunca se revelan entre agentes hasta ACCEPT)
    buyer_max:   Optional[float] = None
    seller_min:  Optional[float] = None

    # Historial de ofertas públicas
    last_offer:  Optional[float] = None
    last_counter: Optional[float] = None
    final_price: Optional[float] = None

    # Bytes totales intercambiados (para métricas)
    bytes_sent:  int = 0

    def is_expired(self) -> bool:
        return time.time() - self.created_at > self.ttl

    def is_terminal(self) -> bool:
        return self.state in {
            SessionState.ACCEPTED,
            SessionState.REJECTED,
            SessionState.CANCELLED,
            SessionState.EXPIRED,
        }

    def advance_round(self):
        self.round += 1
        if self.round >= self.max_rounds:
            self.state = SessionState.EXPIRED
