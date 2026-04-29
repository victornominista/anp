"""
ANP-Wire Frame
==============
Estructura binaria de cada mensaje entre agentes.

Layout (9 bytes header + N bytes payload):
  Offset  Bytes  Tipo      Campo
  ──────────────────────────────────────────
  0       1      uint8     opcode
  1       2      uint16    tx_id      (big-endian)
  3       2      uint16    agent_id   (big-endian)
  5       4      uint32    payload_len (big-endian)
  9       N      bytes     payload

Frame mínimo: 9 bytes (ACK sin payload = 9 + 0 = 9 bytes)
Frame típico BID: ~40 bytes
Equivalente JSON: ~400 bytes  →  ratio 10:1
"""
import struct
from dataclasses import dataclass, field
from typing import Optional

from .opcodes import Op, OP_NAME

# Formato del header: big-endian, sin padding
# ! = big-endian  B = uint8  H = uint16  I = uint32
HEADER_FMT    = "!BHHI"
HEADER_SIZE   = struct.calcsize(HEADER_FMT)  # = 9 bytes
MAX_PAYLOAD   = 65_535                        # límite razonable por frame


@dataclass
class Frame:
    op:         Op
    tx_id:      int        # uint16: ID de transacción (compartido por toda la sesión)
    agent_id:   int        # uint16: quién envía
    payload:    bytes = field(default=b"")

    # ── encoding ──────────────────────────────────────────────────────────────

    def encode(self) -> bytes:
        """Serializa el frame a bytes ANP-Wire."""
        if len(self.payload) > MAX_PAYLOAD:
            raise ValueError(f"Payload {len(self.payload)} > MAX {MAX_PAYLOAD}")
        header = struct.pack(
            HEADER_FMT,
            int(self.op),
            self.tx_id,
            self.agent_id,
            len(self.payload),
        )
        return header + self.payload

    # ── decoding ──────────────────────────────────────────────────────────────

    @classmethod
    def decode(cls, data: bytes) -> "Frame":
        """Deserializa bytes ANP-Wire a Frame. Lanza ValueError si está corrupto."""
        if len(data) < HEADER_SIZE:
            raise ValueError(f"Frame demasiado corto: {len(data)} bytes (mínimo {HEADER_SIZE})")

        op_byte, tx_id, agent_id, payload_len = struct.unpack_from(HEADER_FMT, data, 0)

        try:
            op = Op(op_byte)
        except ValueError:
            raise ValueError(f"Opcode desconocido: 0x{op_byte:02X}")

        expected_total = HEADER_SIZE + payload_len
        if len(data) < expected_total:
            raise ValueError(
                f"Payload incompleto: se esperaban {payload_len} bytes, "
                f"llegaron {len(data) - HEADER_SIZE}"
            )

        payload = data[HEADER_SIZE: expected_total]
        return cls(op=op, tx_id=tx_id, agent_id=agent_id, payload=payload)

    # ── helpers ───────────────────────────────────────────────────────────────

    @property
    def size(self) -> int:
        return HEADER_SIZE + len(self.payload)

    def __repr__(self) -> str:
        hex_header = self.encode()[:HEADER_SIZE].hex(" ")
        return (
            f"Frame({OP_NAME[self.op]:<8} "
            f"tx={self.tx_id:04X} "
            f"agent={self.agent_id:04X} "
            f"payload={len(self.payload)}B | "
            f"wire: {hex_header})"
        )
