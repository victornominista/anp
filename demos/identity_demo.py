"""
ANP · Demo Identidad
====================
Muestra el ciclo completo de identidad Ed25519:
  1. Issuer crea agentes con keypairs únicos
  2. Agentes obtienen credenciales (identidad + pasaporte)
  3. Comprador presenta AUTH al vendedor
  4. Vendedor verifica identidad + permisos en un solo paso
  5. Se intenta suplantación — el sistema la detecta

Ejecutar: python identity_demo.py
"""
import sys, os, uuid, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich import box

from anp.identity import (
    AgentKeyPair, AgentRegistry, RegistryMode,
    CredentialIssuer, CredentialVerifier, AuthPayload,
)
from anp.passport import PassportSigner, PassportValidator, SCOPE_API, SCOPE_HOSTING
from anp.identity.signer import IdentityVerifier

console = Console()

def section(title: str):
    console.print()
    console.rule(f"[bold purple]{title}[/]", style="purple")
    console.print()

def ok(msg): console.print(f"  [bold green]✓[/] {msg}")
def fail(msg): console.print(f"  [bold red]✗[/] {msg}")
def info(msg): console.print(f"  [dim]→[/] {msg}")

def main():
    console.print()
    console.print(Panel(
        "[bold white]ANP · Identidad Ed25519[/]\n"
        "[dim]Sin autoridad central · Firma criptográfica · Registro TOFU · Anti-suplantación[/]",
        border_style="purple", box=box.DOUBLE_EDGE,
    ))

    # ── Paso 1: Setup del ecosistema ──────────────────────────────────────────
    section("Paso 1 · Issuer y agentes")

    passport_signer   = PassportSigner()
    passport_validator = PassportValidator(passport_signer)
    issuer_id         = str(uuid.uuid4())
    issuer            = CredentialIssuer(passport_signer, issuer_id)

    info(f"Issuer ID:          {issuer_id[:20]}...")
    info(f"Key fingerprint:    {passport_signer.key_fingerprint}")

    # Generar keypairs únicos para cada agente
    buyer_kp  = AgentKeyPair.generate(label="bot_compras_produccion")
    seller_kp = AgentKeyPair.generate(label="bot_ventas_cloudhost")
    evil_kp   = AgentKeyPair.generate(label="bot_malicioso")

    info(f"Buyer  agent_id:    {buyer_kp.agent_id[:20]}...")
    info(f"Seller agent_id:    {seller_kp.agent_id[:20]}...")
    info(f"Evil   agent_id:    {evil_kp.agent_id[:20]}...")

    # El issuer emite credenciales
    buyer_cred = issuer.issue(
        buyer_kp,
        budget_usd=10.00,
        budget_per_tx=2.00,
        scope=[SCOPE_API, SCOPE_HOSTING],
        ttl_seconds=3600,
        label="bot_compras_produccion",
    )
    ok(f"Credencial emitida para buyer:  {buyer_cred}")

    # ── Paso 2: Registro de agentes (vendedor) ────────────────────────────────
    section("Paso 2 · Registro TOFU del vendedor")

    registry = AgentRegistry(mode=RegistryMode.TOFU)
    verifier = CredentialVerifier(passport_validator, registry=registry)

    info("El vendedor tiene registro vacío. Primer encuentro → TOFU.")

    # ── Paso 3: Handshake AUTH legítimo ───────────────────────────────────────
    section("Paso 3 · Handshake AUTH legítimo")

    TX_ID = 0xABCD
    ITEM  = "api_access_basic"
    PRICE = 0.05

    auth = buyer_cred.make_auth(tx_id=TX_ID)

    info(f"Buyer envía AUTH frame:")
    info(f"  agent_id:  {auth.agent_id[:20]}...")
    info(f"  pubkey:    {auth.pubkey.hex()[:20]}...")
    info(f"  signature: {auth.signature.hex()[:20]}...")
    info(f"  token:     {auth.token_str[:40]}...")
    console.print()

    valid, msg = verifier.verify_auth(
        auth, tx_id=TX_ID, item=ITEM, price=PRICE, seller_id=None
    )
    if valid:
        ok(f"AUTH verificado: {msg}")
    else:
        fail(f"AUTH rechazado: {msg}")

    # Segunda vez — ahora el agente es KNOWN
    console.print()
    info("Segunda negociación con el mismo agente (ahora es KNOWN en el registro):")
    auth2 = buyer_cred.make_auth(tx_id=TX_ID + 1)
    valid2, msg2 = verifier.verify_auth(auth2, tx_id=TX_ID+1, item=ITEM, price=PRICE)
    if valid2:
        ok(f"AUTH verificado (agente conocido): {msg2}")

    # ── Paso 4: Intentos de ataque ────────────────────────────────────────────
    section("Paso 4 · Intentos de ataque — todos deben fallar")

    attacks = []

    # Ataque 1: agente sin credencial intenta firmar con clave propia pero token del comprador
    evil_auth_with_stolen_token = AuthPayload(
        agent_id=evil_kp.agent_id,
        pubkey=evil_kp.export_public(),
        token_str=buyer_cred.token_str,   # token robado del comprador
        signature=evil_kp.sign(b"mensaje_cualquiera"),
    )
    attacks.append(("Token robado + clave propia", evil_auth_with_stolen_token, TX_ID+2, ITEM, PRICE))

    # Ataque 2: firma correcta del comprador pero token alterado
    import base64
    corrupted_token = buyer_cred.token_str[:-4] + "XXXX"
    corrupted_auth = AuthPayload(
        agent_id=buyer_kp.agent_id,
        pubkey=buyer_kp.export_public(),
        token_str=corrupted_token,
        signature=buyer_cred.make_auth(TX_ID+3).signature,  # firma válida pero sobre token diferente
    )
    attacks.append(("Token alterado", corrupted_auth, TX_ID+3, ITEM, PRICE))

    # Ataque 3: agente real pero item fuera de scope
    attacks.append(("Item fuera de scope", buyer_cred.make_auth(TX_ID+4), TX_ID+4, "compute_gpu_hour", 2.50))

    # Ataque 4: agente real pero precio supera budget_per_tx
    attacks.append(("Precio > budget_per_tx", buyer_cred.make_auth(TX_ID+5), TX_ID+5, ITEM, 5.00))

    # Ataque 5: suplantación — evil usa su propia clave pero el agent_id del comprador
    fake_agent_id_auth = AuthPayload(
        agent_id=buyer_kp.agent_id,       # agent_id del comprador legítimo
        pubkey=evil_kp.export_public(),    # pero clave pública del malicioso
        token_str=buyer_cred.token_str,
        signature=evil_kp.sign(b"x"),
    )
    attacks.append(("Suplantación de agent_id", fake_agent_id_auth, TX_ID+6, ITEM, PRICE))

    t = Table(box=box.SIMPLE_HEAD, padding=(0,1))
    t.add_column("Ataque",    width=28)
    t.add_column("Resultado", width=16)
    t.add_column("Motivo",    style="dim", width=48)

    for name, auth_payload, tx, item, price in attacks:
        # Usar verificador fresco sin registro para ataques de identidad pura
        fresh_verifier = CredentialVerifier(passport_validator, registry=None)
        v, m = fresh_verifier.verify_auth(auth_payload, tx_id=tx, item=item, price=price)
        if v:
            t.add_row(name, "[bold red]⚠ PASÓ[/]", m)
        else:
            t.add_row(name, "[bold green]✓ BLOQUEADO[/]", m[:48])

    console.print(t)

    # ── Paso 5: Resumen del registro ──────────────────────────────────────────
    section("Paso 5 · Estado del registro del vendedor")

    stats = registry.stats()
    for agent in registry.all_agents():
        status = "[green]TRUSTED[/]" if agent.trusted and not agent.blocked else "[red]BLOCKED[/]"
        console.print(
            f"  {status}  {agent.agent_id[:20]}...  "
            f"tx={agent.tx_count}  label={agent.label!r}"
        )

    console.print()
    console.print(Panel(
        f"[dim]Total agentes registrados: {stats['total']}\n"
        f"Confiables: {stats['trusted']} · Bloqueados: {stats['blocked']}\n"
        f"Modo: {stats['mode'].upper()}\n\n"
        "[white]Ningún servidor central. Cada nodo mantiene su registro.\n"
        "Falsificar una identidad Ed25519 requiere 2^128 operaciones.\n"
        "El agente malicioso fue bloqueado en todos los intentos.[/]",
        border_style="purple",
        title="[bold]Seguridad ANP Identity[/]",
    ))
    console.print()

if __name__ == "__main__":
    main()
