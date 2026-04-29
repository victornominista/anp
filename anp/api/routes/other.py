"""
ANP · API · Routes · Oracle, Passport, Identity
================================================
GET  /oracle/{item}       → consulta precio base
POST /passport/issue      → emite token ANP-Pass
POST /passport/verify     → verifica token
POST /identity/register   → registra agente nuevo
POST /identity/verify     → verifica firma AUTH
GET  /health              → estado del sistema
GET  /stats               → métricas del oráculo
"""
import uuid
import time
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ..state import ANPState, get_state
from ...identity import AgentKeyPair, CredentialIssuer, CredentialVerifier
from ...identity.signer import AuthPayload
from ...passport import SCOPE_API, SCOPE_HOSTING, SCOPE_COMPUTE, SCOPE_TRADE

# ══════════════════════════════════════════════════════════════════════════════
# ORACLE
# ══════════════════════════════════════════════════════════════════════════════

oracle_router = APIRouter(prefix="/oracle", tags=["oracle"])


class OracleResponse(BaseModel):
    item:       str
    base_price: Optional[float]
    unit:       str
    floor:      Optional[float]
    ceiling:    Optional[float]
    found:      bool


class ValidateRequest(BaseModel):
    item:  str
    price: float
    qty:   int = 1
    role:  str = Field("buyer", pattern="^(buyer|seller)$")


class ValidateResponse(BaseModel):
    status:       str
    blocked:      bool
    offered:      float
    base_price:   Optional[float]
    deviation_pct: Optional[float]
    savings_usd:  float
    x402_required: bool
    reason:       str


@oracle_router.get("/{item}", response_model=OracleResponse)
async def get_price(item: str, state: ANPState = Depends(get_state)):
    """Consulta el precio base de mercado para un item."""
    entry = state.oracle.feed.get(item)
    if not entry:
        return OracleResponse(item=item, base_price=None, unit="unknown",
                              floor=None, ceiling=None, found=False)
    return OracleResponse(item=item, base_price=entry.price, unit=entry.unit,
                          floor=entry.floor, ceiling=entry.ceiling, found=True)


@oracle_router.post("/validate", response_model=ValidateResponse)
async def validate_price(req: ValidateRequest, state: ANPState = Depends(get_state)):
    """Valida si un precio es razonable según el oráculo."""
    if req.role == "buyer":
        result = state.oracle.check_buy(req.item, req.price, req.qty)
    else:
        result = state.oracle.check_sell(req.item, req.price, req.qty)
    return ValidateResponse(
        status=result.status.value, blocked=result.blocked,
        offered=result.offered, base_price=result.base_price,
        deviation_pct=result.deviation_pct, savings_usd=result.savings_usd,
        x402_required=result.x402_required, reason=result.reason,
    )


@oracle_router.get("", response_model=dict)
async def oracle_stats(state: ANPState = Depends(get_state)):
    """Métricas del oráculo: ahorros acumulados, bloqueos, etc."""
    return {
        "items_in_feed": len(state.oracle.feed),
        "savings": state.oracle.savings_report(),
    }


# ══════════════════════════════════════════════════════════════════════════════
# PASSPORT
# ══════════════════════════════════════════════════════════════════════════════

passport_router = APIRouter(prefix="/passport", tags=["passport"])

VALID_SCOPES = {
    "api": SCOPE_API, "hosting": SCOPE_HOSTING,
    "compute": SCOPE_COMPUTE, "trade": SCOPE_TRADE, "all": "*",
}


class IssueRequest(BaseModel):
    agent_id:      str
    budget_usd:    float = Field(..., gt=0)
    budget_per_tx: float = Field(..., gt=0)
    scope:         list[str] = Field(default=["api"])
    ttl_seconds:   int = Field(3600, ge=60, le=86400)
    label:         str = ""


class IssueResponse(BaseModel):
    token:      str
    token_id:   str
    agent_id:   str
    expires_at: float
    size_bytes: int


class VerifyRequest(BaseModel):
    token:     str
    item:      Optional[str] = None
    price:     Optional[float] = None
    seller_id: Optional[str] = None


class VerifyResponse(BaseModel):
    valid:            bool
    granted:          bool
    agent_id:         Optional[str]
    token_id:         Optional[str]
    remaining_budget: Optional[float]
    reason:           str


@passport_router.post("/issue", response_model=IssueResponse)
async def issue_passport(req: IssueRequest, state: ANPState = Depends(get_state)):
    """Emite un token ANP-Pass para un agente."""
    resolved_scope = [VALID_SCOPES.get(s, s) for s in req.scope]
    token, token_str = state.passport_signer.issue(
        agent_id=req.agent_id,
        issuer_id=state.issuer_id,
        budget_usd=req.budget_usd,
        budget_per_tx=req.budget_per_tx,
        scope=resolved_scope,
        ttl_seconds=req.ttl_seconds,
        label=req.label,
    )
    return IssueResponse(
        token=token_str, token_id=token.token_id,
        agent_id=token.agent_id, expires_at=token.expires_at,
        size_bytes=len(token_str),
    )


