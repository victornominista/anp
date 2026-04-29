"""
ANP · API · Server
==================
Punto de entrada principal del servidor ANP.

Ejecutar:
    python -m anp.api.server
    uvicorn anp.api.server:app --reload --port 8000

Endpoints:
    POST /negotiate              → ejecutar negociación
    GET  /negotiate/{tx_id}     → consultar resultado
    GET  /oracle/{item}         → precio base de item
    POST /oracle/validate       → validar precio vs oráculo
    GET  /oracle                → stats del oráculo
    POST /passport/issue        → emitir token ANP-Pass
    POST /passport/verify       → verificar token
    POST /identity/register     → registrar agente
    POST /identity/verify       → verificar AUTH
    GET  /health                → estado del sistema
    GET  /stats                 → métricas globales
    GET  /docs                  → Swagger UI (automático)
"""
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .state import get_state
from .routes.negotiate import router as negotiate_router
from .routes.other import (
    oracle_router, passport_router,
    identity_router, health_router,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: inicializar estado
    state = get_state()
    print(f"[ANP] Servidor iniciado")
    print(f"[ANP] Oracle: {len(state.oracle.feed)} items en feed")
    print(f"[ANP] Issuer: {state.issuer_id[:16]}...")
    yield
    # Shutdown: nada que limpiar por ahora
    print("[ANP] Servidor detenido")


app = FastAPI(
    title="ANP · Agent Negotiation Protocol",
    description=(
        "La capa económica del stack de agentes. "
        "Negociación Bot-to-Bot · Identidad Ed25519 · Pasaporte de capacidad · "
        "Oráculo anti-alucinación · Integración x402/MPP"
    ),
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health_router)
app.include_router(negotiate_router)
app.include_router(oracle_router)
app.include_router(passport_router)
app.include_router(identity_router)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("anp.api.server:app", host="0.0.0.0", port=8000, reload=True)
