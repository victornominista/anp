"""
ANP · Wrappers · LangChain
==========================
Integra ANP como un Tool de LangChain.
Compatible con cualquier agente LangChain: ReAct, OpenAI Functions, etc.

Uso:
    from langchain_openai import ChatOpenAI
    from langchain.agents import create_tool_calling_agent, AgentExecutor

    llm = ChatOpenAI(model="gpt-4o-mini")
    tools = [ANPNegotiateTool()]
    agent = create_tool_calling_agent(llm, tools, prompt)
    executor = AgentExecutor(agent=agent, tools=tools)
    result = executor.invoke({"input": "Compra hosting por menos de $10"})
"""
import json
from typing import Optional, Type

from .base import ANPBaseWrapper, ANPResult, ANP_SYSTEM_PROMPT

# LangChain es opcional — solo importamos si está instalado
try:
    from langchain.tools import BaseTool
    from pydantic import BaseModel, Field as PydanticField
    LANGCHAIN_AVAILABLE = True
except ImportError:
    LANGCHAIN_AVAILABLE = False
    BaseTool = object


# ── Schema de entrada para LangChain ─────────────────────────────────────────

if LANGCHAIN_AVAILABLE:
    from pydantic import BaseModel, Field as PydanticField

    class ANPNegotiateInput(BaseModel):
        item:            str   = PydanticField(description="Identificador del item a negociar")
        max_price:       float = PydanticField(description="Precio máximo en USD")
        seller_start:    float = PydanticField(description="Precio inicial del vendedor")
        seller_min:      float = PydanticField(description="Precio mínimo del vendedor")
        qty:             int   = PydanticField(default=1, description="Cantidad")
        buyer_strategy:  str   = PydanticField(default="linear", description="linear|patient|aggressive")
        validate_oracle: bool  = PydanticField(default=True, description="Validar con oráculo")

    class ANPNegotiateTool(BaseTool, ANPBaseWrapper):
        """
        LangChain Tool que ejecuta negociaciones ANP.
        Se puede agregar al toolkit de cualquier agente LangChain.
        """
        name: str = "anp_negotiate"
        description: str = (
            "Negocia el precio de un servicio usando el protocolo ANP. "
            "Input: item, max_price, seller_start, seller_min. "
            "Output: resultado JSON con precio final, rondas y bytes wire. "
            "Úsalo para comprar servicios a precio optimizado sin consumir tokens extra."
        )
        args_schema: Type[ANPNegotiateInput] = ANPNegotiateInput

        # Campos de ANPBaseWrapper
        oracle:             Optional[object] = None
        passport_token:     Optional[str]    = None
        passport_validator: Optional[object] = None

        class Config:
            arbitrary_types_allowed = True

        def _run(
            self,
            item: str,
            max_price: float,
            seller_start: float,
            seller_min: float,
            qty: int = 1,
            buyer_strategy: str = "linear",
            validate_oracle: bool = True,
        ) -> str:
            result = self.negotiate(
                item=item, max_price=max_price,
                seller_start=seller_start, seller_min=seller_min,
                qty=qty, buyer_strategy=buyer_strategy,
                validate_oracle=validate_oracle,
            )
            return json.dumps(result.to_dict())

        async def _arun(self, *args, **kwargs) -> str:
            return self._run(*args, **kwargs)

else:
    class ANPNegotiateTool:
        """Placeholder cuando LangChain no está instalado."""
        def __init__(self, *args, **kwargs):
            raise ImportError(
                "LangChain no está instalado. "
                "Instala con: pip install langchain langchain-openai"
            )
