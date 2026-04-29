"""
ANP · Identity · Signer / Verifier
===================================
Firma y verifica frames AUTH del protocolo ANP-Wire.

El frame AUTH es lo que un agente envía al inicio de una sesión para
demostrar que es quien dice ser. Contiene:
  - agent_id (quién soy)
  - token ANP-Pass (qué puedo hacer)
  - firma Ed25519 sobre (tx_id + agent_id + token_hash)

El vendedor verifica:
  1. Que la firma corresponde al agent_id declarado
  2. Que el token ANP-Pass es válido (M3)
  3. Que el agent_id del token coincide con el agent_id firmado

Sin los tres, la sesión no inicia.

Formato del mensaje firmado (canónico, determinístico):
  SHA256( "ANP-AUTH-V1" + tx_id(4B BE) + agent_id(utf8) + token_sha256(32B) )
  → 32 bytes que se firman con Ed25519 → 64 bytes de firma
"""
import hashlib
import struct
from dataclasses import dataclass
from typing import Optional

import nacl.signing

from .keypair import AgentKeyPair, VerifyOnlyKey


# Prefijo de dominio — evita reutilizar firmas de otros contextos
AUTH_DOMAIN = b"ANP-AUTH-V1"


def _canonical_message(tx_id: int, agent_id: str, token_str: str) -> bytes:
    """
    Construye el mensaje canónico que se firma.
    Determinístico: mismos inputs → mismo mensaje → misma firma.
    """
    token_hash = hashlib.sha256(token_str.encode()).digest()  # 32 bytes
    tx_bytes   = struct.pack("!I", tx_id & 0xFFFFFFFF)        # 4 bytes big-endian
    agent_bytes = agent_id.encode("utf-8")

    raw = AUTH_DOMAIN + tx_bytes + agent_bytes + token_hash
    # Doble hash (como Bitcoin): SHA256(SHA256(data))
    return hashlib.sha256(hashlib.sha256(raw).digest()).digest()


@dataclass
class AuthPayload:
    """
    Payload del frame AUTH deserializado.
    Va dentro del frame ANP-Wire op=AUTH.

    Wire format:
      agent_id_len(1B) + agent_id(utf8)
      + pubkey(32B)
      + token_len(2B BE) + token(utf8)
      + signature(64B)
    Total típico: 1 + 32 + 32 + 2 + ~400 + 64 = ~531 bytes
    """
    agent_id:  str
    pubkey:    bytes    # 32 bytes clave pública Ed25519
    token_str: str      # ANP-Pass token (base64url)
    signature: bytes    # 64 bytes firma Ed25519

    def encode(self) -> bytes:
        """Serializa a bytes para ir en el payload del frame AUTH."""
        aid_bytes   = self.agent_id.encode("utf-8")
        token_bytes = self.token_str.encode("utf-8")
        return (
            bytes([len(aid_bytes)])          # 1B: longitud agent_id
            + aid_bytes                      # N bytes: agent_id
            + self.pubkey                    # 32B: clave pública
            + struct.pack("!H", len(token_bytes))  # 2B: longitud token
            + token_bytes                    # M bytes: token
            + self.signature                 # 64B: firma
        )

    @classmethod
    def decode(cls, data: bytes) -> "AuthPayload":
        """Deserializa desde bytes del payload de frame AUTH."""
        offset = 0

        aid_len = data[offset]; offset += 1
        agent_id = data[offset:offset+aid_len].decode("utf-8"); offset += aid_len

        pubkey = data[offset:offset+32]; offset += 32

        token_len = struct.unpack_from("!H", data, offset)[0]; offset += 2
        token_str = data[offset:offset+token_len].decode("utf-8"); offset += token_len

        signature = data[offset:offset+64]

        return cls(
            agent_id=agent_id,
            pubkey=pubkey,
            token_str=token_str,
            signature=signature,
        )


class IdentitySigner:
    """
    El agente usa esto para firmar sus frames AUTH.
    Solo el agente que tiene la clave privada puede crear firmas válidas.
    """

    def __init__(self, keypair: AgentKeyPair):
        self.keypair = keypair

    def make_auth_payload(self, tx_id: int, token_str: str) -> AuthPayload:
        """
        Crea el payload AUTH firmado para una sesión de negociación.
        tx_id: el ID de la transacción (del frame ANP-Wire)
        token_str: el ANP-Pass token del agente
        """
        message   = _canonical_message(tx_id, self.keypair.agent_id, token_str)
        signature = self.keypair.sign(message)

        return AuthPayload(
            agent_id=self.keypair.agent_id,
            pubkey=self.keypair.export_public(),
            token_str=token_str,
            signature=signature,
        )


class IdentityVerifier:
    """
    El vendedor (o cualquier nodo) usa esto para verificar frames AUTH.
    No necesita la clave privada del comprador — solo la pública.
    """

    def verify_auth(
        self,
        payload: AuthPayload,
        tx_id: int,
        known_key: Optional[VerifyOnlyKey] = None,
    ) -> tuple[bool, str]:
        """
        Verifica un payload AUTH.

        Si known_key es None, usa la clave pública incluida en el payload
        (modo TOFU — Trust On First Use, como SSH).

        Si known_key está en el registro, verifica contra esa clave
        (modo estricto — rechaza si la clave cambió).

        Devuelve (válido, mensaje).
        """
        # ── 1. Reconstruir la clave pública ───────────────────────────────────
        try:
            verify_key = nacl.signing.VerifyKey(
                known_key.public_bytes() if known_key else payload.pubkey
            )
        except Exception as e:
            return False, f"Clave pública inválida: {e}"

        # ── 2. Verificar que el agent_id coincide con la pubkey ───────────────
        import hashlib
        derived_id = hashlib.sha256(bytes(verify_key)).hexdigest()[:32]
        if derived_id != payload.agent_id:
            return False, (
                f"agent_id no coincide con la clave pública: "
                f"declarado={payload.agent_id[:12]}... "
                f"derivado={derived_id[:12]}..."
            )

        # ── 3. Verificar que la clave coincide con la registrada (si aplica) ──
        if known_key and bytes(verify_key) != known_key.public_bytes():
            return False, "La clave pública cambió — posible ataque de suplantación"

        # ── 4. Verificar la firma Ed25519 ─────────────────────────────────────
        message = _canonical_message(tx_id, payload.agent_id, payload.token_str)
        try:
            verify_key.verify(message, payload.signature)
        except Exception:
            return False, "Firma Ed25519 inválida — el agente no posee la clave privada"

        return True, "OK"
