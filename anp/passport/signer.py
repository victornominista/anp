"""
ANP · Passport · Signer
=======================
Firma y verifica tokens ANP-Pass usando HMAC-SHA256.
Serialización: msgpack (binario compacto) + base64url (safe para HTTP headers).

Por qué HMAC-SHA256 y no Ed25519 aquí:
  - HMAC es simétrico: el issuer firma Y verifica con la misma clave secreta.
  - Es más rápido y simple para tokens de autorización donde el issuer
    es también quien valida (tu servidor, tu clave).
  - Ed25519 está en M4 (identidad de agentes, donde el vendedor
    necesita verificar sin conocer la clave privada del comprador).
  - HMAC es el estándar de JWT/PASETO — familiar para desarrolladores.

Formato wire del token:
  base64url( version(1B) + msgpack(payload) + hmac(32B) )
  Tamaño típico: ~160 bytes en base64 — cabe en un header HTTP.
"""
import base64
import hashlib
import hmac
import json
import os
import time
from typing import Optional

import msgpack

from .schema import ANPPassToken


# Versión del formato de serialización
TOKEN_VERSION = 0x01


def _b64encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()

def _b64decode(s: str) -> bytes:
    # Re-agregar padding si falta
    pad = 4 - len(s) % 4
    if pad != 4:
        s += "=" * pad
    return base64.urlsafe_b64decode(s)


class PassportSigner:
    """
    Firma y verifica tokens ANP-Pass.
    Instanciar con una clave secreta (32 bytes recomendado).

    El issuer guarda la clave secreta. Los agentes solo tienen el token firmado.
    Para revocar: invalidar el nonce o la clave secreta.
    """

    def __init__(self, secret_key: Optional[bytes] = None):
        if secret_key is None:
            secret_key = os.urandom(32)
        if len(secret_key) < 16:
            raise ValueError("La clave secreta debe tener al menos 16 bytes")
        self._key = secret_key

    @property
    def key_fingerprint(self) -> str:
        """Primeros 8 hex de SHA256 de la clave — para identificar qué clave firmó."""
        digest = hashlib.sha256(self._key).hexdigest()
        return digest[:8]

    # ── Firma ──────────────────────────────────────────────────────────────────

    def sign(self, token: ANPPassToken) -> str:
        """
        Firma el token y devuelve el string base64url listo para usar en wire.
        También setea token.signature con los bytes crudos.
        """
        payload_dict = token.to_dict()
        payload_bytes = msgpack.packb(payload_dict, use_bin_type=True)

        # Header: 1 byte versión
        header = bytes([TOKEN_VERSION])

        # HMAC sobre: header + payload
        mac = hmac.new(self._key, header + payload_bytes, hashlib.sha256).digest()

        # Token wire: header + payload + mac
        raw = header + payload_bytes + mac
        token.signature = mac

        return _b64encode(raw)

    # ── Verificación ───────────────────────────────────────────────────────────

    def verify(self, token_str: str) -> tuple[bool, Optional[ANPPassToken], str]:
        """
        Verifica y deserializa un token.
        Devuelve: (válido, token_o_None, mensaje_de_error)
        """
        try:
            raw = _b64decode(token_str)
        except Exception:
            return False, None, "Token malformado: no es base64url válido"

        if len(raw) < 1 + 32:  # mínimo: 1 header + 32 hmac
            return False, None, "Token demasiado corto"

        version = raw[0]
        if version != TOKEN_VERSION:
            return False, None, f"Versión de token desconocida: {version}"

        # Separa payload y mac (últimos 32 bytes)
        payload_bytes = raw[1:-32]
        received_mac  = raw[-32:]

        # Verifica HMAC (comparación en tiempo constante — anti timing attack)
        expected_mac = hmac.new(
            self._key,
            bytes([version]) + payload_bytes,
            hashlib.sha256,
        ).digest()

        if not hmac.compare_digest(expected_mac, received_mac):
            return False, None, "Firma inválida — token alterado o clave incorrecta"

        # Deserializa payload
        try:
            d = msgpack.unpackb(payload_bytes, raw=False)
        except Exception as e:
            return False, None, f"Payload corrupto: {e}"

        # Reconstruye el token
        try:
            token = ANPPassToken(
                token_id=d["tid"],
                agent_id=d["aid"],
                issuer_id=d["iid"],
                budget_usd=d["bud"],
                budget_per_tx=d["bpt"],
                scope=d["scp"],
                issued_at=d["iat"],
                expires_at=d["exp"],
                nonce=d["non"],
                label=d.get("lbl", ""),
                version=d.get("v", 1),
                max_rounds=d.get("mxr"),
                allowed_sellers=d.get("als"),
                blocked_sellers=d.get("bls"),
                min_price_floor=d.get("flr"),
                max_price_ceiling=d.get("cel"),
                signature=received_mac,
            )
        except KeyError as e:
            return False, None, f"Campo requerido faltante: {e}"

        # Verifica expiración
        if token.is_expired():
            return False, token, f"Token expirado hace {int(time.time() - token.expires_at)}s"

        return True, token, "OK"

    # ── Factory helpers ────────────────────────────────────────────────────────

    def issue(
        self,
        agent_id: str,
        issuer_id: str,
        budget_usd: float,
        budget_per_tx: float,
        scope: list[str],
        ttl_seconds: int = 3600,
        label: str = "",
        **kwargs,
    ) -> tuple[ANPPassToken, str]:
        """
        Crea, firma y devuelve (token_objeto, token_string).
        Shortcut para el flujo más común.
        """
        token = ANPPassToken(
            agent_id=agent_id,
            issuer_id=issuer_id,
            budget_usd=budget_usd,
            budget_per_tx=budget_per_tx,
            scope=scope,
            expires_at=time.time() + ttl_seconds,
            label=label,
            **kwargs,
        )
        token_str = self.sign(token)
        return token, token_str
