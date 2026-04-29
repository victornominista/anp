"""
ANP · Auction · Session
=======================
Estado de una subasta inversa: 1 comprador vs N vendedores.
"""
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class AuctionMode(Enum):
    LOWEST_PRICE   = "lowest_price"
    FIRST_TO_MATCH = "first_to_match"
    VICKREY        = "vickrey"


class AuctionState(Enum):
    OPEN       = "OPEN"
    CLOSED     = "CLOSED"
    NO_DEAL    = "NO_DEAL"
    CANCELLED  = "CANCELLED"


@dataclass
class SellerStatus:
    seller_id:    int
    label:        str
    current_offer: Optional[float] = None
    rounds:       int = 0
    active:       bool = True
    eliminated_at: Optional[float] = None
    elimination_reason: str = ""


@dataclass
class AuctionSession:
    tx_id:        int
    item:         str
    mode:         AuctionMode
    max_rounds:   int = 8
    ttl:          int = 60
    created_at:   float = field(default_factory=time.time)

    state:        AuctionState = AuctionState.OPEN
    round:        int = 0

    sellers:      dict = field(default_factory=dict)

    winner_id:    Optional[int] = None
    winning_price: Optional[float] = None
    second_price:  Optional[float] = None
    buyer_max:    Optional[float] = None

    # Ambos nombres apuntan al mismo contador — compatibilidad con Buyer/SellerAgent
    bytes_sent:   int = 0
    bytes_total:  int = 0

    best_offer_history: list = field(default_factory=list)

    def register_seller(self, seller_id: int, label: str):
        self.sellers[seller_id] = SellerStatus(seller_id=seller_id, label=label)

    def active_sellers(self):
        return [s for s in self.sellers.values() if s.active]

    def best_current_offer(self):
        offers = [s.current_offer for s in self.active_sellers() if s.current_offer is not None]
        return min(offers) if offers else None

    def second_best_offer(self):
        offers = sorted([s.current_offer for s in self.active_sellers() if s.current_offer is not None])
        return offers[1] if len(offers) >= 2 else None

    def eliminate_seller(self, seller_id: int, reason: str = ""):
        if seller_id in self.sellers:
            self.sellers[seller_id].active = False
            self.sellers[seller_id].eliminated_at = time.time()
            self.sellers[seller_id].elimination_reason = reason

    def is_expired(self) -> bool:
        return time.time() - self.created_at > self.ttl

    def advance_round(self):
        self.round += 1
        # Sync bytes_sent → bytes_total
        self.bytes_total = self.bytes_sent
        best = self.best_current_offer()
        if best is not None:
            self.best_offer_history.append(best)
