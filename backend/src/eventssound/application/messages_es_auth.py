"""Public error messages of the auth endpoints, keyed by the machine code in `detail`.

Spanish, no accents (same as `messages_es_chat`). A code and a sentence, never the cause.
"""

AUTH_ERRORS = {
    "invalid_credentials": "El correo o la contrasena no son correctos.",
    "rate_limited": "Demasiados intentos. Intenta de nuevo en unos minutos.",
    "not_authenticated": "Debes iniciar sesion para continuar.",
    "forbidden": "No tienes permiso para ver esto.",
    "invalid_portfolio_event": "Los datos del evento no son validos.",
    "auth_not_configured": "El inicio de sesion no esta disponible por ahora.",
    "auth_unavailable": "No pudimos validar tus datos. Intenta mas tarde.",
    "storage_unavailable": "No pudimos consultar los datos. Intenta mas tarde.",
    "code_taken": "Ya existe un registro con ese codigo.",
    "not_found": "No encontramos ese registro.",
    "unknown_item": "Alguno de los equipos del paquete no existe.",
    "invalid_catalog_entry": "Los datos del registro no son validos.",
}
