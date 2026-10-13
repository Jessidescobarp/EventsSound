/**
 * Every user-facing string of the site lives in this module (Spanish only, no i18n
 * library). Page content is synthetic placeholder text until the owner supplies the
 * real copy. Components must not contain Spanish literals.
 */
export const es = {
  brand: {
    name: "EventSoundDR",
    tagline: "Sonido, luces y DJ para eventos",
    logoLabel: "EventSoundDR, ir al inicio",
  },

  a11y: {
    skipLink: "Saltar al contenido",
    mainNav: "Navegación principal",
    footerNav: "Enlaces del pie de página",
  },

  nav: {
    home: "Inicio",
    about: "Quiénes somos",
    portfolio: "Portafolio",
    services: "Servicios",
    chat: "Cotizar",
  },

  titles: {
    home: "Inicio",
    about: "Quiénes somos",
    portfolio: "Portafolio",
    services: "Servicios y catálogo",
    chat: "Asistente de cotización",
    notFound: "Página no encontrada",
  },

  common: {
    retry: "Reintentar",
    loading: "Cargando...",
    comingSoon: "Próximamente",
  },

  banners: {
    demoTitle: "Datos de demostración",
    demoBody:
      "Estás viendo información de ejemplo: los equipos, paquetes y precios no son reales.",
    wakingTitle: "Despertando el servidor",
    wakingBody:
      "La primera visita puede tardar hasta un minuto. Mientras tanto puedes explorar el sitio.",
    unavailableTitle: "No pudimos conectar con el servidor",
    unavailableBody: "Revisa tu conexión e inténtalo de nuevo.",
  },

  footer: {
    note: "Contenido de ejemplo para la demostración del proyecto.",
    rights: (year: number) => `© ${year} EventSoundDR. Proyecto académico con datos sintéticos.`,
  },

  home: {
    heroTitle: "Sonido, luces y DJ para eventos inolvidables",
    heroLead:
      "Alquilamos equipos y armamos paquetes completos para bodas, fiestas, eventos corporativos y conciertos.",
    ctaServices: "Ver servicios",
    ctaChat: "Cotizar con el asistente",
    offerTitle: "Lo que hacemos",
    offer: [
      {
        title: "Sonido profesional",
        body: "Parlantes, subwoofers, consolas y micrófonos para que todos escuchen con claridad.",
      },
      {
        title: "Iluminación y efectos",
        body: "Luces LED, cabezas móviles, láser y humo para crear la atmósfera de tu evento.",
      },
      {
        title: "DJ y escenarios",
        body: "Equipos de DJ, tarimas y pantallas para que la pista y el escenario estén listos.",
      },
    ],
    stepsTitle: "Cómo trabajamos",
    steps: [
      { title: "Cuéntanos tu evento", body: "Fecha, lugar, tipo de evento y cantidad de invitados." },
      { title: "Recibe una propuesta", body: "Armamos un paquete a la medida con precio claro y desglosado." },
      { title: "Nosotros montamos", body: "Llevamos, instalamos y operamos el equipo para que solo disfrutes." },
    ],
    closingTitle: "¿Listo para tu próximo evento?",
    closingBody: "Explora el catálogo o pide una cotización en minutos.",
  },

  about: {
    title: "Quiénes somos",
    lead: "Somos un equipo de técnicos, DJs y diseñadores de luces apasionados por la música en vivo.",
    storyTitle: "Nuestra historia",
    story: [
      "Empezamos alquilando un par de parlantes para fiestas de amigos. Hoy acompañamos bodas, eventos corporativos y conciertos con equipos de calidad profesional.",
      "Creemos que un buen evento se nota en los detalles: un sonido limpio, una luz bien pensada y un equipo que llega a tiempo.",
    ],
    valuesTitle: "Nuestros valores",
    values: [
      { title: "Puntualidad", body: "Llegamos con tiempo para montar y probar antes de que lleguen los invitados." },
      { title: "Transparencia", body: "Precios claros y desglosados, sin cargos sorpresa." },
      { title: "Cuidado del detalle", body: "Revisamos cada equipo antes de salir y tenemos respaldo para cada evento." },
    ],
  },

  portfolio: {
    title: "Portafolio de eventos",
    lead: "Algunos de los eventos que hemos acompañado (ejemplos ilustrativos).",
    equipmentLabel: "Equipo utilizado",
    imageLabel: (title: string) => `Imagen ilustrativa del evento: ${title}`,
    events: [
      {
        id: "boda-jardin",
        title: "Boda en jardín",
        kind: "Boda",
        description: "Ceremonia y recepción para 180 invitados con sonido ambiental y pista de baile iluminada.",
        equipment: ["Sonido", "Micrófonos inalámbricos", "Luces LED"],
      },
      {
        id: "lanzamiento-corporativo",
        title: "Lanzamiento corporativo",
        kind: "Corporativo",
        description: "Presentación de producto con pantalla LED, micrófonos de solapa y escenario modular.",
        equipment: ["Pantalla LED", "Consola de mezcla", "Tarima"],
      },
      {
        id: "festival-universitario",
        title: "Festival universitario",
        kind: "Festival",
        description: "Dos escenarios con bandas en vivo y DJs durante un día completo.",
        equipment: ["Sistema de sonido", "Cabezas móviles", "Efectos"],
      },
      {
        id: "noche-dj-terraza",
        title: "Noche de DJ en terraza",
        kind: "DJ",
        description: "Sesión nocturna al aire libre con cabina de DJ, láser y máquina de humo.",
        equipment: ["Equipo de DJ", "Láser", "Humo"],
      },
      {
        id: "quince-anos",
        title: "Fiesta de quince años",
        kind: "Fiesta",
        description: "Vals, baile sorpresa y pista con efectos de chispas frías.",
        equipment: ["Sonido", "Chispas frías", "Luces LED"],
      },
      {
        id: "concierto-teatro",
        title: "Concierto en teatro",
        kind: "Concierto",
        description: "Montaje de sonido e iluminación para un concierto acústico con aforo de 400 personas.",
        equipment: ["Line array", "Monitores", "Iluminación escénica"],
      },
    ],
  },

  services: {
    title: "Servicios y catálogo",
    lead: "Alquilamos equipos sueltos y paquetes completos. Los precios son por día de alquiler.",
    packagesTitle: "Paquetes",
    packagesLead: "Combinaciones pensadas para cada tipo de evento, con descuento sobre el precio de los equipos.",
    itemsTitle: "Equipos",
    categoryFilterLabel: "Categoría",
    categoryAll: "Todas las categorías",
    perDay: "por día",
    fromLabel: "Precio base",
    stockLabel: (n: number) => (n === 1 ? "1 unidad disponible" : `${n} unidades disponibles`),
    discountBadge: (percent: string) => `${percent} de descuento`,
    includesLabel: "Incluye",
    memberLine: (quantity: number, name: string) => `${quantity} × ${name}`,
    loading: "Cargando el catálogo...",
    waiting: "Esperando al servidor, esto puede tardar hasta un minuto...",
    unavailableTitle: "El catálogo estará disponible pronto",
    unavailableBody: "Todavía no podemos mostrar los equipos y paquetes. Vuelve a intentarlo en unos minutos.",
    emptyItems: "Aún no hay equipos publicados.",
    emptyPackages: "Aún no hay paquetes publicados.",
    chatCta: "¿No sabes qué elegir? Pide una cotización al asistente.",
    chatCtaButton: "Cotizar con el asistente",
    categories: {
      sound: "Sonido",
      lighting: "Iluminación",
      dj: "DJ",
      stage: "Escenarios",
      effects: "Efectos",
      video: "Video",
    } as Record<string, string>,
    categoryFallback: "Otros",
  },

  chat: {
    title: "Asistente de cotización",
    lead: "Cuéntanos sobre tu evento (fecha, horario, invitados, lugar y equipos) y el asistente te entregará una cotización detallada.",
    conversationTitle: "Conversación",
    empty: "Aún no hay mensajes. Describe tu evento para empezar.",
    logLabel: "Mensajes de la conversación",
    authorUser: "Tú",
    authorAssistant: "Asistente",
    inputLabel: "Tu mensaje",
    inputHelp: "Enter envía el mensaje; Mayús + Enter agrega una línea.",
    counter: (used: number, max: number) => `${used} de ${max} caracteres`,
    send: "Enviar",
    typing: "El asistente está escribiendo...",
    newConversation: "Nueva conversación",
    demoHint:
      "Escenarios de la demostración: escribe «pregunta», «faltante», «limite» o «apagado»; cualquier otro texto devuelve una cotización completa.",
    source: {
      llm: "Redactado por IA",
      template: "Respuesta automática",
      static: "Respuesta automática",
    } as Record<string, string>,
    errors: {
      empty: { title: "Escribe un mensaje antes de enviar.", body: "" },
      too_long: { title: "El mensaje es demasiado largo.", body: "Acórtalo e inténtalo de nuevo." },
      disabled: {
        title: "El asistente no está disponible por ahora",
        body: "Estamos terminando de prepararlo. Mientras tanto, explora el catálogo o vuelve más tarde.",
      },
      rate_limited: {
        title: "Has enviado demasiadas solicitudes",
        body: "Espera un momento antes de enviar otro mensaje.",
      },
      budget: {
        title: "El asistente alcanzó su límite diario",
        body: "Vuelve a intentarlo mañana.",
      },
      invalid: {
        title: "No pudimos procesar tu mensaje",
        body: "Revisa que no sea demasiado largo e inténtalo de nuevo.",
      },
      transient: {
        title: "No pudimos contactar al asistente",
        body: "Revisa tu conexión e inténtalo de nuevo.",
      },
      unexpected: {
        title: "Recibimos una respuesta que no pudimos interpretar",
        body: "Inténtalo de nuevo en unos instantes.",
      },
    },
    waking: "El servidor está despertando, esto puede tardar hasta un minuto.",
    cooldown: (seconds: number) => `Podrás enviar de nuevo en ${seconds} s.`,
    catalogLink: "Ver el catálogo",
  },

  quote: {
    title: "Detalle de la cotización",
    caption: "Conceptos de la cotización en pesos colombianos",
    colConcept: "Concepto",
    colQuantity: "Cantidad",
    colAmount: "Valor",
    rentalDays: (days: number) => (days === 1 ? "Alquiler por 1 día" : `Alquiler por ${days} días`),
    subtotal: "Subtotal",
    total: "Total",
    unitDetail: (quantity: number, periods: number, unit: string) =>
      `${quantity} × ${periods} ${periods === 1 ? "día" : "días"} × ${unit}`,
    surchargeDetail: (rate: string, basis: string) => `${rate} sobre ${basis}`,
    kinds: {
      item: "Equipo",
      package: "Paquete",
      package_discount: "Descuento del paquete",
      guest_size: "Recargo por número de invitados",
      weekend_holiday: "Recargo por fin de semana o festivo",
      night: "Recargo nocturno",
      distance: "Recargo por distancia",
      rounding: "Ajuste de redondeo",
    } as Record<string, string>,
    kindFallback: "Otro concepto",
    equipmentFallback: "Equipo",
    availabilityTitle: "Disponibilidad",
    allAvailable: "Todos los equipos están disponibles para la fecha.",
    available: "Disponible",
    shortage: (requested: number, available: number) =>
      `No alcanza: pediste ${requested} y hay ${available}`,
    missingTitle: "Para continuar necesito:",
    missing: {
      event_date: "La fecha del evento",
      start_time: "La hora de inicio",
      end_time_or_duration: "La hora de fin o la duración",
      guest_count: "El número de invitados",
      distance_or_locality: "La ciudad o la distancia desde Bogotá",
      equipment: "Los equipos que necesitas",
    } as Record<string, string>,
  },

  notFound: {
    title: "Página no encontrada",
    body: "La dirección que buscas no existe o fue movida.",
    cta: "Volver al inicio",
  },
} as const;

export type Copy = typeof es;
