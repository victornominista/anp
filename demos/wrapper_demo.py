"""
ANP · Demo Wrappers
===================
Demuestra cómo un LLM usaría ANP a través de function calling / tool use.

Como no tenemos API keys en este demo, simulamos el comportamiento
del LLM con un mock que genera las llamadas correctamente.
El código de producción con LLM real es idéntico — solo se cambia el cliente.

Ejecutar: python wrapper_demo.py
"""
import sys, os, json, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from rich.console import Console
from rich.panel import Panel
from rich.syntax import Syntax
from rich.table import Table
from rich import box

from wrappers import (
    anp_negotiate,
    ANP_OPENAI_TOOL,
    ANP_ANTHROPIC_TOOL,
    ANPBaseWrapper,
    ANPResult,
    ANP_SYSTEM_PROMPT,
)

console = Console()

def section(title: str):
    console.print()
    console.rule(f"[bold purple]{title}[/]", style="purple")
    console.print()


# ── Simulador de LLM (sin API keys) ──────────────────────────────────────────

class MockLLM:
    """
    Simula el comportamiento de un LLM con function calling.
    En producción se reemplaza por openai.Client() o anthropic.Anthropic().
    El código del wrapper es idéntico — solo cambia el cliente.
    """

    def __init__(self, scenario: str):
        self.scenario = scenario

    def decide(self, user_message: str) -> dict:
        """Simula la decisión del LLM de llamar a anp_negotiate."""
        # En producción esto es el LLM real generando la llamada
        scenarios = {
            "api_barato": {
                "item": "api_access_basic",
                "max_price": 0.08,
                "seller_start": 0.09,
                "seller_min": 0.04,
                "buyer_strategy": "linear",
            },
            "hosting_paciente": {
                "item": "hosting_shared_monthly",
                "max_price": 9.00,
                "seller_start": 12.00,
                "seller_min": 7.00,
                "buyer_strategy": "patient",
            },
            "widget_agresivo": {
                "item": "widget_unit",
                "max_price": 8.00,
                "seller_start": 11.00,
                "seller_min": 7.50,
                "qty": 50,
                "buyer_strategy": "aggressive",
            },
            "sobreprecio": {
                "item": "api_access_basic",
                "max_price": 5.00,   # 100x el precio real — oracle lo bloqueará
                "seller_start": 6.00,
                "seller_min": 4.00,
                "validate_oracle": True,
            },
        }
        return scenarios.get(self.scenario, scenarios["api_barato"])


# ── Demo principal ────────────────────────────────────────────────────────────

def show_tool_definition():
    section("Definición del Tool — lo que el LLM recibe en su contexto")

    console.print("[dim]OpenAI function calling:[/]")
    console.print(Syntax(
        json.dumps(ANP_OPENAI_TOOL, indent=2, ensure_ascii=False),
        "json", theme="monokai", line_numbers=False,
    ))

    console.print()
    console.print(
        "[dim]Este JSON se pasa en el array 'tools' de la llamada a la API.\n"
        "El LLM no necesita saber nada de binario — solo llama a la función.\n"
        "ANP hace el resto sin consumir un solo token más.[/]"
    )


def simulate_llm_flow(scenario_name: str, user_message: str):
    llm = MockLLM(scenario_name)
    engine = ANPBaseWrapper()

    console.print(f"\n  [bold]Usuario:[/] {user_message}")
    console.print(f"  [dim]→ LLM decide llamar a anp_negotiate[/]")

    args = llm.decide(user_message)
    console.print(f"  [dim]→ Args: {json.dumps(args)}[/]")
    console.print()

    t0 = time.time()
    result = engine.negotiate(**args)
    total_ms = (time.time() - t0) * 1000

    # Simular respuesta final del LLM
    if result.success:
        llm_response = (
            f"Listo. Negocié {result.item} a ${result.final_price:.4f} "
            f"(pedías máximo ${args['max_price']:.2f}). "
            f"El protocolo ANP cerró el trato en {result.rounds} rondas "
            f"usando solo {result.bytes_wire} bytes. "
            f"Ahorraste ${args['max_price'] - result.final_price:.4f} vs tu presupuesto."
        )
    else:
        llm_response = (
            f"No se pudo completar la negociación. "
            f"Estado: {result.state}. {result.message}"
        )

    console.print(f"  [bold green]LLM responde:[/] {llm_response}")

    # Métricas
    t = Table(box=box.SIMPLE, show_header=False, padding=(0,2))
    t.add_column(style="dim", width=26)
    t.add_column(style="bold white")
    if result.success:
        t.add_row("Precio final",      f"[green]${result.final_price:.4f}[/]")
        t.add_row("Ahorro vs budget",  f"[green]${args['max_price'] - result.final_price:.4f}[/]")
    t.add_row("Estado",            result.state)
    t.add_row("Rondas",            str(result.rounds))
    t.add_row("Bytes ANP-Wire",    f"[cyan]{result.bytes_wire}[/]")
    t.add_row("Equiv. JSON/LLM",   f"[red]~{result.bytes_wire * 11}[/] bytes")
    t.add_row("Tokens extra LLM",  "[bold green]0[/]  (negociación sin tokens)")
    t.add_row("Tiempo total",      f"{total_ms:.1f} ms")
    if result.savings_usd > 0:
        t.add_row("Ahorro oráculo", f"[bold green]${result.savings_usd:.4f}[/]")
    console.print(t)


