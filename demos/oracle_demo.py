"""
ANP · Demo Oracle
=================
Muestra en vivo cuánto USD ahorra el oráculo bloqueando sobreprecios.
Este número es el argumento de venta del sistema.

Ejecutar: python oracle_demo.py
"""
import sys, os, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich import box
from anp.oracle import Oracle
from anp.oracle.validator import ValidationStatus

console = Console()

FEED_PATH = os.path.join(os.path.dirname(__file__), "../anp/oracle/feeds/sample_prices.json")

# Simulación: un agente LLM "alucina" estos precios (errores reales de LLMs)
HALLUCINATED_OFFERS = [
    # (item,                    precio_alucinado, precio_real, descripción)
    ("api_access_basic",        0.05,   "normal — dentro de rango"),
    ("api_access_basic",        0.08,   "ligeramente alto — WARN"),
    ("api_access_basic",        0.50,   "ALUCINACIÓN: 10x el precio real"),
    ("hosting_shared_monthly",  8.50,   "normal — OK"),
    ("hosting_shared_monthly",  45.00,  "ALUCINACIÓN: error de decimal"),
    ("hosting_vps_monthly",     24.00,  "normal — OK"),
    ("hosting_vps_monthly",     240.00, "ALUCINACIÓN: extra cero"),
    ("widget_unit",             10.00,  "normal — OK"),
    ("widget_unit",             1000.00,"ALUCINACIÓN: ,$10 → $1000 error"),
    ("llm_token_1k",            0.002,  "normal — OK"),
    ("llm_token_1k",            2.00,   "ALUCINACIÓN: olvidó los decimales"),
    ("item_desconocido",        99.99,  "item no está en el feed"),
]

def status_style(status: ValidationStatus) -> tuple[str, str]:
    return {
        ValidationStatus.OK:              ("✓ OK",              "green"),
        ValidationStatus.WARN:            ("⚠ WARN",            "yellow"),
        ValidationStatus.BLOCKED_CEILING: ("✗ BLOQUEADO",       "bold red"),
        ValidationStatus.BLOCKED_FLOOR:   ("✗ BLOQUEADO FLOOR", "bold red"),
        ValidationStatus.NEEDS_HUMAN:     ("⚠ HUMANO",          "yellow"),
        ValidationStatus.UNKNOWN_ITEM:    ("? DESCONOCIDO",      "dim"),
    }.get(status, ("?", "white"))

def main():
    oracle = Oracle.from_json(
        FEED_PATH,
        x402_endpoint="https://payments.example.com/x402",
        x402_threshold_usd=1.0,
    )

    console.print()
    console.print(Panel(
        "[bold white]ANP · Oracle de Precios[/]\n"
        "[dim]Protección contra sobreprecios · Integración x402/MPP · Valor medible en USD[/]",
        border_style="purple", box=box.DOUBLE_EDGE,
    ))
    console.print(f"\n  [dim]Feed cargado:[/] {len(oracle.feed)} items\n")

    # Tabla de resultados
    t = Table(box=box.SIMPLE_HEAD, show_header=True, padding=(0, 1))
    t.add_column("Item",            style="dim",        width=28)
    t.add_column("Ofrecido",        justify="right",    width=10)
    t.add_column("Mercado",         justify="right",    width=10)
    t.add_column("Desviación",      justify="right",    width=11)
    t.add_column("Estado",          width=16)
    t.add_column("Ahorro USD",      justify="right",    width=12)
    t.add_column("x402",            justify="center",   width=6)
    t.add_column("Descripción",     style="dim",        width=34)

    for item, price, desc in HALLUCINATED_OFFERS:
        result = oracle.check_buy(item, price)
        label, color = status_style(result.status)

        dev_str = f"{result.deviation_pct:.1f}%" if result.deviation_pct is not None else "—"
        base_str = f"${result.base_price:.4f}" if result.base_price else "—"
        savings_str = f"[bold green]${result.savings_usd:.4f}[/]" if result.savings_usd > 0 else "[dim]—[/]"
        x402_str = "[cyan]✓[/]" if result.x402_required else "[dim]—[/]"

        t.add_row(
            item,
            f"${price:.4f}",
            base_str,
            dev_str,
            f"[{color}]{label}[/]",
            savings_str,
            x402_str,
            desc,
        )
        time.sleep(0.05)

    console.print(t)

    # Reporte de ahorros
    rep = oracle.savings_report()
    console.print()

    savings_table = Table(box=box.SIMPLE, show_header=False, padding=(0, 2))
    savings_table.add_column(style="dim", width=30)
    savings_table.add_column(style="bold white")
    savings_table.add_row("Transacciones validadas",   str(rep["total_validated"]))
    savings_table.add_row("Bloqueadas (sobreprecio)",  f"[bold red]{rep['total_blocked']}[/]")
    savings_table.add_row("Advertencias",              str(rep["total_warned"]))
    savings_table.add_row("Tasa de bloqueo",           f"{rep['block_rate_pct']:.1f}%")
    savings_table.add_row("Sobreprecio detectado",     f"[red]${rep['overprice_detected_usd']:.4f} USD[/]")
    savings_table.add_row("💰 TOTAL AHORRADO",         f"[bold green]${rep['total_savings_usd']:.4f} USD[/]")

    console.print(Panel(
        savings_table,
        title="[bold green]Valor Medible del Oracle[/]",
        border_style="green",
    ))

    console.print()
    console.print(Panel(
        "[dim]Cada bloqueo = dinero real que el agente no pagó de más.\n"
        "A 1,000 negociaciones/día con 20% de alucinaciones LLM:\n"
        "[white]el oráculo ahorra cientos de USD al mes en piloto automático.[/]\n\n"
        "[dim]x402 activado en transacciones ≥ $1.00 → canal de micropago verificado.[/]",
        border_style="purple",
    ))
    console.print()

if __name__ == "__main__":
    main()
