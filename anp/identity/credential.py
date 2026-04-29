"""
ANP · Identity · Credential
============================
El "Token de Aplicación" — combina identidad Ed25519 + ANP-Pass.

Es lo que un agente presenta al mundo para demostrar:
  1. QUÉ ES (identidad Ed25519 — no falsificable)
  2. QUÉ PUEDE HACER (ANP-Pass — presupuesto, scope, TTL)
  3. QUE ESTÁ AUTORIZADO (firma del issuer sobre ambos)

Analogía B2B:
  Es como un empleado que presenta:
    - Su DNI (identidad — no falsificable)
    - Su tarjeta corporativa con límite (ANP-Pass)
    - La carta de su empresa diciendo que puede negociar (firma issuer)

Uso en flujo de negociación:
  1. Issuer crea Credential para el agente
  2. Agente guarda el Credential
  3. Al iniciar sesión, agente envía frame AUTH con Credential
  4. Vendedor verifica: firma Ed25519 + ANP-Pass válido + agent_id coincide
  5. Si todo OK → negociación puede iniciar
"""
import hashlib
import json
import time
from dataclasses import dataclass
from typing import Optional

from .keypair import AgentKeyPair, VerifyOnlyKey
from .signer import IdentitySigner, IdentityVerifier, AuthPayload
from ..passport import PassportSigner, PassportValidator, ANPPassToken


@dataclass
class AgentCredential:
    """
    Credencial completa de un agente ANP.
    Combina keypair (identidad) + token ANP-Pass (permisos).
    """
    keypair:    AgentKeyPair
    token:      ANPPassToken
    token_str:  str             # token serializado y firmado (listo para wire)

    # Objetos de firma/verificación
    _id_signer: Optional[IdentitySigner] = None

    def __post_init__(self):
        self._id_signer = IdentitySigner(self.keypair)

    @property
    def agent_id(self) -> str:
        return self.keypair.agent_id

    @property
    def public_key_bytes(self) -> bytes:
        return self.keypair.export_public()

    def make_auth(self, tx_id: int) -> AuthPayload:
        """
        Genera el payload AUTH listo para insertar en un frame ANP-Wire.
        Se llama al inicio de cada sesión de negociación.
        """
        return self._id_signer.make_auth_payload(tx_id, self.token_str)

    def can_negotiate(self, item: str, price: float) -> bool:
        """Verifica rápido si este credential permite negociar este item."""
        return (
            not self.token.is_expired()
            and self.token.allows_scope(item)
            and self.token.can_spend(price)
        )

    def __repr__(self) -> str:
        return (
            f"AgentCredential("
            f"id={self.agent_id[:12]}... "
            f"label={self.keypair.label!r} "
            f"budget=${self.token.budget_usd:.2f} "
            f"scope={self.token.scope})"
        )


class CredentialIssuer:
    """
    El issuer (humano o sistema) crea credenciales para sus agentes.
    Tiene tanto la clave HMAC (para ANP-Pass) como puede firmar con Ed25519
    su propio keypair para certificar que el agente es legítimo.
    """

    def __init__(self, passport_signer: PassportSigner, issuer_id: str):
        self.passport_signer = passport_signer
        self.issuer_id = issuer_id

    def issue(
        self,
        agent_keypair: AgentKeyPair,
        budget_usd: float,
        budget_per_tx: float,
        scope: list[str],
        ttl_seconds: int = 3600,
        label: str = "",
        **token_kwargs,
    ) -> AgentCredential:
        """
        Emite una credencial completa para un agente.
        El agente ya tiene su keypair — el issuer solo emite el ANP-Pass.
        """
        token, token_str = self.passport_signer.issue(
            agent_id=agent_keypair.agent_id,
            issuer_id=self.issuer_id,
            budget_usd=budget_usd,
            budget_per_tx=budget_per_tx,
            scope=scope,
            ttl_seconds=ttl_seconds,
            label=label or agent_keypair.label,
            **token_kwargs,
        )

        return AgentCredential(
            keypair=agent_keypair,
            token=token,
            token_str=token_str,
        )


class CredentialVerifier:
    """
    Verifica una credencial completa durante el handshake AUTH.
    Lo que usa el vendedor al recibir un frame AUTH.
    """

    def __init__(
        self,
        passport_validator: PassportValidator,
        registry=None,        # AgentRegistry opcional
    ):
        self.passport_validator = passport_validator
        self.registry = registry
        self._id_verifier = IdentityVerifier()

    def verify_auth(
        self,
        auth_payload: AuthPayload,
        tx_id: int,
        item: str,
        price: float,
        seller_id: Optional[str] = None,
        qty: int = 1,
    ) -> tuple[bool, str]:
        """
        Verificación completa de un AUTH payload.
        Devuelve (autorizado, motivo).

        Pasos:
          1. Registry: ¿conocemos este agente? ¿no está bloqueado?
          2. Identity: ¿la firma Ed25519 es válida?
          3. Passport: ¿el ANP-Pass autoriza esta transacción?
          4. Cross-check: ¿el agent_id del token == agent_id firmado?
        """

        # ── 1. Registro ───────────────────────────────────────────────────────
        known_key = None
        if self.registry:
            status, record = self.registry.encounter(
                auth_payload.agent_id,
                auth_payload.pubkey,
            )
            if status == "BLOCKED":
                return False, f"Agente bloqueado en el registro"
            if status == "KEY_CHANGED":
                return False, f"ALERTA: clave del agente cambió — posible suplantación"
            if status in ("KNOWN", "NEW"):
                known_key = self.registry.get_verify_key(auth_payload.agent_id)

        # ── 2. Verificar identidad Ed25519 ────────────────────────────────────
        id_valid, id_msg = self._id_verifier.verify_auth(
            auth_payload, tx_id, known_key=known_key,
        )
        if not id_valid:
            return False, f"Identidad inválida: {id_msg}"

        # ── 3. Verificar ANP-Pass ─────────────────────────────────────────────
        perm = self.passport_validator.check(
            auth_payload.token_str,
            item=item,
            price=price,
            qty=qty,
            seller_id=seller_id,
        )
        if not perm.granted:
            return False, f"Passport denegado: {perm.reason}"

        # ── 4. Cross-check agent_id ───────────────────────────────────────────
        _, token, _ = self.passport_validator.signer.verify(auth_payload.token_str)
        if token and token.agent_id != auth_payload.agent_id:
            return False, (
                f"agent_id no coincide: "
                f"firma={auth_payload.agent_id[:12]}... "
                f"token={token.agent_id[:12]}..."
            )

        return True, f"✓ Autorizado: {auth_payload.agent_id[:12]}... puede negociar {item} a ${price:.4f}"
