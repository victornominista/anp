"""
ANP · Oracle · Price Feed
=========================
Carga precios base de mercado desde JSON local o fuente externa.
El oráculo usa estos precios para validar si una oferta es razonable.

Fuentes soportadas:
  1. JSON local (default, sin internet)
  2. x402 / MPP price endpoint (HTTP, si está disponible)
  3. Dict en memoria (para tests)
"""
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass
class PriceEntry:
    item:       str
    price:      float       # precio base de mercado en USD
    unit:       str         # "per_call", "per_month", "each", etc.
    updated:    str         # ISO date
    source:     str = "local"

    # Límites opcionales (para protección hard)
    floor:      Optional[float] = None   # nunca aceptar por debajo de esto
    ceiling:    Optional[float] = None   # nunca pagar más de esto (protección sobreprecio)


class PriceFeed:
    """
    Repositorio de precios base. Thread-safe para lectura.
    Se puede refrescar sin reiniciar el proceso.
    """

    def __init__(self):
        self._prices: dict[str, PriceEntry] = {}
        self._loaded_at: float = 0

    # ── Carga ──────────────────────────────────────────────────────────────────

    def load_json(self, path: str | Path) -> int:
        """Carga precios desde archivo JSON. Devuelve número de items cargados."""
        data = json.loads(Path(path).read_text())
        count = 0
        for item, info in data.items():
            self._prices[item] = PriceEntry(
                item=item,
                price=float(info["price"]),
                unit=info.get("unit", "unit"),
                updated=info.get("updated", "unknown"),
                source="local_json",
                floor=info.get("floor"),
                ceiling=info.get("ceiling"),
            )
            count += 1
        self._loaded_at = time.time()
        return count

    def load_dict(self, data: dict) -> int:
        """Carga precios desde dict en memoria (útil para tests)."""
        for item, price in data.items():
            if isinstance(price, (int, float)):
                self._prices[item] = PriceEntry(
                    item=item, price=float(price),
                    unit="unit", updated="manual", source="memory",
                )
            elif isinstance(price, dict):
                self._prices[item] = PriceEntry(
                    item=item,
                    price=float(price["price"]),
                    unit=price.get("unit", "unit"),
                    updated=price.get("updated", "manual"),
                    source="memory",
                    floor=price.get("floor"),
                    ceiling=price.get("ceiling"),
                )
        self._loaded_at = time.time()
        return len(data)

    def load_x402(self, endpoint: str, timeout: float = 2.0) -> int:
        """
        Intenta cargar precios desde endpoint x402/MPP.
        Si falla (sin internet, timeout) usa los precios locales ya cargados.
        Devuelve número de items actualizados, 0 si falló.
        """
        try:
            import urllib.request
            import urllib.error
            req = urllib.request.Request(
                endpoint,
                headers={"Accept": "application/json", "X-ANP-Version": "1"},
            )
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = json.loads(resp.read().decode())
            count = 0
            for item, info in data.get("prices", {}).items():
                self._prices[item] = PriceEntry(
                    item=item,
                    price=float(info["price"]),
                    unit=info.get("unit", "unit"),
                    updated=info.get("updated", "unknown"),
                    source=f"x402:{endpoint}",
                    floor=info.get("floor"),
                    ceiling=info.get("ceiling"),
                )
                count += 1
            self._loaded_at = time.time()
            return count
        except Exception:
            return 0   # falla silenciosa — usa precios locales

    # ── Consulta ───────────────────────────────────────────────────────────────

    def get(self, item: str) -> Optional[PriceEntry]:
        return self._prices.get(item)

    def get_price(self, item: str) -> Optional[float]:
        entry = self._prices.get(item)
        return entry.price if entry else None

    def all_items(self) -> list[str]:
        return list(self._prices.keys())

    def __len__(self):
        return len(self._prices)

    def __repr__(self):
        return f"PriceFeed({len(self._prices)} items, loaded {int(time.time()-self._loaded_at)}s ago)"
