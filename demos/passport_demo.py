"""
ANP · Demo Passport
===================
Muestra el ciclo completo de un ANP-Pass:
  1. Issuer crea y firma el token
  2. Agente lo recibe y lo presenta
  3. Validator verifica permisos por transacción
  4. Se simulan intentos legítimos y bloqueados

Ejecutar: python passport_demo.py
"""
import sys, os, time, uuid
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.text import Text
from rich import box

from anp.passport import (
    PassportSigner, PassportValidator,
    SCOPE_API, SCOPE_HOSTING, PermissionStatus,
)

console = Console()

def status_display(perm) -> tuple[str, str]:
    if perm.granted:
        return "✓ GRANTED", "bold green"
    colors = {
        PermissionStatus.DENIED_EXPIRED:  ("✗ EXPIRADO",   "red"),
        PermissionStatus.DENIED_SCOPE:    ("✗ SCOPE",      "red"),
        PermissionStatus.DENIED_BUDGET:   ("✗ BUDGET TX",  "red"),
        PermissionStatus.DENIED_TOTAL:    ("✗ SIN FONDOS", "bold red"),
        PermissionStatus.DENIED_SELLER:   ("✗ SELLER",     "red"),
        PermissionStatus.DENIED_CEILING:  ("✗ CEILING",    "red"),
        PermissionStatus.DENIED_SIG:      ("✗ FIRMA",      "bold red"),
    }
    return colors.get(perm.status, ("✗ DENEGADO", "red"))

