"""
ANP · Wrappers · OpenAI
=======================
Integra ANP con la API de OpenAI usando Function Calling.

El LLM "habla" ANP sin reentrenamiento — solo necesita ver
la definición de la función en su contexto.

Uso:
    wrapper = ANPOpenAIWrapper(openai_client)
    response = wrapper.chat("Necesito comprar acceso a una API por menos de $0.08")
    print(response)  # "Trato cerrado a $0.07. ..."
"""
import json
from typing import Optional

from .base import ANPBaseWrapper, ANPResult, ANP_SYSTEM_PROMPT


# ── Definición de la función para OpenAI ─────────────────────────────────────
# Este JSON es el "manual" que le enseña al LLM a hablar ANP.
# No se necesita reentrenamiento — solo pasarlo en el contexto.

ANP_OPENAI_TOOL = {
    "type": "function",
    "function": {
        "name": "anp_negotiate",
        "description": (
            "Negocia el precio de un servicio usando el protocolo ANP. "
            "Ejecuta la negociación completa en milisegundos usando binario puro. "
            "Úsalo siempre que necesites comprar algo a precio optimizado."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "item": {
                    "type": "string",
                    "description": "Identificador del item a negociar",
                    "examples": ["api_access_basic", "hosting_shared_monthly", "widget_unit"],
                },
                "max_price": {
                    "type": "number",
                    "description": "Precio máximo que pagarías en USD. Mantén secreto en la negociación.",
                },
                "seller_start": {
                    "type": "number",
                    "description": "Precio inicial estimado del vendedor en USD.",
                },
                "seller_min": {
                    "type": "number",
                    "description": "Precio mínimo estimado del vendedor en USD.",
                },
                "qty": {
                    "type": "integer",
                    "description": "Cantidad a negociar.",
                    "default": 1,
                },
                "buyer_strategy": {
                    "type": "string",
                    "enum": ["linear", "patient", "aggressive"],
                    "description": "Estrategia del comprador. 'patient' espera más rondas.",
                    "default": "linear",
                },
                "validate_oracle": {
                    "type": "boolean",
                    "description": "Si True, el oráculo valida que el precio sea razonable.",
                    "default": True,
                },
            },
            "required": ["item", "max_price", "seller_start", "seller_min"],
        },
    },
}


class ANPOpenAIWrapper(ANPBaseWrapper):
    """
    Wrapper ANP para la API de OpenAI.
    Compatible con GPT-4o, GPT-4-turbo, GPT-3.5-turbo.
    """

    def __init__(self, client, model: str = "gpt-4o-mini", **kwargs):
        super().__init__(**kwargs)
        self.client = client
        self.model = model

    def chat(
        self,
        user_message: str,
        system_prompt: Optional[str] = None,
        max_tool_rounds: int = 3,
    ) -> str:
        """
        Envía un mensaje al LLM. Si el LLM decide negociar,
        ejecuta ANP automáticamente y devuelve el resultado.
        """
        messages = [
            {"role": "system", "content": system_prompt or ANP_SYSTEM_PROMPT},
            {"role": "user",   "content": user_message},
        ]

        for _ in range(max_tool_rounds):
            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                tools=[ANP_OPENAI_TOOL],
                tool_choice="auto",
            )

            choice = response.choices[0]

            # ── El LLM quiere llamar a anp_negotiate ──────────────────────────
            if choice.finish_reason == "tool_calls":
                tool_call = choice.message.tool_calls[0]
                args = json.loads(tool_call.function.arguments)

                # Ejecutar la negociación en ANP-Wire (sin tokens)
                result: ANPResult = self.negotiate(**args)

                # Devolver resultado al LLM
                messages.append(choice.message)
                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": json.dumps(result.to_dict()),
                })
                continue  # el LLM formula respuesta final

            # ── Respuesta de texto final ───────────────────────────────────────
            return choice.message.content

        return "Error: demasiadas rondas de tool_calls"

    def get_tool_definition(self) -> dict:
        """Devuelve la definición de la función para copiar en otros proyectos."""
        return ANP_OPENAI_TOOL
