"""
ANP · API · State
=================
Singleton compartido con todos los componentes ANP.
FastAPI lo inyecta en cada ruta vía dependency injection.
"""
import os
import uuid
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional

from ..oracle import Oracle
from ..passport import PassportSigner, PassportValidator
from ..identity import AgentRegistry, CredentialVerifier, RegistryMode
from ..negotiation import NegotiationEngine, NegotiationResult

# Directorio de datos persistentes
DATA_DIR = Path(os.getenv("ANP_DATA_DIR", "/tmp/anp_data"))
FEED_PATH = Path(__file__).parent.parent / "oracle" / "feeds" / "sample_prices.json"


@dataclass
class ANPState:
    oracle:             Oracle
    passport_signer:    PassportSigner
    passport_validator: PassportValidator
    registry:           AgentRegistry
    issuer_id:          str

    # Sesiones activas en memoria (en producción: Redis)
    active_sessions:    dict = field(default_factory=dict)
    # Resultados de negociaciones completadas
    completed:          dict = field(default_factory=dict)

    @classmethod
    def create(cls) -> "ANPState":
        DATA_DIR.mkdir(parents=True, exist_ok=True)

        oracle = Oracle.from_json(
            FEED_PATH,
            x402_endpoint=os.getenv("ANP_X402_ENDPOINT"),
            x402_threshold_usd=float(os.getenv("ANP_X402_THRESHOLD", "1.0")),
        )

        secret = os.getenv("ANP_SECRET_KEY", "").encode() or None
        passport_signer = PassportSigner(secret_key=secret)
        passport_validator = PassportValidator(passport_signer)

        registry = AgentRegistry(
            mode=RegistryMode.TOFU,
            persist_path=DATA_DIR / "registry.json",
        )

        issuer_id = os.getenv("ANP_ISSUER_ID", str(uuid.uuid4()))

        return cls(
            oracle=oracle,
            passport_signer=passport_signer,
            passport_validator=passport_validator,
            registry=registry,
            issuer_id=issuer_id,
        )


# Instancia global — se inicializa en el startup de FastAPI
_state: Optional[ANPState] = None

def get_state() -> ANPState:
    global _state
    if _state is None:
        _state = ANPState.create()
    return _state
