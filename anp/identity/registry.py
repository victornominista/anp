"""
ANP · Identity · Registry
==========================
Registro local de agentes conocidos.
Como el archivo `~/.ssh/known_hosts` pero para agentes ANP.

Dos modos:
  TOFU (Trust On First Use): la primera vez que ves un agente, guardas su clave.
    Si la próxima vez viene con una clave diferente → alerta de suplantación.
  STRICT: solo acepta agentes pre-registrados (whitelist explícita).

No hay servidor central. Cada nodo mantiene su propio registro.
Esto es descentralizado por diseño — igual que Bitcoin no tiene un
servidor central que diga qué direcciones existen.
"""
import json
import time
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Optional
from enum import Enum

from .keypair import VerifyOnlyKey
import nacl.signing


class RegistryMode(Enum):
    TOFU   = "tofu"    # confía la primera vez, alerta si cambia
    STRICT = "strict"  # solo acepta agentes pre-registrados


@dataclass
class AgentRecord:
    agent_id:      str
    pubkey_hex:    str       # clave pública en hex (64 chars)
    label:         str
    first_seen:    float
    last_seen:     float
    trusted:       bool = True
    blocked:       bool = False
    tx_count:      int  = 0
    total_spent:   float = 0.0
    notes:         str  = ""

    def to_verify_key(self) -> VerifyOnlyKey:
        return VerifyOnlyKey(
            verify_key=nacl.signing.VerifyKey(bytes.fromhex(self.pubkey_hex)),
            agent_id=self.agent_id,
            label=self.label,
        )


class AgentRegistry:
    """
    Registro local de agentes conocidos.

    Uso típico (vendedor verificando comprador):
        registry = AgentRegistry(mode=RegistryMode.TOFU)
        result = registry.encounter(agent_id, pubkey_bytes)
        if result == "BLOCKED":
            raise PermissionError("Agente bloqueado")
    """

    def __init__(
        self,
        mode: RegistryMode = RegistryMode.TOFU,
        persist_path: Optional[str | Path] = None,
    ):
        self.mode = mode
        self._records: dict[str, AgentRecord] = {}
        self._path = Path(persist_path) if persist_path else None
        if self._path and self._path.exists():
            self._load()

    # ── Registro y consulta ───────────────────────────────────────────────────

    def encounter(
        self,
        agent_id: str,
        pubkey_bytes: bytes,
        label: str = "",
    ) -> tuple[str, Optional[AgentRecord]]:
        """
        Procesa un encuentro con un agente.
        Devuelve: ("NEW"|"KNOWN"|"KEY_CHANGED"|"BLOCKED", record_o_None)

        NEW:         primer encuentro — en TOFU, se registra automáticamente
        KNOWN:       agente conocido, clave igual — OK
        KEY_CHANGED: agente conocido pero con clave diferente — ALERTA
        BLOCKED:     agente en blacklist — rechazar
        """
        pubkey_hex = pubkey_bytes.hex()
        now = time.time()

        # ── Agente ya conocido ────────────────────────────────────────────────
        if agent_id in self._records:
            record = self._records[agent_id]

            if record.blocked:
                return "BLOCKED", record

            if record.pubkey_hex != pubkey_hex:
                # La clave cambió — posible suplantación
                record.notes += f"\n[{int(now)}] ALERTA: clave cambió de {record.pubkey_hex[:16]}... a {pubkey_hex[:16]}..."
                return "KEY_CHANGED", record

            # Todo bien — actualizar stats
            record.last_seen = now
            record.tx_count += 1
            self._save()
            return "KNOWN", record

        # ── Agente nuevo ──────────────────────────────────────────────────────
        if self.mode == RegistryMode.STRICT:
            # En modo strict, los desconocidos son rechazados
            return "BLOCKED", None

        # TOFU: registrar automáticamente
        record = AgentRecord(
            agent_id=agent_id,
            pubkey_hex=pubkey_hex,
            label=label or agent_id[:12] + "...",
            first_seen=now,
            last_seen=now,
            trusted=True,
            blocked=False,
            tx_count=1,
        )
        self._records[agent_id] = record
        self._save()
        return "NEW", record

    def get(self, agent_id: str) -> Optional[AgentRecord]:
        return self._records.get(agent_id)

    def get_verify_key(self, agent_id: str) -> Optional[VerifyOnlyKey]:
        record = self._records.get(agent_id)
        return record.to_verify_key() if record else None

    def register(self, agent_id: str, pubkey_bytes: bytes, label: str = "", trusted: bool = True):
        """Registra manualmente un agente (para whitelist en modo STRICT)."""
        now = time.time()
        self._records[agent_id] = AgentRecord(
            agent_id=agent_id,
            pubkey_hex=pubkey_bytes.hex(),
            label=label,
            first_seen=now,
            last_seen=now,
            trusted=trusted,
            blocked=False,
        )
        self._save()

    def block(self, agent_id: str, reason: str = ""):
        """Bloquea un agente — sus futuros AUTH serán rechazados."""
        if agent_id in self._records:
            self._records[agent_id].blocked = True
            self._records[agent_id].notes += f"\nBLOCKED: {reason}"
        else:
            now = time.time()
            self._records[agent_id] = AgentRecord(
                agent_id=agent_id, pubkey_hex="",
                label="blocked", first_seen=now, last_seen=now,
                trusted=False, blocked=True, notes=f"BLOCKED: {reason}",
            )
        self._save()

    def record_spend(self, agent_id: str, amount: float):
        if agent_id in self._records:
            self._records[agent_id].total_spent += amount
            self._save()

    def all_agents(self) -> list[AgentRecord]:
        return list(self._records.values())

    def stats(self) -> dict:
        records = self.all_agents()
        return {
            "total":   len(records),
            "trusted": sum(1 for r in records if r.trusted and not r.blocked),
            "blocked": sum(1 for r in records if r.blocked),
            "mode":    self.mode.value,
        }

    # ── Persistencia ──────────────────────────────────────────────────────────

    def _save(self):
        if not self._path:
            return
        self._path.parent.mkdir(parents=True, exist_ok=True)
        data = {aid: asdict(rec) for aid, rec in self._records.items()}
        self._path.write_text(json.dumps(data, indent=2))

    def _load(self):
        try:
            data = json.loads(self._path.read_text())
            self._records = {aid: AgentRecord(**rec) for aid, rec in data.items()}
        except Exception:
            self._records = {}
