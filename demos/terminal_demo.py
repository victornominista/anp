"""
ANP · Demo Terminal v2
======================
Usa el NegotiationEngine real con buyer y seller configurables.

Ejecutar: python terminal_demo.py
"""
import time
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.text import Text
from rich import box

from anp.wire import Op, Frame
from anp.negotiation import (
    NegotiationEngine, BuyerAgent, SellerAgent,
    BuyerLinear, BuyerPatient, BuyerAggressive,
    SellerLinear, SellerDeadline,
)

console = Console()
BUYER_ID  = 0x0001
SELLER_ID = 0x0002

def show_frame(direction, frame, label):
    wire = frame.encode()
    hex_str = wire.hex(" ").upper()
    role = "[cyan]BUYER [/]" if frame.agent_id == BUYER_ID else "[green]SELLER[/]"
    op_color = {Op.BID:"cyan",Op.OFFER:"green",Op.COUNTER:"yellow",Op.ACCEPT:"bold green",Op.REJECT:"red"}.get(frame.op,"white")
    line = Text()
    line.append(f"  {role} ","bold")
    line.append(direction, style=f"bold {'cyan' if direction=='→' else 'green'}")
    line.append(" WIRE  ","dim")
    line.append(f"{hex_str:<40}","dim white")
    line.append(f"  [{frame.op.name}]",style=f"bold {op_color}")
    line.append(f"  {label}","white")
    console.print(line)
    time.sleep(0.25)

def run_scenario(title, buyer, seller, item):
    console.print()
    console.print(Panel(
        f"[bold white]{title}[/]\n[dim]Comprador max=${buyer.max_price:.2f}  ·  Vendedor start=${seller.start_price:.2f}  min=${seller.min_price:.2f}[/]",
        border_style="purple", box=box.ROUNDED,
    ))
    console.print()
    engine = NegotiationEngine(buyer, seller)
    result = engine.run(item=item, deadline=int(time.time())+60, on_frame=show_frame)
    console.print()
    if result.success:
        t = Table(box=box.SIMPLE, show_header=False, padding=(0,2))
        t.add_column(style="dim", width=26)
        t.add_column(style="bold white")
        t.add_row("Precio acordado", f"[bold green]${result.final_price:.2f}[/]")
        t.add_row("Rondas", str(result.rounds))
        t.add_row("Mensajes", str(len(result.frames)))
        t.add_row("Bytes ANP-Wire", f"[cyan]{result.bytes_total}[/]")
        t.add_row("Equiv. JSON", f"[red]~{result.json_equiv_bytes}[/] bytes")
        t.add_row("Tiempo", f"{result.elapsed_ms:.1f} ms")
        console.print(Panel(t, title="[bold green]✓ TRATO CERRADO[/]", border_style="green"))
    else:
        console.print(Panel(f"[bold red]✗ Sin acuerdo — {result.state.value}[/]", border_style="red"))
    return result

def main():
    console.print()
    console.print(Panel(
        "[bold white]ANP · Agent Negotiation Protocol[/]\n[dim]Binario nativo entre agentes · sin LLM · sin GPU · sin tokens[/]",
        border_style="purple", box=box.DOUBLE_EDGE,
    ))
    run_scenario("Escenario 1 · Acuerdo inmediato",
        BuyerAgent(BUYER_ID, max_price=0.10, strategy=BuyerLinear()),
        SellerAgent(SELLER_ID, start_price=0.07, min_price=0.05, strategy=SellerLinear()),
        "api_access")
    run_scenario("Escenario 2 · Comprador paciente vs vendedor firme",
        BuyerAgent(BUYER_ID, max_price=0.08, strategy=BuyerPatient(patience=2)),
        SellerAgent(SELLER_ID, start_price=0.12, min_price=0.07, strategy=SellerLinear()),
        "hosting_shared")
    run_scenario("Escenario 3 · Sin acuerdo (precios incompatibles)",
        BuyerAgent(BUYER_ID, max_price=0.04, strategy=BuyerAggressive()),
        SellerAgent(SELLER_ID, start_price=0.15, min_price=0.10, strategy=SellerDeadline()),
        "widget_unit")
    console.print()
    console.print(Panel(
        "[dim]Cero tokens LLM. Cero GPU. Cada byte = valor real moviéndose.\n[white]Este es el lenguaje nativo de los agentes.[/]",
        border_style="purple",
    ))
    console.print()

if __name__ == "__main__":
    main()
