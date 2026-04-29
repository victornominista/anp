"""
ANP · Wrappers · Anthropic Claude
==================================
Integra ANP con la API de Anthropic usando Tool Use.

Compatible con claude-3-5-sonnet, claude-3-opus, claude-sonnet-4-*.

Uso:
    wrapper = ANPAnthropicWrapper(anthropic_client)
    response = wrapper.chat("Busca hosting por menos de $10 al mes")
    print(response)
"""
import json
from typing import Optional

from .base import ANPBaseWrapper, ANPResult, ANP_SYSTEM_PROMPT


# ── Definición del tool para Anthropic ───────────────────────────────────────

ANP_ANTHROPIC_TOOL = {
    "name": "anp_negotiate",
    "description": (
        "Negocia el precio de un servicio usando el protocolo ANP (Agent Negotiation Protocol). "
        "Ejecuta miles de micro-negociaciones en milisegundos usando binario puro entre agentes. "
        "Costo de tokens: cero durante la negociación. "
        "Úsalo cuando el usuario quiera comprar algo a precio optimizado."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "item": {
                "type": "string",
                "description": "Identificador del item. Ejemplos: api_access_basic, hosting_shared_monthly, widget_unit",
            },
            "max_price": {
                "type": "number",
                "description": "Precio máximo a pagar en USD. Este valor es secreto durante la negociación.",
            },
            "seller_start": {
                "type": "number",
                "description": "Precio inicial del vendedor en USD (estimado si no se conoce).",
            },
            "seller_min": {
                "type": "number",
                "description": "Precio mínimo del vendedor en USD (estimado si no se conoce).",
            },
            "qty": {
                "type": "integer",
                "description": "Cantidad a negociar. Default: 1",
            },
            "buyer_strategy": {
                "type": "string",
                "enum": ["linear", "patient", "aggressive"],
                "description": "Estrategia: linear=gradual, patient=espera rondas, aggressive=va al máximo directo.",
            },
            "validate_oracle": {
                "type": "boolean",
                "description": "Validar precio vs oráculo de mercado antes de negociar. Default: true",
            },
        },
        "required": ["item", "max_price", "seller_start", "seller_min"],
    },
}


class ANPAnthropicWrapper(ANPBaseWrapper):
    """
    Wrapper ANP para la API de Anthropic.
    Compatible con todos los modelos Claude 3+.
    """

    def __init__(
        self,
        client,
        model: str = "claude-sonnet-4-20250514",
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.client = client
        self.model = model

    def chat(
        self,
        user_message: str,
        system_prompt: Optional[str] = None,
        max_tool_rounds: int = 3,
    ) -> str:
        messages = [{"role": "user", "content": user_message}]

        for _ in range(max_tool_rounds):
            response = self.client.messages.create(
                model=self.model,
                max_tokens=1024,
                system=system_prompt or ANP_SYSTEM_PROMPT,
                tools=[ANP_ANTHROPIC_TOOL],
                messages=messages,
            )

            # ── Claude quiere usar anp_negotiate ──────────────────────────────
            if response.stop_reason == "tool_use":
                # Agregar respuesta del asistente al historial
                messages.append({"role": "assistant", "content": response.content})

                # Procesar cada tool_use block
                tool_results = []
                for block in response.content:
                    if block.type == "tool_use" and block.name == "anp_negotiate":
                        result: ANPResult = self.negotiate(**block.input)
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": json.dumps(result.to_dict()),
                        })

                messages.append({"role": "user", "content": tool_results})
                continue

            # ── Respuesta de texto final ───────────────────────────────────────
            for block in response.content:
                if hasattr(block, "text"):
                    return block.text

        return "Error: demasiadas rondas de tool_use"

    def get_tool_definition(self) -> dict:
        return ANP_ANTHROPIC_TOOL