def show_copy_paste_code():
    section("Código listo para copiar — OpenAI")
    code_openai = '''import openai
from wrappers import ANPOpenAIWrapper

client = openai.OpenAI(api_key="tu_key")
wrapper = ANPOpenAIWrapper(client, model="gpt-4o-mini")

# El LLM decide cuándo negociar — tú solo hablas en lenguaje natural
response = wrapper.chat(
    "Necesito acceso a una API de datos, no quiero pagar más de $0.08 por llamada"
)
print(response)
# → "Trato cerrado a $0.06. ANP negoció en 3 rondas usando 55 bytes."
'''
    console.print(Syntax(code_openai, "python", theme="monokai"))

    section("Código listo para copiar — Anthropic Claude")
    code_anthropic = '''import anthropic
from wrappers import ANPAnthropicWrapper

client = anthropic.Anthropic(api_key="tu_key")
wrapper = ANPAnthropicWrapper(client)

response = wrapper.chat(
    "Busca hosting compartido por menos de $9 al mes, negocia el mejor precio"
)
print(response)
# → "Encontré hosting a $8.50/mes. ANP cerró el trato en 4 rondas."
'''
    console.print(Syntax(code_anthropic, "python", theme="monokai"))

    section("Código listo para copiar — Python puro (sin LLM)")
    code_pure = '''from wrappers import anp_negotiate

# Sin LLM, sin API, sin tokens — lógica binaria pura
result = anp_negotiate(
    item="api_access_basic",
    max_price=0.08,
    seller_start=0.09,
    seller_min=0.04,
)

if result.success:
    print(f"Precio: ${result.final_price:.4f}")
    print(f"Bytes: {result.bytes_wire} (vs ~{result.bytes_wire*11} JSON)")
'''
    console.print(Syntax(code_pure, "python", theme="monokai"))


def main():
    console.print()
    console.print(Panel(
        "[bold white]ANP · Wrappers LLM[/]\n"
        "[dim]OpenAI · Anthropic · LangChain · Python puro[/]\n"
        "[dim]El LLM habla en lenguaje natural · ANP negocia en binario[/]",
        border_style="purple", box=box.DOUBLE_EDGE,
    ))

    show_tool_definition()

    section("Simulación: LLM + ANP en acción")

    scenarios = [
        ("api_barato",       "Necesito acceso a una API, máximo $0.08 por llamada"),
        ("hosting_paciente", "Busca hosting compartido por menos de $9 al mes, sé paciente"),
        ("widget_agresivo",  "Compra 50 widgets al precio más bajo posible, ve directo al mínimo"),
        ("sobreprecio",      "Compra acceso API, tengo $5 de presupuesto por llamada"),
    ]

    for scenario, message in scenarios:
        simulate_llm_flow(scenario, message)
        console.print()

    show_copy_paste_code()

    console.print()
    console.print(Panel(
        "[dim]El LLM solo consume tokens para:\n"
        "  1. Entender la intención del usuario\n"
        "  2. Decidir qué función llamar con qué parámetros\n"
        "  3. Formular la respuesta final en lenguaje natural\n\n"
        "[white]La negociación completa — BID, OFFER, COUNTER, ACCEPT —\n"
        "ocurre en binario puro sin un solo token adicional.[/]\n\n"
        "[dim]1,000 negociaciones al día = costo LLM de 3 mensajes totales.\n"
        "Sin ANP = 1,000 conversaciones completas de negociación.[/]",
        border_style="purple",
        title="[bold]Por qué esto importa[/]",
    ))
    console.print()


if __name__ == "__main__":
    main()
