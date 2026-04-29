"""
ANP · Identity · KeyPair
========================
Identidad criptográfica de un agente usando Ed25519.

Por qué Ed25519 (igual que Bitcoin moderno / SSH / Signal):
  - Claves de solo 32 bytes (vs 256 bytes de RSA-2048)
  - Firma en ~50 microsegundos en CPU sin GPU
  - Verificación en ~100 microsegundos
  - Seguridad de 128 bits — equivalente a RSA-3072
  - Sin parámetros secretos que malconfigurar (a diferencia de ECDSA)

Analogía Bitcoin:
  Bitcoin:  clave privada → dirección pública → firmas transacciones
  ANP:      clave privada → agent_id (DID)    → firma mensajes AUTH

El agent_id es el primer 16 bytes del SHA256 de la clave pública,
codificado como hex. Determinístico, sin registro central.
"""
import hashlib
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import nacl.signing
import nacl.encoding


@dataclass
class AgentKeyPair:
    """
    Par de claves Ed25519 de un agente.
    La clave privada NUNCA sale del agente.
    La clave pública se comparte libremente.
    El agent_id se deriva de la clave pública (como una dirección Bitcoin).
    """
    _signing_key:   nacl.signing.SigningKey    # PRIVADA — nunca serializar en logs
    verify_key:     nacl.signing.VerifyKey     # pública — compartir libremente
    agent_id:       str                        # DID derivado: hex de primeros 16B del SHA256(pubkey)
    label:          str = ""                   # nombre legible opcional

    # ── Factory methods ───────────────────────────────────────────────────────

    @classmethod
    def generate(cls, label: str = "") -> "AgentKeyPair":
        """Genera un nuevo par de claves aleatorio."""
        signing_key = nacl.signing.SigningKey.generate()
        return cls._from_signing_key(signing_key, label)

    @classmethod
    def from_seed(cls, seed: bytes, label: str = "") -> "AgentKeyPair":
        """
        Deriva claves desde una semilla de 32 bytes.
        Determinístico: misma semilla → mismo agent_id.
        Útil para recuperar identidad desde una frase mnemónica.
        """
        if len(seed) != 32:
            raise ValueError("La semilla debe ser exactamente 32 bytes")
        signing_key = nacl.signing.SigningKey(seed)
        return cls._from_signing_key(signing_key, label)

    @classmethod
    def _from_signing_key(cls, signing_key: nacl.signing.SigningKey, label: str) -> "AgentKeyPair":
        verify_key = signing_key.verify_key
        pubkey_bytes = bytes(verify_key)
        agent_id = hashlib.sha256(pubkey_bytes).hexdigest()[:32]  # 16 bytes → 32 hex chars
        return cls(
            _signing_key=signing_key,
            verify_key=verify_key,
            agent_id=agent_id,
            label=label,
        )

    # ── Serialización (solo para persistencia) ────────────────────────────────

    def export_private(self) -> bytes:
        """
        Exporta la clave privada como 32 bytes.
        GUARDAR EN LUGAR SEGURO. Quien tenga esto controla el agente.
        """
        return bytes(self._signing_key)

    def export_public(self) -> bytes:
        """Exporta la clave pública como 32 bytes. Seguro compartir."""
        return bytes(self.verify_key)

    def export_public_hex(self) -> str:
        return self.export_public().hex()

    def save(self, path: str | Path, include_private: bool = True):
        """
        Guarda el keypair en disco.
        Si include_private=False, solo guarda la clave pública (para registros).
        """
        p = Path(path)
        p.mkdir(parents=True, exist_ok=True)
        if include_private:
            (p / "private.key").write_bytes(self.export_private())
            (p / "private.key").chmod(0o600)  # solo el dueño puede leer
        (p / "public.key").write_bytes(self.export_public())
        (p / "agent_id").write_text(self.agent_id)
        if self.label:
            (p / "label").write_text(self.label)

    @classmethod
    def load(cls, path: str | Path) -> "AgentKeyPair":
        """Carga un keypair desde disco."""
        p = Path(path)
        private_bytes = (p / "private.key").read_bytes()
        label = (p / "label").read_text() if (p / "label").exists() else ""
        return cls.from_seed(private_bytes, label=label)

    @classmethod
    def load_public_only(cls, agent_id: str, public_bytes: bytes, label: str = "") -> "VerifyOnlyKey":
        """
        Carga solo la clave pública (para verificar firmas sin poder firmar).
        Lo que tiene el vendedor cuando recibe un AUTH del comprador.
        """
        return VerifyOnlyKey(
            verify_key=nacl.signing.VerifyKey(public_bytes),
            agent_id=agent_id,
            label=label,
        )

    # ── Firma ──────────────────────────────────────────────────────────────────

    def sign(self, message: bytes) -> bytes:
        """
        Firma un mensaje. Devuelve 64 bytes de firma Ed25519.
        El mensaje NO está incluido en la firma — se pasa por separado al verificar.
        """
        signed = self._signing_key.sign(message)
        return signed.signature   # solo los 64 bytes de firma, no el mensaje

    # ── Verificación ───────────────────────────────────────────────────────────

    def verify(self, message: bytes, signature: bytes) -> bool:
        """Verifica una firma contra este keypair."""
        try:
            self.verify_key.verify(message, signature)
            return True
        except Exception:
            return False

    def __repr__(self) -> str:
        return f"AgentKeyPair(id={self.agent_id[:12]}... label={self.label!r})"


@dataclass
class VerifyOnlyKey:
    """
    Solo la clave pública de un agente.
    Permite verificar firmas sin poder firmar.
    Es lo que el vendedor tiene del comprador en su registro.
    """
    verify_key: nacl.signing.VerifyKey
    agent_id:   str
    label:      str = ""

    def verify(self, message: bytes, signature: bytes) -> bool:
        try:
            self.verify_key.verify(message, signature)
            return True
        except Exception:
            return False

    def public_bytes(self) -> bytes:
        return bytes(self.verify_key)

    def public_hex(self) -> str:
        return self.public_bytes().hex()

    def __repr__(self) -> str:
        return f"VerifyOnlyKey(id={self.agent_id[:12]}... label={self.label!r})"
