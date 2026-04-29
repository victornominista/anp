"""
ANP · Seller Agent
==================
El agente vendedor. Conoce su min_price pero nunca lo revela en wire.
Recibe BID o COUNTER, responde con OFFER, COUNTER o REJECT.
"""
from ..wire import (
    Op, Frame, Codec,
    OfferPayload, AcceptPayload, RejectPayload,
)
from .session import NegotiationSession, SessionState
from .rules import SellerStrategy, DEFAULT_SELLER_STRATEGY


class SellerAgent:
    def __init__(
        self,
        agent_id: int,
        start_price: float,
        min_price: float,
        stock: int = 999,
        strategy: SellerStrategy = DEFAULT_SELLER_STRATEGY,
    ):
        self.agent_id = agent_id
        self.start_price = start_price   # precio inicial público
        self.min_price = min_price       # SECRETO — nunca va al wire
        self.stock = stock
        self.strategy = strategy

    def respond_to_bid(self, bid_frame: Frame, session: NegotiationSession) -> Frame:
        """Recibe el BID inicial, devuelve primera OFFER."""
        session.seller_min = self.min_price
        session.state = SessionState.NEGOTIATING

        offer_price = self.strategy.next_offer(
            last_counter=None,
            min_price=self.min_price,
            start_price=self.start_price,
            round_n=0,
        )
        session.last_offer = offer_price

        payload = Codec.encode_offer(OfferPayload(
            item=session.item,
            price=offer_price,
            tx_ref=session.tx_id,
            stock=self.stock,
        ))
        frame = Frame(op=Op.OFFER, tx_id=session.tx_id, agent_id=self.agent_id, payload=payload)
        session.bytes_sent += frame.size
        return frame

    def respond_to_counter(self, counter_frame: Frame, session: NegotiationSession) -> Frame:
        """Recibe COUNTER del comprador, devuelve OFFER ajustada o REJECT."""
        if session.is_expired():
            session.state = SessionState.EXPIRED
            payload = Codec.encode_reject(RejectPayload(tx_ref=session.tx_id))
            return Frame(op=Op.REJECT, tx_id=session.tx_id, agent_id=self.agent_id, payload=payload)

        decoded = Codec.decode_payload(counter_frame)
        counter_price = decoded["price"]

        # ¿Rechazo definitivo?
        if self.strategy.should_reject(counter_price, self.min_price):
            session.state = SessionState.REJECTED
            payload = Codec.encode_reject(RejectPayload(tx_ref=session.tx_id))
            frame = Frame(op=Op.REJECT, tx_id=session.tx_id, agent_id=self.agent_id, payload=payload)
            session.bytes_sent += frame.size
            return frame

        # Nueva oferta bajando hacia el mínimo
        offer_price = self.strategy.next_offer(
            last_counter=counter_price,
            min_price=self.min_price,
            start_price=self.start_price,
            round_n=session.round,
        )
        session.last_offer = offer_price

        payload = Codec.encode_offer(OfferPayload(
            item=session.item,
            price=offer_price,
            tx_ref=session.tx_id,
            stock=self.stock,
        ))
        frame = Frame(op=Op.OFFER, tx_id=session.tx_id, agent_id=self.agent_id, payload=payload)
        session.bytes_sent += frame.size
        return frame
