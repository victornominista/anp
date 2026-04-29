"""
ANP · Wrappers
==============
Adaptadores para que LLMs hablen el protocolo ANP.

Importaciones rápidas:
    from wrappers import ANPOpenAIWrapper         # OpenAI function calling
    from wrappers import ANPAnthropicWrapper      # Claude tool use
    from wrappers import ANPNegotiateTool         # LangChain tool
    from wrappers import anp_negotiate            # función Python directa (sin LLM)
    from wrappers import ANP_OPENAI_TOOL          # JSON de definición para OpenAI
    from wrappers import ANP_ANTHROPIC_TOOL       # JSON de definición para Anthropic
"""
from .base import ANPBaseWrapper, ANPResult, ANP_SYSTEM_PROMPT
from .openai_wrapper import ANPOpenAIWrapper, ANP_OPENAI_TOOL
from .anthropic_wrapper import ANPAnthropicWrapper, ANP_ANTHROPIC_TOOL
from .langchain_wrapper import ANPNegotiateTool

# Función directa sin LLM — para usar ANP puro desde cualquier script
_engine = ANPBaseWrapper()

def anp_negotiate(
    item: str,
    max_price: float,
    seller_start: float,
    seller_min: float,
    qty: int = 1,
    buyer_strategy: str = "linear",
    seller_strategy: str = "linear",
    validate_oracle: bool = False,
) -> ANPResult:
    """
    Ejecuta una negociación ANP directamente desde Python.
    Sin LLM. Sin API externa. Solo lógica binaria pura.

    Ejemplo:
        from wrappers import anp_negotiate
        result = anp_negotiate("api_access_basic", max_price=0.08, seller_start=0.09, seller_min=0.05)
        print(result.final_price)
    """
    return _engine.negotiate(
        item=item, max_price=max_price,
        seller_start=seller_start, seller_min=seller_min,
        qty=qty, buyer_strategy=buyer_strategy,
        seller_strategy=seller_strategy,
        validate_oracle=validate_oracle,
    )


__all__ = [
    "ANPBaseWrapper", "ANPResult", "ANP_SYSTEM_PROMPT",
    "ANPOpenAIWrapper", "ANP_OPENAI_TOOL",
    "ANPAnthropicWrapper", "ANP_ANTHROPIC_TOOL",
    "ANPNegotiateTool",
    "anp_negotiate",
]
