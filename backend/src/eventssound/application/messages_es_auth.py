"""Public error messages of the auth endpoints, keyed by the machine code in `detail`.

Spanish, no accents (same as `messages_es_chat`). A code and a sentence, never the cause.
"""

AUTH_ERRORS = {
    "invalid_credentials": "El correo o la contrasena no son correctos.",
    "rate_limited": "Demasiados intentos. Intenta de nuevo en unos minutos.",
    "not_authenticated": "Debes iniciar sesion para continuar.",
    "forbidden": "No tienes permiso para ver esto.",
    "auth_not_configured": "El inicio de sesion no esta disponible por ahora.",
    "auth_unavailable": "No pudimos validar tus datos. Intenta mas tarde.",
}
