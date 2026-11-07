from decimal import Decimal, InvalidOperation

from django import template
from django.utils.html import format_html
from django.utils.safestring import mark_safe

register = template.Library()

COLORES = {
    "PENDIENTE": "warning", "APROBADO": "primary", "PAGADO_PARCIAL": "info",
    "PAGADO": "success", "EFECTUADO": "success", "CANCELADO": "secondary",
    "CARGO": "danger", "ABONO": "success",
}


@register.filter
def dinero(valor):
    try:
        return f"${Decimal(valor or 0):,.2f}"
    except (InvalidOperation, TypeError, ValueError):
        return valor


@register.simple_tag
def badge(estado, etiqueta=None):
    color = COLORES.get(estado, "secondary")
    return format_html('<span class="status status-{}">{}</span>',
                       color, etiqueta or estado.replace("_", " ").title())


PASOS = {
    "gasto": [("PENDIENTE", "Registrado", "pencil"), ("APROBADO", "Aprobado", "check2"),
              ("PAGADO_PARCIAL", "Pago parcial", "pie-chart"), ("PAGADO", "Pagado", "cash-coin")],
    "pago": [("PENDIENTE", "Generado", "pencil"), ("APROBADO", "Aprobado", "check2"),
             ("EFECTUADO", "Efectuado", "send-check")],
}


@register.simple_tag
def stepper(tipo, estado):
    """Línea de progreso del estado de un gasto o pago (UX-08)."""
    pasos = PASOS[tipo]
    claves = [p[0] for p in pasos]
    cancelado = estado == "CANCELADO"
    actual = claves.index(estado) if estado in claves else -1
    html = []
    for i, (clave, etiqueta, icono) in enumerate(pasos):
        if cancelado:
            cls = "done" if i == 0 else "skipped"
        elif i < actual:
            cls = "done"
        elif i == actual:
            cls = "done" if i == len(pasos) - 1 else "current"
        else:
            cls = ""
        contenido = format_html('<i class="bi bi-{}"></i>', "check-lg" if "done" in cls else icono)
        html.append(format_html('<div class="step {}"><span class="dot">{}</span><span class="lbl">{}</span></div>',
                                cls, contenido, etiqueta))
    if cancelado:
        html.append(format_html('<div class="step cancelled"><span class="dot"><i class="bi bi-x-lg"></i></span>'
                                '<span class="lbl">Cancelado</span></div>'))
    return format_html('<div class="card stepper mb-3" aria-label="Progreso del estado">{}</div>',
                       mark_safe("".join(html)))


@register.simple_tag(takes_context=True)
def qs_page(context, page):
    """Conserva los filtros de la URL al paginar."""
    q = context["request"].GET.copy()
    q["page"] = page
    return q.urlencode()