@passport_router.post("/verify", response_model=VerifyResponse)
async def verify_passport(req: VerifyRequest, state: ANPState = Depends(get_state)):
    """Verifica un token ANP-Pass y opcionalmente su permiso para una transacción."""
    if req.item and req.price is not None:
        perm = state.passport_validator.check(
            req.token, item=req.item, price=req.price, seller_id=req.seller_id,
        )
        return VerifyResponse(
            valid=True, granted=perm.granted,
            agent_id=perm.agent_id, token_id=perm.token_id,
            remaining_budget=perm.remaining_budget, reason=perm.reason,
        )
    else:
        valid, token, msg = state.passport_signer.verify(req.token)
        return VerifyResponse(
            valid=valid, granted=valid,
            agent_id=token.agent_id if token else None,
            token_id=token.token_id if token else None,
            remaining_budget=token.remaining_budget() if token else None,
            reason=msg,
        )


# ══════════════════════════════════════════════════════════════════════════════
# IDENTITY
# ══════════════════════════════════════════════════════════════════════════════

identity_router = APIRouter(prefix="/identity", tags=["identity"])


class RegisterResponse(BaseModel):
    agent_id:       str
    public_key_hex: str
    label:          str
    message:        str


class VerifyAuthRequest(BaseModel):
    agent_id:  str
    pubkey_hex: str
    token_str: str
    signature_hex: str
    tx_id:     int
    item:      str
    price:     float


class VerifyAuthResponse(BaseModel):
    authorized: bool
    agent_id:   str
    reason:     str
    registry_status: str


@identity_router.post("/register", response_model=RegisterResponse)
async def register_agent(label: str = "", state: ANPState = Depends(get_state)):
    """
    Genera un nuevo keypair Ed25519 para un agente.
    En producción el agente genera su propio keypair localmente
    y solo comparte la clave pública. Este endpoint es para demos/testing.
    """
    kp = AgentKeyPair.generate(label=label)
    state.registry.register(kp.agent_id, kp.export_public(), label=label)
    return RegisterResponse(
        agent_id=kp.agent_id,
        public_key_hex=kp.export_public_hex(),
        label=label,
        message="Keypair generado. Guarda la clave pública — la privada solo existe aquí ahora.",
    )


@identity_router.post("/verify", response_model=VerifyAuthResponse)
async def verify_auth(req: VerifyAuthRequest, state: ANPState = Depends(get_state)):
    """Verifica un payload AUTH completo (identidad + firma + passport)."""
    try:
        pubkey_bytes = bytes.fromhex(req.pubkey_hex)
        sig_bytes    = bytes.fromhex(req.signature_hex)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"Hex inválido: {e}")

    auth = AuthPayload(
        agent_id=req.agent_id,
        pubkey=pubkey_bytes,
        token_str=req.token_str,
        signature=sig_bytes,
    )

    verifier = CredentialVerifier(state.passport_validator, registry=state.registry)
    authorized, reason = verifier.verify_auth(
        auth, tx_id=req.tx_id, item=req.item, price=req.price,
    )

    rec = state.registry.get(req.agent_id)
    registry_status = "unknown"
    if rec:
        registry_status = "blocked" if rec.blocked else ("known" if rec.tx_count > 1 else "new")

    return VerifyAuthResponse(
        authorized=authorized, agent_id=req.agent_id,
        reason=reason, registry_status=registry_status,
    )


# ══════════════════════════════════════════════════════════════════════════════
# HEALTH
# ══════════════════════════════════════════════════════════════════════════════

health_router = APIRouter(tags=["health"])


@health_router.get("/health")
async def health(state: ANPState = Depends(get_state)):
    return {
        "status": "ok",
        "version": "1.0.0",
        "protocol": "ANP",
        "issuer_id": state.issuer_id[:16] + "...",
        "oracle_items": len(state.oracle.feed),
        "registered_agents": len(state.registry.all_agents()),
        "completed_negotiations": len(state.completed),
        "timestamp": time.time(),
    }


@health_router.get("/stats")
async def stats(state: ANPState = Depends(get_state)):
    reg_stats = state.registry.stats()
    return {
        "oracle":   state.oracle.savings_report(),
        "registry": reg_stats,
        "sessions": {
            "completed": len(state.completed),
            "active":    len(state.active_sessions),
        },
    }
