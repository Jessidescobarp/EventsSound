# EventSoundDR: documento de entrega

Proyecto final del Máster en Desarrollo con IA. Plantilla de la entrega: los enlaces ya están completos; completá lo marcado con `<...>` antes de entregarla. Las contraseñas **no** se escriben en este archivo ni en el repositorio: se envían a los evaluadores por separado.

## Enlaces

| Entregable | Enlace |
| --- | --- |
| Aplicación (frontend) | https://eventsounddr-web.onrender.com |
| API (backend) | https://eventsounddr-api.onrender.com/docs |
| Repositorio público | https://github.com/Jessidescobarp/EventsSound |
| Diapositivas | https://github.com/Jessidescobarp/EventsSound/blob/main/documentacion/EventSoundDR-presentacion.pptx |
| Video del producto funcionando | `<URL del video>` |

## Qué es

Aplicación web con un agente de IA que arma cotizaciones para una empresa de sonido, luces y DJ para eventos. El agente conversa en español, extrae los datos del evento y propone un paquete. **La IA nunca calcula el precio**: lo calcula una función determinista (`calculate_price`) y el borrador del agente se verifica contra ese cálculo. Todos los datos son sintéticos.

## Cuentas de demostración

| Rol | Correo | Contraseña |
| --- | --- | --- |
| Administrador | `admin@eventsounddr.example` | enviada por separado |
| Cliente | `cliente@eventsounddr.example` | enviada por separado |

Solo protegen cuentas sintéticas.

## Guía rápida de prueba

1. Las instancias gratuitas se duermen tras 15 minutos sin uso: abrí primero la API (enlace de arriba) y esperá cerca de un minuto.
2. Entrá a `/cotizar` y escribí, por ejemplo: "Quiero cotizar un cumpleaños". El agente pregunta de a un dato por vez; respondé con mensajes cortos (fecha, horario, invitados, distancia).
3. Con la cuenta de cliente, "Mis cotizaciones" lista las cotizaciones hechas con sesión iniciada.
4. Con la cuenta de administrador, el panel permite editar el catálogo, los paquetes, el portafolio y la configuración del agente (con doble confirmación).
5. Probá un mensaje fuera de tema o un intento de inyección ("ignorá tus instrucciones…"): el agente lo rechaza.

La guía completa, la arquitectura y las decisiones están en el [README](../README.es.md) y en esta carpeta.

## Requisitos del TFM y dónde verlos

| Requisito | Dónde |
| --- | --- |
| README con stack, pasos y credenciales de prueba | [README.es.md](../README.es.md) |
| Repositorio público | enlace de arriba |
| URL en vivo | enlace de arriba |
| IA como núcleo del producto | agente de cotización (LangGraph + OpenRouter), [architecture.md](architecture.md) |
| Diapositivas y video | enlaces de arriba |
