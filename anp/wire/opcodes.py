"""
ANP-Wire Opcode Table
Cada opcode es 1 byte. Máximo 255 opcodes posibles en el protocolo.
"""
from enum import IntEnum


class Op(IntEnum):
    BID     = 0x01  # Comprador lanza petición
    OFFER   = 0x02  # Vendedor responde con precio
    COUNTER = 0x03  # Contraoferta
    ACCEPT  = 0x04  # Acuerdo cerrado
    REJECT  = 0x05  # Rechazo sin contraoferta
    CANCEL  = 0x06  # Cancelación unilateral
    AUTH    = 0x07  # Presentación de token ANP-Pass
    ACK     = 0x08  # Confirmación de recepción
    ERR     = 0x09  # Error con código
    QUERY   = 0x0A  # Consulta al oráculo de precios
    PRICE   = 0x0B  # Respuesta del oráculo

    # Debug flag: si el frame empieza con 0xFF, activar modo verbose
    DEBUG   = 0xFF


# Códigos de error para payload de ERR
class ErrCode(IntEnum):
    AUTH_FAILED     = 0x01  # Token inválido o expirado
    PRICE_REJECTED  = 0x02  # Oráculo bloqueó la oferta
    BUDGET_EXCEEDED = 0x03  # Oferta supera presupuesto del token
    SCOPE_DENIED    = 0x04  # Item no está en scope del token
    SESSION_EXPIRED = 0x05  # TTL de sesión agotado
    MAX_ROUNDS      = 0x06  # Límite de rondas alcanzado
    MALFORMED_FRAME = 0x07  # Frame corrupto o inválido


# Qué opcodes puede enviar cada rol
BUYER_OPS  = {Op.BID, Op.COUNTER, Op.ACCEPT, Op.REJECT, Op.CANCEL, Op.AUTH, Op.ACK, Op.QUERY}
SELLER_OPS = {Op.OFFER, Op.COUNTER, Op.REJECT, Op.CANCEL, Op.AUTH, Op.ACK, Op.ERR, Op.PRICE}

# Opcodes que cierran la sesión (no se pueden enviar más mensajes después)
TERMINAL_OPS = {Op.ACCEPT, Op.REJECT, Op.CANCEL}

# Nombres legibles para logs
OP_NAME = {op: op.name for op in Op}
