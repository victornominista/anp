"""
ANP · Passport · Schema
=======================
Define la estructura del token ANP-Pass.

Un ANP-Pass es el "pasaporte" de un agente:
  - Quién es (agent_id)
  - Quién lo autorizó (issuer_id — el humano dueño)
  - Cuánto puede gastar (budget_usd)
  - En qué puede negociar (scope)
  - Hasta cuándo (ttl / expires_at)
  - Nonce único anti-replay

Inspirado en JWT pero más compacto y con semántica económica explícita.
Sin librerías de terceros para el schema — solo dataclasses + stdlib.
"""
import time
import uuid
from dataclasses import dataclass, field
from typing import Optional


# Scopes estándar del protocolo ANP
# Cualquier item del feed de precios es un scope válido.
# Wildcards: "hosting:*" cubre hosting_shared, hosting_vps, etc.
SCOPE_ALL       = "*"          # acceso total (solo para tests)
SCOPE_API       = "api:*"      # cualquier API access
SCOPE_HOSTING   = "hosting:*"  # cualquier hosting
SCOPE_COMPUTE   = "compute:*"  # GPU, CPU, storage
SCOPE_TRADE     = "trade:*"    # cualquier negociación comercial


@dataclass
class ANPPassToken:
    """
    Token de capacidad para un agente ANP.
    El issuer firma este token con HMAC-SHA256.
    El agente lo presenta en cada sesión de negociación (frame AUTH).
    """
    # ── Identidad ─────────────────────────────────────────────────────────────
    agent_id:    str            # UUID del agente que usará el token
    issuer_id:   str            # UUID del humano/sistema que emite el token

    # ── Capacidades económicas ────────────────────────────────────────────────
    budget_usd:  float          # máximo que puede gastar en total
    budget_per_tx: float        # máximo por transacción individual
    scope:       list[str]      # qué categorías puede negociar

    # ── Tiempo ────────────────────────────────────────────────────────────────
    issued_at:   float = field(default_factory=time.time)
    expires_at:  float = field(default_factory=lambda: time.time() + 3600)  # 1h default

    # ── Anti-replay ───────────────────────────────────────────────────────────
    nonce:       str = field(default_factory=lambda: str(uuid.uuid4()))
    token_id:    str = field(default_factory=lambda: str(uuid.uuid4()))

    # ── Restricciones opcionales ──────────────────────────────────────────────
    max_rounds:         Optional[int]  = None   # límite de rondas de negociación
    allowed_sellers:    Optional[list] = None   # whitelist de seller IDs
    blocked_sellers:    Optional[list] = None   # blacklist de seller IDs
    min_price_floor:    Optional[float]= None   # no aceptar por debajo de esto
    max_price_ceiling:  Optional[float]= None   # no pagar más de esto (override oracle)

    # ── Metadata ──────────────────────────────────────────────────────────────
    label:       str = ""       # nombre legible ("bot compras_hosting_abril")
    version:     int = 1        # versión del schema

    # ── Firma (se agrega después de crear el token) ───────────────────────────
    signature:   Optional[bytes] = None

    # ── Estado de uso (tracking en memoria, no va en wire) ───────────────────
    spent_usd:   float = 0.0    # cuánto ha gastado hasta ahora

    def is_expired(self) -> bool:
        return time.time() > self.expires_at

    def remaining_budget(self) -> float:
        return max(0.0, self.budget_usd - self.spent_usd)

    def can_spend(self, amount: float) -> bool:
        if self.is_expired():
            return False
        if amount > self.budget_per_tx:
            return False
        if amount > self.remaining_budget():
            return False
        return True

    def allows_scope(self, item: str) -> bool:
        """Verifica si el item está dentro del scope permitido."""
        for s in self.scope:
            if s == SCOPE_ALL:
                return True
            if s.endswith(":*"):
                prefix = s[:-2]  # "hosting:*" → "hosting"
                if item.startswith(prefix):
                    return True
            if s == item:
                return True
        return False

    def to_dict(self) -> dict:
        """Serializa a dict para firmar. NO incluye signature ni spent_usd."""
        return {
            "v":          self.version,
            "tid":        self.token_id,
            "aid":        self.agent_id,
            "iid":        self.issuer_id,
            "bud":        self.budget_usd,
            "bpt":        self.budget_per_tx,
            "scp":        self.scope,
            "iat":        self.issued_at,
            "exp":        self.expires_at,
            "non":        self.nonce,
            "lbl":        self.label,
            # opcionales solo si están seteados
            **({"mxr": self.max_rounds}       if self.max_rounds is not None else {}),
            **({"als": self.allowed_sellers}   if self.allowed_sellers else {}),
            **({"bls": self.blocked_sellers}   if self.blocked_sellers else {}),
            **({"flr": self.min_price_floor}   if self.min_price_floor is not None else {}),
            **({"cel": self.max_price_ceiling} if self.max_price_ceiling is not None else {}),
        }

    def __repr__(self) -> str:
        status = "EXPIRED" if self.is_expired() else "VALID"
        return (
            f"ANPPass({self.label or self.agent_id[:8]}... "
            f"budget=${self.budget_usd:.2f} "
            f"spent=${self.spent_usd:.2f} "
            f"scope={self.scope} "
            f"{status})"
        )
