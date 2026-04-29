"""
ANP · Auction Engine
====================
Motor de subasta inversa: 1 comprador vs N vendedores simultáneos.

Por qué "inversa": el comprador define un precio máximo y los vendedores
BAJAN sus precios compitiendo entre sí. El comprador nunca sube.

Anti-explotación:
  Las estrategias de negociación predecibles (BuyerLinear) pueden ser
  explotadas por vendedores sofisticados que detectan el patrón.
  Solución: ruido aleatorio calibrado en los pasos de precio.
  El vendedor ve variación, no puede inferir el algoritmo exacto.

Modos de subasta:
  LOWEST_PRICE   — al final de las rondas, gana el precio más bajo
  FIRST_TO_MATCH — en cuanto un vendedor llega al max_price, cierra
  VICKREY        — gana el más barato pero paga el segundo precio
                   (incentiva honestidad: no conviene dumping extremo)
"""
import random
import time
from dataclasses import dataclass, field
from typing import Optional, Callable

from ..wire import Op, Frame, Codec, OfferPayload, AcceptPayload, RejectPayload
from .auction_session import AuctionSession, AuctionState, AuctionMode, SellerStatus
from .buyer import BuyerAgent
from .seller import SellerAgent
from .rules import BuyerStrategy, SellerStrategy, DEFAULT_BUYER_STRATEGY, DEFAULT_SELLER_STRATEGY


# ── Resultado de subasta ──────────────────────────────────────────────────────

@dataclass
class AuctionResult:
    success:        bool
    mode:           AuctionMode
    item:           str
    winner_id:      Optional[int]
    winner_label:   Optional[str]
    winning_price:  Optional[float]
    payment_price:  Optional[float]     # puede diferir en Vickrey
    savings_vs_start: Optional[float]   # cuánto bajó el precio respecto al inicio
    rounds:         int
    sellers_count:  int
    sellers_active_end: int             # cuántos quedaron activos al final
    bytes_total:    int
    elapsed_ms:     float
    price_history:  list[float]         # mejor precio por ronda
    seller_results: list[dict]          # detalle por vendedor

    @property
    def json_equiv_bytes(self) -> int:
        return self.bytes_total * 11

    def summary(self) -> str:
        if not self.success:
            return f"No deal after {self.rounds} rounds. Best offer: {self._best_offer()}"
        vickrey_note = ""
        if self.mode == AuctionMode.VICKREY and self.payment_price != self.winning_price:
            vickrey_note = f" (Vickrey: pays ${self.payment_price:.4f})"
        return (
            f"Winner: seller_{self.winner_id} at ${self.winning_price:.4f}{vickrey_note}. "
            f"{self.rounds} rounds, {self.sellers_count} sellers, "
            f"{self.bytes_total}B wire."
        )

    def _best_offer(self) -> str:
        offers = [r["final_offer"] for r in self.seller_results if r["final_offer"]]
        return f"${min(offers):.4f}" if offers else "none"


# ── Motor principal ───────────────────────────────────────────────────────────

