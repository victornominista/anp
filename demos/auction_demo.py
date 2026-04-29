"""
ANP · Demo Subasta Multi-Party
==============================
1 comprador vs N vendedores simultáneos.
Tres modos de subasta: LOWEST_PRICE, FIRST_TO_MATCH, VICKREY.

Ejecutar: python auction_demo.py
"""
import sys, os, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.text import Text
from rich import box

from anp.wire import Op, Frame
from anp.negotiation import (
    BuyerAgent, SellerAgent,
    BuyerLinear, SellerLinear, SellerDeadline,
    AuctionEngine, AuctionMode, AuctionResult,
)

console = Console()

BUYER_ID = 0x0001


def show_frame(direction: str, frame: Frame, label: str):
    is_buyer = frame.agent_id == BUYER_ID
    role_color = "cyan" if is_buyer else "green"
    role = "BUYER  " if is_buyer else f"SELLER "
    op_color = {
        Op.BID: "cyan", Op.OFFER: "green", Op.COUNTER: "yellow",
        Op.ACCEPT: "bold green", Op.REJECT: "red",
    }.get(frame.op, "white")
    dir_color = "cyan" if direction == "→" else "green"

    line = Text()
    line.append(f"  [{role_color}]{role}[/] ")
    line.append(direction, style=f"bold {dir_color}")
    line.append(f"  [{frame.op.name:<8}]", style=f"bold {op_color}")
    line.append(f"  {label}", style="white")
    console.print(line)
    time.sleep(0.08)


def show_result(result: AuctionResult, mode_name: str):
    console.print()

    # Tabla de vendedores
    t = Table(box=box.SIMPLE_HEAD, padding=(0, 1), show_header=True)
    t.add_column("Vendedor",      width=16)
    t.add_column("Inicio",  justify="right", width=8)
    t.add_column("Mínimo",  justify="right", width=8)
    t.add_column("Final",   justify="right", width=10)
    t.add_column("Rondas",  justify="center", width=7)
    t.add_column("Estado",  width=14)

    for r in result.seller_results:
        if r["won"]:
            status = "[bold green]★ GANÓ[/]"
            final_str = f"[bold green]${r['final_offer']:.4f}[/]"
        elif not r["active"]:
            status = "[dim]eliminado[/]"
            final_str = f"[dim]${r['final_offer']:.4f}[/]" if r["final_offer"] else "[dim]—[/]"
        else:
            status = "[dim]perdió[/]"
            final_str = f"${r['final_offer']:.4f}" if r["final_offer"] else "—"

        t.add_row(
            r["label"],
            f"${r['start_price']:.4f}",
            f"${r['min_price']:.4f}",
            final_str,
            str(r["rounds"]),
            status,
        )
    console.print(t)

    # Panel de resultado
    if result.success:
        pay_note = ""
        if result.mode == AuctionMode.VICKREY and result.payment_price != result.winning_price:
            pay_note = f"\n[dim]Vickrey: gana ${result.winning_price:.4f}, paga ${result.payment_price:.4f}[/]"

        summary = Table(box=box.SIMPLE, show_header=False, padding=(0, 2))
        summary.add_column(style="dim", width=22)
        summary.add_column(style="bold white")
        summary.add_row("Ganador",           f"[bold green]{result.winner_label}[/]")
        summary.add_row("Precio ganador",    f"[bold green]${result.winning_price:.4f}[/]")
        if result.mode == AuctionMode.VICKREY:
            summary.add_row("Precio que paga", f"[cyan]${result.payment_price:.4f}[/]")
        summary.add_row("Ahorro vs inicio",  f"[green]${result.savings_vs_start:.4f}[/]" if result.savings_vs_start else "—")
        summary.add_row("Rondas",            str(result.rounds))
        summary.add_row("Vendedores",        f"{result.sellers_count} total, {result.sellers_active_end} al final")
        summary.add_row("Bytes ANP-Wire",    f"[cyan]{result.bytes_total}[/]")
        summary.add_row("Equiv. JSON",       f"[red]~{result.json_equiv_bytes}[/]")
        summary.add_row("Tiempo",            f"{result.elapsed_ms:.1f} ms")

        console.print(Panel(
            summary,
            title=f"[bold green]✓ {mode_name} — TRATO CERRADO[/]{pay_note}",
            border_style="green",
        ))
    else:
        console.print(Panel(
            f"[bold red]✗ Sin acuerdo — ningún vendedor llegó al presupuesto del comprador[/]",
            border_style="red",
        ))


def run_auction(title: str, mode: AuctionMode, buyer: BuyerAgent, sellers: list, item: str):
    console.print()
    console.print(Panel(
        f"[bold white]{title}[/]\n"
        f"[dim]Modo: {mode.value}  ·  "
        f"Comprador max=${buyer.max_price:.4f} (secreto)  ·  "
        f"{len(sellers)} vendedores[/]",
        border_style="purple", box=box.ROUNDED,
    ))
    console.print()

    engine = AuctionEngine(buyer, sellers, mode=mode, noise=True, on_frame=show_frame)
    return engine.run(item=item, tx_id=0x3000 + list(AuctionMode).index(mode))


