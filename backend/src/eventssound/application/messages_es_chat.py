"""Public error messages of the chat endpoint, keyed by the machine code in `detail`.

Spanish, written without accents like the rest of `messages_es`. They never carry detail
about the cause: a code and a sentence for the customer.
"""

CHAT_ERRORS = {
    "chat_disabled": "El asistente de cotizaciones no esta disponible por ahora.",
    "payload_too_large": "El mensaje es demasiado grande.",
    "invalid_request": "La solicitud no es valida. Revisa el numero y el largo de los mensajes.",
    "rate_limited": "Has enviado demasiadas solicitudes. Intenta de nuevo en unos minutos.",
    "daily_budget_exhausted": "El asistente alcanzo su limite diario. Intenta de nuevo manana.",
    "llm_unavailable": "El asistente no esta disponible en este momento. Intenta mas tarde.",
    "catalog_unavailable": "No pudimos consultar el catalogo. Intenta mas tarde.",
    "internal_error": "Ocurrio un error inesperado. Intenta de nuevo mas tarde.",
}