class AuctionEngine:
    """
    Subasta inversa ANP: 1 comprador vs N vendedores.

    Uso:
        buyer   = BuyerAgent(0x0001, max_price=0.08)
        sellers = [
            SellerAgent(0x0010, start_price=0.12, min_price=0.06, label="Seller A"),
            SellerAgent(0x0011, start_price=0.10, min_price=0.07, label="Seller B"),
            SellerAgent(0x0012, start_price=0.11, min_price=0.05, label="Seller C"),
        ]
        engine = AuctionEngine(buyer, sellers, mode=AuctionMode.LOWEST_PRICE)
        result = engine.run(item="api_access_basic")
    """

    # Ruido anti-explotación: ±X% sobre el paso calculado
    NOISE_PCT = 0.08

    def __init__(
        self,
        buyer: BuyerAgent,
        sellers: list[SellerAgent],
        mode: AuctionMode = AuctionMode.LOWEST_PRICE,
        noise: bool = True,             # activar ruido anti-explotación
        on_frame: Optional[Callable] = None,
    ):
        if len(sellers) < 2:
            raise ValueError("Una subasta necesita al menos 2 vendedores")

        self.buyer   = buyer
        self.sellers = sellers
        self.mode    = mode
        self.noise   = noise
        self.on_frame = on_frame

        # Asignar labels si no tienen
        for i, s in enumerate(self.sellers):
            if not hasattr(s, 'label') or not s.label:
                s.label = f"Seller_{s.agent_id:04X}"

    def _add_noise(self, price: float) -> float:
        """Añade ruido calibrado para que el patrón de negociación no sea predecible."""
        if not self.noise:
            return price
        noise_factor = 1 + random.uniform(-self.NOISE_PCT, self.NOISE_PCT)
        return round(price * noise_factor, 4)

    def _emit(self, direction: str, frame: Frame, label: str, session: AuctionSession):
        session.bytes_total += frame.size
        if self.on_frame:
            self.on_frame(direction, frame, label)

    def run(
        self,
        item: str,
        deadline: Optional[int] = None,
        tx_id: int = 0x2000,
    ) -> AuctionResult:

        if deadline is None:
            deadline = int(time.time()) + 60

        session = AuctionSession(
            tx_id=tx_id,
            item=item,
            mode=self.mode,
        )
        session.buyer_max = self.buyer.max_price

        for s in self.sellers:
            session.register_seller(s.agent_id, getattr(s, 'label', str(s.agent_id)))

        t0 = time.time()

        # ── Ronda 0: BID del comprador → todos los vendedores ─────────────────
        bid_frame = self.buyer.make_bid(session, deadline=deadline)
        self._emit("→", bid_frame, f"[BROADCAST] BID  {item}  max=SECRET", session)

        # ── Loop de rondas ────────────────────────────────────────────────────
        winner_id    = None
        winning_price = None

        for round_n in range(session.max_rounds):
            session.advance_round()
            active = session.active_sellers()
            if not active:
                break

            round_offers: dict[int, float] = {}

            # Cada vendedor activo genera su oferta
            for seller_status in active:
                seller = next(s for s in self.sellers if s.agent_id == seller_status.seller_id)

                # Precio base de la estrategia
                if round_n == 0:
                    raw_price = seller.strategy.next_offer(
                        last_counter=None,
                        min_price=seller.min_price,
                        start_price=seller.start_price,
                        round_n=0,
                    )
                else:
                    # El vendedor ve la mejor oferta actual de la competencia
                    best_competitor = min(
                        (o for sid, o in round_offers.items() if sid != seller.agent_id),
                        default=seller_status.current_offer or seller.start_price,
                    )
                    raw_price = seller.strategy.next_offer(
                        last_counter=best_competitor,
                        min_price=seller.min_price,
                        start_price=seller.start_price,
                        round_n=round_n,
                    )

                # Aplicar ruido anti-explotación
                noisy_price = self._add_noise(raw_price)
                # Nunca bajo el mínimo del vendedor
                final_price = max(noisy_price, seller.min_price)
                seller_status.current_offer = final_price
                seller_status.rounds += 1
                round_offers[seller.agent_id] = final_price

                # Emitir frame OFFER
                payload = Codec.encode_offer(OfferPayload(
                    item=item, price=final_price,
                    tx_ref=tx_id, stock=999,
                ))
                frame = Frame(op=Op.OFFER, tx_id=tx_id,
                              agent_id=seller.agent_id, payload=payload)
                self._emit(
                    "←", frame,
                    f"[{getattr(seller, 'label', seller.agent_id)}]  OFFER  ${final_price:.4f}",
                    session,
                )

            # ── Evaluar ronda ─────────────────────────────────────────────────
            best_price = session.best_current_offer()

            # FIRST_TO_MATCH: ¿algún vendedor llegó al max_price?
            if self.mode == AuctionMode.FIRST_TO_MATCH:
                matched = [
                    (sid, offer) for sid, offer in round_offers.items()
                    if offer <= self.buyer.max_price
                ]
                if matched:
                    # Gana el de menor precio (tie-break: primero en la lista)
                    winner_id, winning_price = min(matched, key=lambda x: x[1])
                    break

            # LOWEST_PRICE / VICKREY: eliminar vendedores que no pueden competir
            if best_price is not None:
                for seller_status in active:
                    s = next(s for s in self.sellers if s.agent_id == seller_status.seller_id)
                    # Si el mínimo del vendedor ya es mayor al mejor precio actual
                    if s.min_price > best_price * 1.05:  # 5% de tolerancia
                        session.eliminate_seller(
                            seller_status.seller_id,
                            f"min_price ${s.min_price:.4f} > best ${best_price:.4f}",
                        )
                        frame = Frame(op=Op.REJECT, tx_id=tx_id,
                                      agent_id=seller_status.seller_id,
                                      payload=Codec.encode_reject(
                                          __import__('anp.wire', fromlist=['RejectPayload']).RejectPayload(tx_ref=tx_id)
                                          if False else type('R', (), {'tx_ref': tx_id})()
                                      ))

            # ¿Quedan vendedores activos?
            if len(session.active_sellers()) == 0:
                break

        # ── Determinar ganador ────────────────────────────────────────────────
        active_final = session.active_sellers()

        if self.mode in (AuctionMode.LOWEST_PRICE, AuctionMode.VICKREY):
            # Gana el precio más bajo entre los activos
            candidates = [
                (s.seller_id, s.current_offer)
                for s in active_final
                if s.current_offer is not None
            ]
            if candidates:
                winner_id, winning_price = min(candidates, key=lambda x: x[1])
                if winning_price <= self.buyer.max_price:
                    session.winner_id = winner_id
                    session.winning_price = winning_price
                    if self.mode == AuctionMode.VICKREY:
                        session.second_price = session.second_best_offer() or winning_price
                else:
                    winner_id = None  # ninguno llegó al precio del comprador

        elif self.mode == AuctionMode.FIRST_TO_MATCH and winner_id:
            session.winner_id = winner_id
            session.winning_price = winning_price

        # ── Frame ACCEPT o REJECT ─────────────────────────────────────────────
        success = winner_id is not None and winning_price is not None

        if success:
            from ..wire import AcceptPayload as AP
            payload = Codec.encode_accept(AP(tx_ref=tx_id))
            frame = Frame(op=Op.ACCEPT, tx_id=tx_id,
                          agent_id=self.buyer.agent_id, payload=payload)
            winner_label = session.sellers[winner_id].label
            payment = session.second_price if self.mode == AuctionMode.VICKREY else winning_price
            self._emit("→", frame, f"ACCEPT  {winner_label}  ${winning_price:.4f}"
                       + (f"  [Vickrey pays ${payment:.4f}]" if self.mode == AuctionMode.VICKREY else ""),
                       session)
            session.state = AuctionState.CLOSED
        else:
            session.state = AuctionState.NO_DEAL

        elapsed_ms = (time.time() - t0) * 1000

        # ── Construir resultado detallado ─────────────────────────────────────
        start_prices = [s.start_price for s in self.sellers]
        avg_start = sum(start_prices) / len(start_prices)
        savings = round(avg_start - winning_price, 4) if winning_price else None

        seller_results = [
            {
                "seller_id":    s.seller_id,
                "label":        session.sellers[s.seller_id].label,
                "start_price":  next(x.start_price for x in self.sellers if x.agent_id == s.seller_id),
                "min_price":    next(x.min_price   for x in self.sellers if x.agent_id == s.seller_id),
                "final_offer":  s.current_offer,
                "rounds":       s.rounds,
                "active":       s.active,
                "won":          s.seller_id == winner_id,
                "eliminated_reason": s.elimination_reason,
            }
            for s in session.sellers.values()
        ]

        return AuctionResult(
            success=success,
            mode=self.mode,
            item=item,
            winner_id=winner_id,
            winner_label=session.sellers[winner_id].label if winner_id and winner_id in session.sellers else None,
            winning_price=winning_price,
            payment_price=session.second_price if self.mode == AuctionMode.VICKREY else winning_price,
            savings_vs_start=savings,
            rounds=session.round,
            sellers_count=len(self.sellers),
            sellers_active_end=len(session.active_sellers()),
            bytes_total=session.bytes_total,
            elapsed_ms=elapsed_ms,
            price_history=session.best_offer_history,
            seller_results=seller_results,
        )