def main():
    console.print()
    console.print(Panel(
        "[bold white]ANP · Subasta Multi-Party[/]\n"
        "[dim]1 comprador vs N vendedores · Binario puro · Anti-explotación noise[/]",
        border_style="purple", box=box.DOUBLE_EDGE,
    ))

    item = "api_access_basic"

    # ── Escenario 1: LOWEST_PRICE — 4 vendedores compitiendo ─────────────────
    result1 = run_auction(
        "Modo 1 · LOWEST_PRICE — 4 vendedores compitiendo",
        AuctionMode.LOWEST_PRICE,
        buyer=BuyerAgent(BUYER_ID, max_price=0.08, strategy=BuyerLinear()),
        sellers=[
            _make_seller(0x0010, 0.12, 0.06, "CloudHost-A"),
            _make_seller(0x0011, 0.10, 0.07, "DataCenter-B"),
            _make_seller(0x0012, 0.11, 0.05, "FastAPI-C"),
            _make_seller(0x0013, 0.13, 0.08, "MicroServ-D"),
        ],
        item=item,
    )
    show_result(result1, "LOWEST_PRICE")

    # ── Escenario 2: FIRST_TO_MATCH — velocidad ───────────────────────────────
    result2 = run_auction(
        "Modo 2 · FIRST_TO_MATCH — gana quien baje primero al precio del comprador",
        AuctionMode.FIRST_TO_MATCH,
        buyer=BuyerAgent(BUYER_ID, max_price=0.07, strategy=BuyerLinear()),
        sellers=[
            _make_seller(0x0020, 0.10, 0.06, "Speed-A",   strategy="deadline"),
            _make_seller(0x0021, 0.09, 0.07, "Speed-B",   strategy="linear"),
            _make_seller(0x0022, 0.11, 0.05, "Speed-C",   strategy="deadline"),
        ],
        item=item,
    )
    show_result(result2, "FIRST_TO_MATCH")

    # ── Escenario 3: VICKREY — honestidad incentivada ─────────────────────────
    result3 = run_auction(
        "Modo 3 · VICKREY — gana el más barato, paga el segundo precio",
        AuctionMode.VICKREY,
        buyer=BuyerAgent(BUYER_ID, max_price=0.09, strategy=BuyerLinear()),
        sellers=[
            _make_seller(0x0030, 0.12, 0.05, "Vickrey-A"),
            _make_seller(0x0031, 0.11, 0.06, "Vickrey-B"),
            _make_seller(0x0032, 0.10, 0.07, "Vickrey-C"),
        ],
        item=item,
    )
    show_result(result3, "VICKREY")

    # ── Resumen comparativo ───────────────────────────────────────────────────
    console.print()
    compare = Table(title="Comparación de modos", box=box.SIMPLE_HEAD, padding=(0, 2))
    compare.add_column("Modo",         width=18)
    compare.add_column("Precio",  justify="right", width=10)
    compare.add_column("Rondas",  justify="center", width=7)
    compare.add_column("Bytes",   justify="right", width=8)
    compare.add_column("Cuándo usar",  style="dim", width=34)

    rows = [
        (result1, "LOWEST_PRICE",    "Maximizar ahorro, sin urgencia"),
        (result2, "FIRST_TO_MATCH",  "Necesitas cerrar rápido"),
        (result3, "VICKREY",         "Incentiva precios honestos (B2B)"),
    ]
    for r, name, when in rows:
        price_str = f"[green]${r.winning_price:.4f}[/]" if r.success else "[red]sin acuerdo[/]"
        compare.add_row(name, price_str, str(r.rounds), str(r.bytes_total), when)

    console.print(compare)
    console.print()
    console.print(Panel(
        "[dim]Anti-explotación: ruido ±8% sobre cada precio calculado.\n"
        "El vendedor no puede inferir el algoritmo del comprador observando los pasos.\n\n"
        "[white]Los tres modos corren sobre el mismo protocolo ANP-Wire.\n"
        "El comprador nunca sabe cuántos vendedores hay.\n"
        "Los vendedores nunca saben el max_price del comprador.[/]",
        border_style="purple",
    ))
    console.print()


def _make_seller(agent_id, start, min_price, label, strategy="linear"):
    from anp.negotiation import SellerLinear, SellerDeadline
    strat = SellerDeadline() if strategy == "deadline" else SellerLinear()
    s = SellerAgent(agent_id, start_price=start, min_price=min_price, strategy=strat)
    s.label = label
    return s


if __name__ == "__main__":
    main()
