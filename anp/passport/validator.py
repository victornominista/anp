"""
ANP · Passport · Validator
==========================
Verifica si un token ANP-Pass autoriza una transacción específica.

Se ejecuta ANTES de que el agente envíe un BID o acepte un OFFER.
Si el token no autoriza, la negociación no inicia.

Capas de verificación (en orden):
  1. Firma válida (no alterado)
  2. No expirado
  3. Item dentro del scope
  4. Precio dentro del budget_per_tx
  5. Budget total restante suficiente
  6. Seller no está en blacklist
  7. Seller está en whitelist (si existe)
  8. Precio no supera max_price_ceiling del token
"""
from dataclasses import dataclass
from enum import Enum
from typing import Optional

from .schema import ANPPassToken
from .signer import PassportSigner


class PermissionStatus(Enum):
    GRANTED         = "GRANTED"           # ✓ todo OK
    DENIED_EXPIRED  = "DENIED_EXPIRED"    # ✗ token expirado
    DENIED_SCOPE    = "DENIED_SCOPE"      # ✗ item fuera de scope
    DENIED_BUDGET   = "DENIED_BUDGET"     # ✗ precio > budget_per_tx
    DENIED_TOTAL    = "DENIED_TOTAL"      # ✗ presupuesto total agotado
    DENIED_SELLER   = "DENIED_SELLER"     # ✗ seller no autorizado
    DENIED_CEILING  = "DENIED_CEILING"    # ✗ precio supera ceiling del token
    DENIED_SIG      = "DENIED_SIG"        # ✗ firma inválida
    DENIED_FLOOR    = "DENIED_FLOOR"      # ✗ precio bajo floor (para vendedores)


@dataclass
class PermissionResult:
    status:     PermissionStatus
    granted:    bool
    reason:     str
    token_id:   Optional[str] = None
    agent_id:   Optional[str] = None
    remaining_budget: Optional[float] = None

    def __bool__(self):
        return self.granted

    def __repr__(self):
        icon = "✓" if self.granted else "✗"
        return f"Permission({icon} {self.status.value}: {self.reason})"


class PassportValidator:
    """
    Valida permisos de tokens ANP-Pass por transacción.

    Uso típico (en el engine antes de enviar BID):
        validator = PassportValidator(signer)
        perm = validator.check(token_str, item="api_access", price=0.07, seller_id="seller_001")
        if not perm:
            raise PermissionError(perm.reason)
    """

    def __init__(self, signer: PassportSigner):
        self.signer = signer
        # Nonces usados (anti-replay en memoria — en producción: Redis/DB)
        self._used_nonces: set[str] = set()

    def check(
        self,
        token_str:   str,
        item:        str,
        price:       float,
        qty:         int = 1,
        seller_id:   Optional[str] = None,
        use_nonce:   bool = False,   # True = marca nonce como usado (operación real)
    ) -> PermissionResult:
        """
        Verifica si el token autoriza esta transacción específica.
        Devuelve PermissionResult (truthy si GRANTED).
        """

        # ── 1. Verificar firma ────────────────────────────────────────────────
        valid, token, msg = self.signer.verify(token_str)
        if not valid:
            return PermissionResult(
                status=PermissionStatus.DENIED_SIG,
                granted=False,
                reason=msg,
            )

        # ── 2. Expiración ─────────────────────────────────────────────────────
        if token.is_expired():
            return PermissionResult(
                status=PermissionStatus.DENIED_EXPIRED,
                granted=False,
                reason="Token expirado",
                token_id=token.token_id,
                agent_id=token.agent_id,
            )

        # ── 3. Scope ──────────────────────────────────────────────────────────
        if not token.allows_scope(item):
            return PermissionResult(
                status=PermissionStatus.DENIED_SCOPE,
                granted=False,
                reason=f"Item '{item}' fuera del scope {token.scope}",
                token_id=token.token_id,
                agent_id=token.agent_id,
            )

        total_cost = price * qty

        # ── 4. Budget por transacción ─────────────────────────────────────────
        if total_cost > token.budget_per_tx:
            return PermissionResult(
                status=PermissionStatus.DENIED_BUDGET,
                granted=False,
                reason=(
                    f"${total_cost:.4f} supera budget_per_tx "
                    f"${token.budget_per_tx:.4f}"
                ),
                token_id=token.token_id,
                agent_id=token.agent_id,
                remaining_budget=token.remaining_budget(),
            )

        # ── 5. Budget total restante ──────────────────────────────────────────
        if not token.can_spend(total_cost):
            return PermissionResult(
                status=PermissionStatus.DENIED_TOTAL,
                granted=False,
                reason=(
                    f"Budget insuficiente: necesita ${total_cost:.4f}, "
                    f"disponible ${token.remaining_budget():.4f}"
                ),
                token_id=token.token_id,
                agent_id=token.agent_id,
                remaining_budget=token.remaining_budget(),
            )

        # ── 6. Blacklist de sellers ───────────────────────────────────────────
        if seller_id and token.blocked_sellers:
            if seller_id in token.blocked_sellers:
                return PermissionResult(
                    status=PermissionStatus.DENIED_SELLER,
                    granted=False,
                    reason=f"Seller '{seller_id}' está en la blacklist del token",
                    token_id=token.token_id,
                    agent_id=token.agent_id,
                )

        # ── 7. Whitelist de sellers ───────────────────────────────────────────
        if seller_id and token.allowed_sellers:
            if seller_id not in token.allowed_sellers:
                return PermissionResult(
                    status=PermissionStatus.DENIED_SELLER,
                    granted=False,
                    reason=f"Seller '{seller_id}' no está en la whitelist del token",
                    token_id=token.token_id,
                    agent_id=token.agent_id,
                )

        # ── 8. Ceiling del token ──────────────────────────────────────────────
        if token.max_price_ceiling and price > token.max_price_ceiling:
            return PermissionResult(
                status=PermissionStatus.DENIED_CEILING,
                granted=False,
                reason=(
                    f"Precio ${price:.4f} supera ceiling del token "
                    f"${token.max_price_ceiling:.4f}"
                ),
                token_id=token.token_id,
                agent_id=token.agent_id,
            )

        # ── GRANTED ───────────────────────────────────────────────────────────
        if use_nonce:
            self._used_nonces.add(token.nonce)

        return PermissionResult(
            status=PermissionStatus.GRANTED,
            granted=True,
            reason=f"Autorizado: ${total_cost:.4f} de ${token.budget_usd:.2f}",
            token_id=token.token_id,
            agent_id=token.agent_id,
            remaining_budget=token.remaining_budget(),
        )

    def record_spend(self, token: ANPPassToken, amount: float):
        """Registra un gasto real contra el budget del token en memoria."""
        token.spent_usd += amount