def main():
    console.print()
    console.print(Panel(
        "[bold white]ANP · Passport · ANP-Pass Token[/]\n"
        "[dim]Capacidad limitada · Scope granular · Anti-replay · Bitcoin-style[/]",
        border_style="purple", box=box.DOUBLE_EDGE,
    ))

    # ── 1. El issuer (humano/sistema) crea su clave y emite tokens ────────────
    console.print("\n[bold]Paso 1 · Issuer crea clave secreta y emite tokens[/]\n")

    signer = PassportSigner()  # clave aleatoria de 32 bytes
    validator = PassportValidator(signer)

    issuer_id = str(uuid.uuid4())
    agent_a   = str(uuid.uuid4())
    agent_b   = str(uuid.uuid4())

    console.print(f"  [dim]Issuer ID:[/]         {issuer_id[:16]}...")
    console.print(f"  [dim]Key fingerprint:[/]   {signer.key_fingerprint}")

    # Token A: agente de compras de APIs (presupuesto moderado)
    token_a, token_str_a = signer.issue(
        agent_id=agent_a,
        issuer_id=issuer_id,
        budget_usd=5.00,
        budget_per_tx=0.50,
        scope=[SCOPE_API],
        ttl_seconds=3600,
        label="bot_compras_api",
        max_price_ceiling=0.30,
    )

    # Token B: agente de hosting (presupuesto mayor, sellers específicos)
    token_b, token_str_b = signer.issue(
        agent_id=agent_b,
        issuer_id=issuer_id,
        budget_usd=50.00,
        budget_per_tx=15.00,
        scope=[SCOPE_HOSTING],
        ttl_seconds=86400,
        label="bot_compras_hosting",
        allowed_sellers=["seller_cloudflare", "seller_aws"],
        blocked_sellers=["seller_spam"],
    )

    console.print(f"\n  [dim]Token A (API bot):[/]     {token_str_a[:40]}...")
    console.print(f"  [dim]Tamaño token A:[/]       {len(token_str_a)} bytes")
    console.print(f"  [dim]Token B (Hosting bot):[/] {token_str_b[:40]}...")
    console.print(f"  [dim]Tamaño token B:[/]       {len(token_str_b)} bytes")

    # ── 2. Tabla de intentos de transacción ───────────────────────────────────
    console.print("\n[bold]Paso 2 · Verificación de permisos por transacción[/]\n")

    checks = [
        # (token_str, item, price, seller, descripción)
        (token_str_a, "api_access_basic",   0.05,  None,                "API · precio normal"),
        (token_str_a, "api_access_premium", 0.15,  None,                "API · precio alto — OK"),
        (token_str_a, "api_access_basic",   0.35,  None,                "API · supera ceiling $0.30"),
        (token_str_a, "api_access_basic",   0.60,  None,                "API · supera budget_per_tx $0.50"),
        (token_str_a, "hosting_shared_monthly", 8.99, None,             "Hosting · fuera de scope"),
        (token_str_b, "hosting_shared_monthly", 8.99, "seller_cloudflare", "Hosting · seller en whitelist ✓"),
        (token_str_b, "hosting_shared_monthly", 8.99, "seller_aws",     "Hosting · seller en whitelist ✓"),
        (token_str_b, "hosting_shared_monthly", 8.99, "seller_desconocido", "Hosting · seller NO en whitelist"),
        (token_str_b, "hosting_shared_monthly", 8.99, "seller_spam",    "Hosting · seller en BLACKLIST"),
        (token_str_b, "hosting_vps_monthly", 24.00, "seller_aws",       "Hosting VPS · OK"),
        ("token_falso_manipulado_abc123", "api_access_basic", 0.05, None, "Firma inválida (token falso)"),
    ]

    t = Table(box=box.SIMPLE_HEAD, padding=(0, 1))
    t.add_column("Token",    style="dim", width=12)
    t.add_column("Item",               width=22)
    t.add_column("Precio",  justify="right", width=8)
    t.add_column("Seller",  style="dim", width=18)
    t.add_column("Resultado",          width=16)
    t.add_column("Razón",   style="dim", width=38)

    for tok_str, item, price, seller, desc in checks:
        perm = validator.check(tok_str, item=item, price=price, seller_id=seller)
        label, color = status_display(perm)
        tok_label = "Token-A" if tok_str == token_str_a else (
                    "Token-B" if tok_str == token_str_b else "FALSO")
        t.add_row(
            tok_label,
            item,
            f"${price:.2f}",
            seller or "—",
            f"[{color}]{label}[/]",
            perm.reason[:38],
        )

    console.print(t)

    # ── 3. Ciclo de vida: gastar el budget ────────────────────────────────────
    console.print("\n[bold]Paso 3 · Agotando el presupuesto del Token-A[/]\n")

    spent = 0.0
    for i in range(1, 15):
        perm = validator.check(token_str_a, item="api_access_basic", price=0.05)
        if perm.granted:
            validator.record_spend(token_a, 0.05)
            spent += 0.05
            bar_filled = int(spent / token_a.budget_usd * 30)
            bar = "█" * bar_filled + "░" * (30 - bar_filled)
            console.print(
                f"  Tx #{i:02d}  [green]✓[/]  "
                f"[cyan]{bar}[/]  "
                f"${spent:.2f} / ${token_a.budget_usd:.2f}"
            )
        else:
            console.print(
                f"  Tx #{i:02d}  [bold red]✗ BLOQUEADO — {perm.reason}[/]"
            )
            break

    # ── 4. Resumen de seguridad ───────────────────────────────────────────────
    console.print()
    console.print(Panel(
        "[dim]El token define exactamente qué puede hacer el agente:\n"
        "  · Cuánto puede gastar en total\n"
        "  · Cuánto por transacción\n"
        "  · Con qué categorías de items\n"
        "  · Con qué sellers específicos\n"
        "  · Hasta cuándo\n\n"
        "[white]Sin token válido → cero negociaciones.\n"
        "Sin la clave del issuer → imposible falsificar.\n"
        "Inspirado en Bitcoin: tú controlas las llaves, el agente obedece.[/]",
        border_style="purple",
        title="[bold]Seguridad ANP-Pass[/]",
    ))
    console.print()

if __name__ == "__main__":
    main()
