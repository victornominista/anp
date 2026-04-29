"""
ANP · API · Routes · Negotiate
==============================
POST /negotiate       → inicia negociación completa
GET  /negotiate/{id}  → consulta resultado por tx_id
"""
import time
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ..state import ANPState, get_state
from ...negotiation import (
    NegotiationEngine, BuyerAgent, SellerAgent,
    BuyerLinear, BuyerPatient, BuyerAggressive,
    SellerLinear, SellerDeadline,
)

router = APIRouter(prefix="/negotiate", tags=["negotiate"])


# ── Request / Response models ─────────────────────────────────────────────────

class NegotiateRequest(BaseModel):
    item:            str   = Field(..., example="api_access_basic")
    max_price:       float = Field(..., gt=0, example=0.10)
    seller_start:    float = Field(..., gt=0, example=0.09)
    seller_min:      float = Field(..., gt=0, example=0.05)
    qty:             int   = Field(1, ge=1)
    buyer_strategy:  str   = Field("linear", pattern="^(linear|patient|aggressive)$")
    seller_strategy: str   = Field("linear", pattern="^(linear|deadline)$")
    validate_oracle: bool  = Field(True)
    passport_token:  Optional[str] = Field(None)


class FrameLog(BaseModel):
    direction: str
    op:        str
    tx_id:     str
    agent_id:  str
    bytes:     int
    label:     str


class NegotiateResponse(BaseModel):
    tx_id:          str
    success:        bool
    final_price:    Optional[float]
    state:          str
    rounds:         int
    bytes_wire:     int
    bytes_json_equiv: int
    elapsed_ms:     float
    savings_usd:    float
    oracle_blocked: bool
    frames:         list[FrameLog]
    message:        str


# ── Helpers ───────────────────────────────────────────────────────────────────

BUYER_STRATEGIES = {
    "linear":     lambda: BuyerLinear(),
    "patient":    lambda: BuyerPatient(patience=3),
    "aggressive": lambda: BuyerAggressive(),
}

SELLER_STRATEGIES = {
    "linear":   lambda: SellerLinear(),
    "deadline": lambda: SellerDeadline(),
}


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("", response_model=NegotiateResponse)
async def negotiate(req: NegotiateRequest, state: ANPState = Depends(get_state)):
    """
    Ejecuta una negociación completa entre un agente comprador y vendedor.

    Si validate_oracle=True, el oráculo valida el precio antes de iniciar.
    Si passport_token está presente, se verifica que el token autorice la operación.
    """

    # ── 1. Validación del oráculo ─────────────────────────────────────────────
    oracle_blocked = False
    savings_usd = 0.0

    if req.validate_oracle:
        result = state.oracle.check_buy(req.item, req.max_price, req.qty)
        if result.blocked:
            oracle_blocked = True
            savings_usd = result.savings_usd
            return NegotiateResponse(
                tx_id="blocked",
                success=False,
                final_price=None,
                state="ORACLE_BLOCKED",
                rounds=0,
                bytes_wire=0,
                bytes_json_equiv=0,
                elapsed_ms=0,
                savings_usd=savings_usd,
                oracle_blocked=True,
                frames=[],
                message=f"Oracle bloqueó la operación: {result.reason}",
            )

    # ── 2. Validación del passport (si se provee) ─────────────────────────────
    if req.passport_token:
        perm = state.passport_validator.check(
            req.passport_token,
            item=req.item,
            price=req.max_price,
            qty=req.qty,
        )
        if not perm.granted:
            raise HTTPException(status_code=403, detail=f"Passport denegado: {perm.reason}")

    # ── 3. Construir agentes ──────────────────────────────────────────────────
    tx_id_int = int(uuid.uuid4().int & 0xFFFF)

    buyer = BuyerAgent(
        agent_id=0x0001,
        max_price=req.max_price,
        strategy=BUYER_STRATEGIES[req.buyer_strategy](),
    )
    seller = SellerAgent(
        agent_id=0x0002,
        start_price=req.seller_start,
        min_price=req.seller_min,
        strategy=SELLER_STRATEGIES[req.seller_strategy](),
    )

    # ── 4. Ejecutar negociación ───────────────────────────────────────────────
    engine = NegotiationEngine(buyer, seller)
    neg_result = engine.run(
        item=req.item,
        deadline=int(time.time()) + 60,
        tx_id=tx_id_int,
        qty=req.qty,
    )

    # ── 5. Construir log de frames ────────────────────────────────────────────
    frame_logs = [
        FrameLog(
            direction=direction,
            op=frame.op.name,
            tx_id=f"{frame.tx_id:04X}",
            agent_id=f"{frame.agent_id:04X}",
            bytes=frame.size,
            label=label,
        )
        for direction, frame, label in neg_result.frames
    ]

    # ── 6. Guardar resultado ──────────────────────────────────────────────────
    tx_key = f"{tx_id_int:04X}"
    state.completed[tx_key] = neg_result

    return NegotiateResponse(
        tx_id=tx_key,
        success=neg_result.success,
        final_price=neg_result.final_price,
        state=neg_result.state.value,
        rounds=neg_result.rounds,
        bytes_wire=neg_result.bytes_total,
        bytes_json_equiv=neg_result.json_equiv_bytes,
        elapsed_ms=neg_result.elapsed_ms,
        savings_usd=savings_usd,
        oracle_blocked=oracle_blocked,
        frames=frame_logs,
        message=(
            f"Trato cerrado a ${neg_result.final_price:.4f}"
            if neg_result.success
            else f"Sin acuerdo: {neg_result.state.value}"
        ),
    )


@router.get("/{tx_id}", response_model=NegotiateResponse)
async def get_negotiation(tx_id: str, state: ANPState = Depends(get_state)):
    """Consulta el resultado de una negociación por su tx_id."""
    result = state.completed.get(tx_id.upper())
    if not result:
        raise HTTPException(status_code=404, detail=f"Negociación {tx_id} no encontrada")

    frame_logs = [
        FrameLog(
            direction=d, op=f.op.name,
            tx_id=f"{f.tx_id:04X}", agent_id=f"{f.agent_id:04X}",
            bytes=f.size, label=l,
        )
        for d, f, l in result.frames
    ]
    return NegotiateResponse(
        tx_id=tx_id.upper(), success=result.success,
        final_price=result.final_price, state=result.state.value,
        rounds=result.rounds, bytes_wire=result.bytes_total,
        bytes_json_equiv=result.json_equiv_bytes, elapsed_ms=result.elapsed_ms,
        savings_usd=0.0, oracle_blocked=False, frames=frame_logs,
        message="Resultado de negociación completada",
    )
