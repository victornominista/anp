"""
ANP · Buyer Agent
=================
El agente comprador. Conoce su max_price pero nunca lo revela en wire.
Recibe frames del vendedor, decide si acepta, rechaza o contraoferta.
"""
from ..wire import (
    Op, Frame, Codec,
    BidPayload, CounterPayload, AcceptPayload, RejectPayload,
)
from .session import NegotiationSession, SessionState
from .rules import BuyerStrategy, DEFAULT_BUYER_STRATEGY


class BuyerAgent:
    def __init__(
        self,
        agent_id: int,
        max_price: float,
        strategy: BuyerStrategy = DEFAULT_BUYER_STRATEGY,
    ):
        self.agent_id = agent_id
        self.max_price = max_price          # SECRETO — nunca va al wire
        self.strategy = strategy

    def make_bid(self, session: NegotiationSession, deadline: int, qty: int = 1) -> Frame:
        """Crea el frame BID inicial."""
        payload = Codec.encode_bid(BidPayload(
            item=session.item,
            max_price=self.max_price,
            deadline=deadline,
            qty=qty,
        ))
        session.buyer_max = self.max_price
        session.state = SessionState.BIDDING
        frame = Frame(op=Op.BID, tx_id=session.tx_id, agent_id=self.agent_id, payload=payload)
        session.bytes_sent += frame.size
        return frame

    def respond_to_offer(self, offer_frame: Frame, session: NegotiationSession) -> Frame:
        """
        Recibe un OFFER del vendedor.
        Devuelve ACCEPT, COUNTER o REJECT.
        """
        if session.is_expired():
            session.state = SessionState.EXPIRED
            payload = Codec.encode_reject(RejectPayload(tx_ref=session.tx_id))
            return Frame(op=Op.REJECT, tx_id=session.tx_id, agent_id=self.agent_id, payload=payload)

        decoded = Codec.decode_payload(offer_frame)
        offer_price = decoded["price"]
        session.last_offer = offer_price
        session.state = SessionState.NEGOTIATING

        # ¿Acepto?
        if self.strategy.should_accept(offer_price, self.max_price):
            session.state = SessionState.ACCEPTED
            session.final_price = offer_price
            payload = Codec.encode_accept(AcceptPayload(tx_ref=session.tx_id))
            frame = Frame(op=Op.ACCEPT, tx_id=session.tx_id, agent_id=self.agent_id, payload=payload)
            session.bytes_sent += frame.size
            return frame

        # ¿Llegué al límite de rondas?
        session.advance_round()
        if session.is_terminal():
            payload = Codec.encode_reject(RejectPayload(tx_ref=session.tx_id))
            frame = Frame(op=Op.REJECT, tx_id=session.tx_id, agent_id=self.agent_id, payload=payload)
            session.bytes_sent += frame.size
            return frame

        # Contraoferta
        counter_price = self.strategy.next_counter(offer_price, self.max_price, session.round)
        session.last_counter = counter_price
        payload = Codec.encode_counter(CounterPayload(
            item=session.item,
            price=counter_price,
            tx_ref=session.tx_id,
        ))
        frame = Frame(op=Op.COUNTER, tx_id=session.tx_id, agent_id=self.agent_id, payload=payload)
        session.bytes_sent += frame.size
        return frame
