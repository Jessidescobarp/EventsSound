"""Public messages of the agent configuration endpoints, keyed by machine code.

Spanish, no accents (same as `messages_es_auth`). A code and a sentence, never the cause.
"""

CONFIG_ERRORS = {
    "invalid_config": "La configuracion no es valida. Revisa los campos indicados.",
    "no_changes": "No hay cambios para aplicar.",
    "version_conflict": "La configuracion cambio mientras la editabas. Recarga e intenta de nuevo.",
    "unknown_version": "No encontramos esa version.",
    "confirmation_unavailable": "La confirmacion de cambios no esta disponible por ahora.",
    "token_invalid": "La confirmacion no es valida. Revisa los cambios de nuevo.",
    "token_expired": "La confirmacion vencio. Revisa los cambios de nuevo.",
    "token_used": "La confirmacion ya se uso. Revisa los cambios de nuevo.",
    "token_mismatch": "La confirmacion no corresponde a estos cambios. Revisalos de nuevo.",
    "typed_confirmation_invalid": "Escribe APLICAR para confirmar.",
    "reauth_failed": "No pudimos confirmar tu identidad.",
    "password_required": "Estos cambios requieren tu contrasena.",
}

WARNINGS = {
    "cap_raised": "Subiste un tope diario: el agente podra gastar mas.",
    "cap_raised_2x": "Un tope diario sube a mas del doble del actual.",
    "model_changed": "Cambia el modelo del agente: la calidad y el costo pueden variar.",
    "rate_limit_raised": "Subiste el limite por minuto del chat.",
    "texts_changed": "Cambian los textos que ven los clientes.",
    "behavior_changed": "Cambia el tono o la politica de temas fuera de alcance.",
    "cost_cap_not_binding": (
        "El tope de costo no aplica con los precios actuales (0): solo limita el tope de tokens."
    ),
    "free_model_limits": (
        "Los modelos gratuitos pueden tener límites de uso del proveedor, menor disponibilidad "
        "y calidad distinta; el tope de costo no aplica, el tope de tokens sí."
    ),
    "paid_model_cost": (
        "El modelo seleccionado es de pago: su gasto cuenta contra el tope diario de costo."
    ),
    "cost_unknown": "No se puede estimar el costo del modelo seleccionado.",
    "immediate_effect": (
        "Este cambio afecta cada conversacion nueva de inmediato y puede aumentar el costo."
    ),
}
