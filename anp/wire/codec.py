"""
ANP-Wire Codec
==============
Encode/decode de los payloads por opcode.
Usa struct binario para máxima velocidad y mínimo tamaño.

Precios: int32 big-endian representando centavos (x100).
  $0.07 → 7   $10.50 → 1050   $0.001 → 0 (mínimo 1 centavo)

item_hash: primeros 4 bytes del hash SHA1 del nombre del item.
  "api_access" → sha1 → primeros 4 bytes → uint32
"""
import hashlib
import struct
from dataclasses import dataclass
from typing import Optional

import msgpack

from .frame import Frame
from .opcodes import Op, ErrCode


# ── Helpers de precio ─────────────────────────────────────────────────────────

def price_to_wire(price_usd: float) -> int:
    """$0.07 → 7 (centavos como int32)"""
    return round(price_usd * 100)

def wire_to_price(cents: int) -> float:
    """7 → $0.07"""
    return cents / 100.0

def item_hash(item: str) -> int:
    """'api_access' → uint32 de 4 bytes (identificador compacto)"""
    digest = hashlib.sha1(item.encode()).digest()
    return struct.unpack("!I", digest[:4])[0]


# ── Payloads tipados ──────────────────────────────────────────────────────────

@dataclass
class BidPayload:
    item: str
    max_price: float    # en USD
    deadline: int       # unix timestamp
    qty: int = 1

@dataclass
class OfferPayload:
    item: str
    price: float
    tx_ref: int         # tx_id de la sesión
    stock: int = 999

@dataclass
class CounterPayload:
    item: str
    price: float
    tx_ref: int

@dataclass
class AcceptPayload:
    tx_ref: int

@dataclass
class RejectPayload:
    tx_ref: int

@dataclass
class ErrPayload:
    code: ErrCode
    tx_ref: int

@dataclass
class QueryPayload:
    item: str

@dataclass
class PricePayload:
    item: str
    price: float
    deviation: float    # 0.0 - 1.0, cuánto se desvía del mercado


# ── Formatos struct por opcode ────────────────────────────────────────────────
# BID:     item_hash(I) + max_price(i) + deadline(I) + qty(H)  = 14 bytes
# OFFER:   item_hash(I) + price(i) + tx_ref(H) + stock(H)      = 12 bytes
# COUNTER: item_hash(I) + price(i) + tx_ref(H)                 = 10 bytes
# ACCEPT:  tx_ref(H)                                            = 2 bytes
# REJECT:  tx_ref(H)                                            = 2 bytes
# ERR:     code(B) + tx_ref(H)                                  = 3 bytes
# QUERY:   item_hash(I)                                         = 4 bytes
# PRICE:   item_hash(I) + price(i) + deviation(h)              = 10 bytes
#          deviation como int16 = deviation*10000 (4 decimales)

FMT = {
    Op.BID:     "!IiIH",
    Op.OFFER:   "!IiHH",
    Op.COUNTER: "!IiH",
    Op.ACCEPT:  "!H",
    Op.REJECT:  "!H",
    Op.ERR:     "!BH",
    Op.QUERY:   "!I",
    Op.PRICE:   "!Iih",
}


# ── Encoder principal ─────────────────────────────────────────────────────────

class Codec:

    # ── encode ─────────────────────────────────────────────────────────────────

    @staticmethod
    def encode_bid(p: BidPayload) -> bytes:
        return struct.pack(FMT[Op.BID],
            item_hash(p.item),
            price_to_wire(p.max_price),
            p.deadline,
            p.qty,
        )

    @staticmethod
    def encode_offer(p: OfferPayload) -> bytes:
        return struct.pack(FMT[Op.OFFER],
            item_hash(p.item),
            price_to_wire(p.price),
            p.tx_ref,
            p.stock,
        )

    @staticmethod
    def encode_counter(p: CounterPayload) -> bytes:
        return struct.pack(FMT[Op.COUNTER],
            item_hash(p.item),
            price_to_wire(p.price),
            p.tx_ref,
        )

    @staticmethod
    def encode_accept(p: AcceptPayload) -> bytes:
        return struct.pack(FMT[Op.ACCEPT], p.tx_ref)

    @staticmethod
    def encode_reject(p: RejectPayload) -> bytes:
        return struct.pack(FMT[Op.REJECT], p.tx_ref)

    @staticmethod
    def encode_err(p: ErrPayload) -> bytes:
        return struct.pack(FMT[Op.ERR], int(p.code), p.tx_ref)

    @staticmethod
    def encode_query(item: str) -> bytes:
        return struct.pack(FMT[Op.QUERY], item_hash(item))

    @staticmethod
    def encode_price(p: PricePayload) -> bytes:
        return struct.pack(FMT[Op.PRICE],
            item_hash(p.item),
            price_to_wire(p.price),
            int(p.deviation * 10000),
        )

    # ── decode ─────────────────────────────────────────────────────────────────

    @staticmethod
    def decode_bid(payload: bytes) -> dict:
        ih, max_price_c, deadline, qty = struct.unpack(FMT[Op.BID], payload)
        return {
            "item_hash": f"{ih:08X}",
            "max_price": wire_to_price(max_price_c),
            "deadline": deadline,
            "qty": qty,
        }

    @staticmethod
    def decode_offer(payload: bytes) -> dict:
        ih, price_c, tx_ref, stock = struct.unpack(FMT[Op.OFFER], payload)
        return {
            "item_hash": f"{ih:08X}",
            "price": wire_to_price(price_c),
            "tx_ref": tx_ref,
            "stock": stock,
        }

    @staticmethod
    def decode_counter(payload: bytes) -> dict:
        ih, price_c, tx_ref = struct.unpack(FMT[Op.COUNTER], payload)
        return {
            "item_hash": f"{ih:08X}",
            "price": wire_to_price(price_c),
            "tx_ref": tx_ref,
        }

    @staticmethod
    def decode_accept(payload: bytes) -> dict:
        (tx_ref,) = struct.unpack(FMT[Op.ACCEPT], payload)
        return {"tx_ref": tx_ref}

    @staticmethod
    def decode_reject(payload: bytes) -> dict:
        (tx_ref,) = struct.unpack(FMT[Op.REJECT], payload)
        return {"tx_ref": tx_ref}

    @staticmethod
    def decode_err(payload: bytes) -> dict:
        code, tx_ref = struct.unpack(FMT[Op.ERR], payload)
        return {"code": ErrCode(code).name, "tx_ref": tx_ref}

    @staticmethod
    def decode_price(payload: bytes) -> dict:
        ih, price_c, dev_i = struct.unpack(FMT[Op.PRICE], payload)
        return {
            "item_hash": f"{ih:08X}",
            "price": wire_to_price(price_c),
            "deviation": dev_i / 10000.0,
        }

    # ── dispatch universal ─────────────────────────────────────────────────────

    DECODERS = {
        Op.BID:     decode_bid.__func__,
        Op.OFFER:   decode_offer.__func__,
        Op.COUNTER: decode_counter.__func__,
        Op.ACCEPT:  decode_accept.__func__,
        Op.REJECT:  decode_reject.__func__,
        Op.ERR:     decode_err.__func__,
        Op.PRICE:   decode_price.__func__,
    }

    @classmethod
    def decode_payload(cls, frame: Frame) -> Optional[dict]:
        """Decodifica el payload de un frame según su opcode. None si no hay payload."""
        decoder = cls.DECODERS.get(frame.op)
        if decoder and frame.payload:
            return decoder(frame.payload)
        return None
