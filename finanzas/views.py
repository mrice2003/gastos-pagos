from datetime import date
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Count, Q, Sum
from django.db.models.functions import TruncMonth
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.views.decorators.http import require_POST

from . import services
from .forms import (AbonoForm, CuentaEditForm, CuentaForm, GastoForm, GenerarPagoForm,
                    MotivoForm, ProveedorForm)
from .models import CuentaBancaria, Gasto, MovimientoCuenta, Pago, Proveedor
from .services import ReglaNegocioError


def _paginar(request, qs, por_pagina=15):
    return Paginator(qs, por_pagina).get_page(request.GET.get("page"))


def parse_entero(valor):
    try:
        return int(valor)
    except (TypeError, ValueError):
        return None


def parse_fecha(valor):
    try:
        return parse_date(valor or "")
    except ValueError:
        return None


def _f(valor):
    return float(valor or 0)


def resumen_datos():
    """Agregados para el dashboard y para /api/resumen/."""
    hoy = timezone.localdate()
    inicio_mes = hoy.replace(day=1)
    gastos_vivos = Gasto.objects.exclude(estado=Gasto.Estado.CANCELADO)
    total_gastos = gastos_vivos.aggregate(t=Sum("monto"))["t"] or Decimal("0")
    pagado = Pago.objects.filter(estado=Pago.Estado.EFECTUADO).aggregate(t=Sum("monto"))["t"] or Decimal("0")
    pagado_mes = (Pago.objects.filter(estado=Pago.Estado.EFECTUADO, fecha_pago__date__gte=inicio_mes)
                  .aggregate(t=Sum("monto"))["t"] or Decimal("0"))
    saldo_cuentas = CuentaBancaria.objects.filter(activa=True).aggregate(t=Sum("saldo"))["t"] or Decimal("0")

    por_estado = {e.value: {"etiqueta": e.label, "cantidad": 0, "monto": 0.0} for e in Gasto.Estado}
    for r in Gasto.objects.values("estado").annotate(c=Count("id"), m=Sum("monto")):
        por_estado[r["estado"]].update(cantidad=r["c"], monto=_f(r["m"]))

    etiquetas_cat = dict(Gasto.Categoria.choices)
    por_categoria = [
        {"categoria": etiquetas_cat.get(r["categoria"], r["categoria"]), "monto": _f(r["m"])}
        for r in gastos_vivos.values("categoria").annotate(m=Sum("monto")).order_by("-m")
    ]

    # Últimos 6 meses: gastos registrados vs pagos efectuados
    meses = []
    y, m = hoy.year, hoy.month
    for _ in range(6):
        meses.append(date(y, m, 1))
        y, m = (y, m - 1) if m > 1 else (y - 1, 12)
    meses.reverse()
    g_mes = {r["mes"].strftime("%Y-%m"): _f(r["m"]) for r in
             gastos_vivos.filter(fecha__gte=meses[0]).annotate(mes=TruncMonth("fecha"))
             .values("mes").annotate(m=Sum("monto"))}
    p_mes = {r["mes"].strftime("%Y-%m"): _f(r["m"]) for r in
             Pago.objects.filter(estado=Pago.Estado.EFECTUADO, fecha_pago__date__gte=meses[0])
             .annotate(mes=TruncMonth("fecha_pago")).values("mes").annotate(m=Sum("monto"))}
    por_mes = [{"mes": d.strftime("%Y-%m"), "gastos": g_mes.get(d.strftime("%Y-%m"), 0.0),
                "pagos": p_mes.get(d.strftime("%Y-%m"), 0.0)} for d in meses]

    cuentas = [{"id": c.id, "cuenta": c.nombre, "banco": c.banco, "saldo": _f(c.saldo)}
               for c in CuentaBancaria.objects.filter(activa=True)]

    return {
        "total_gastos": _f(total_gastos),
        "total_pagado": _f(pagado),
        "por_pagar": _f(total_gastos - pagado),
        "pagado_mes": _f(pagado_mes),
        "saldo_cuentas": _f(saldo_cuentas),
        "gastos_pendientes_aprobacion": Gasto.objects.filter(estado=Gasto.Estado.PENDIENTE).count(),
        "pagos_por_aprobar": Pago.objects.filter(estado=Pago.Estado.PENDIENTE).count(),
        "pagos_por_efectuar": Pago.objects.filter(estado=Pago.Estado.APROBADO).count(),
        "gastos_por_estado": list(por_estado.values()),
        "gastos_por_categoria": por_categoria,
        "gastos_vs_pagos_por_mes": por_mes,
        "saldo_por_cuenta": cuentas,
    }


# ---------------------------------------------------------------- DASHBOARD

@login_required
def dashboard(request):
    return render(request, "finanzas/dashboard.html", {
        "resumen": resumen_datos(),
        "pendientes": Gasto.objects.filter(estado=Gasto.Estado.PENDIENTE).select_related("proveedor")[:5],
        "pagos_aprobados": Pago.objects.filter(estado=Pago.Estado.APROBADO)
                                       .select_related("gasto", "cuenta")[:5],
        "ultimos_movimientos": MovimientoCuenta.objects.select_related("cuenta")[:6],
    })


# ---------------------------------------------------------------- GASTOS

@login_required
def gasto_list(request):
    qs = Gasto.objects.select_related("proveedor")
    f = {k: request.GET.get(k, "") for k in ("estado", "categoria", "proveedor", "desde", "hasta", "q")}
    if f["estado"]:
        qs = qs.filter(estado=f["estado"])
    if f["categoria"]:
        qs = qs.filter(categoria=f["categoria"])
    proveedor, desde, hasta = parse_entero(f["proveedor"]), parse_fecha(f["desde"]), parse_fecha(f["hasta"])
    if proveedor is not None:
        qs = qs.filter(proveedor_id=proveedor)
    if desde:
        qs = qs.filter(fecha__gte=desde)
    if hasta:
        qs = qs.filter(fecha__lte=hasta)
    if f["q"]:
        qs = qs.filter(concepto__icontains=f["q"]) | qs.filter(folio__icontains=f["q"])
    total = qs.aggregate(t=Sum("monto"))["t"] or 0
    return render(request, "finanzas/gasto_list.html", {
        "page": _paginar(request, qs), "f": f, "total": total,
        "estados": Gasto.Estado.choices, "categorias": Gasto.Categoria.choices,
        "proveedores": Proveedor.objects.all(),
    })


@login_required
def gasto_create(request):
    form = GastoForm(request.POST or None, initial={"fecha": timezone.localdate()})
    if request.method == "POST" and form.is_valid():
        gasto = services.crear_gasto(request.user, **form.cleaned_data)
        messages.success(request, f"Gasto {gasto.folio} registrado. Queda pendiente de aprobación.")
        return redirect("gasto_detail", pk=gasto.pk)
    return render(request, "finanzas/form.html", {"form": form, "titulo": "Nuevo gasto",
                                                   "volver": "gasto_list"})


@login_required
def gasto_edit(request, pk):
    gasto = get_object_or_404(Gasto, pk=pk)
    if gasto.estado != Gasto.Estado.PENDIENTE:
        messages.error(request, "Sólo se pueden editar gastos pendientes.")
        return redirect("gasto_detail", pk=pk)
    form = GastoForm(request.POST or None, instance=gasto)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Gasto actualizado.")
        return redirect("gasto_detail", pk=pk)
    return render(request, "finanzas/form.html", {"form": form, "titulo": f"Editar {gasto.folio}",
                                                   "volver": "gasto_list"})


@login_required
def gasto_detail(request, pk):
    gasto = get_object_or_404(Gasto.objects.select_related("proveedor", "creado_por", "aprobado_por"), pk=pk)
    return render(request, "finanzas/gasto_detail.html", {
        "gasto": gasto,
        "pagos": gasto.pagos.select_related("cuenta"),
        "bitacora": gasto.bitacora.select_related("usuario"),
        "pago_form": GenerarPagoForm(gasto=gasto) if gasto.puede_generar_pago else None,
        "motivo_form": MotivoForm(),
    })


@login_required
@require_POST
def gasto_aprobar(request, pk):
    try:
        g = services.aprobar_gasto(pk, request.user)
        messages.success(request, f"Gasto {g.folio} aprobado. Ya puedes generar el pago.")
    except ReglaNegocioError as e:
        messages.error(request, str(e))
    return redirect("gasto_detail", pk=pk)


@login_required
@require_POST
def gasto_cancelar(request, pk):
    form = MotivoForm(request.POST)
    motivo = form.cleaned_data["motivo"] if form.is_valid() else ""
    try:
        g = services.cancelar_gasto(pk, request.user, motivo)
        messages.warning(request, f"Gasto {g.folio} cancelado. Esta acción no se puede revertir.")
    except ReglaNegocioError as e:
        messages.error(request, str(e))
    return redirect("gasto_detail", pk=pk)


@login_required
@require_POST
def gasto_generar_pago(request, pk):
    gasto = get_object_or_404(Gasto, pk=pk)
    form = GenerarPagoForm(request.POST, gasto=gasto)
    if not form.is_valid():
        for errs in form.errors.values():
            for e in errs:
                messages.error(request, e)
        return redirect("gasto_detail", pk=pk)
    d = form.cleaned_data
    try:
        pago, creado = services.generar_pago(
            pk, request.user, cuenta=d["cuenta"], monto=d["monto"], metodo=d["metodo"],
            referencia=d["referencia"], idempotency_key=d["idempotency_key"])
    except ReglaNegocioError as e:
        messages.error(request, str(e))
        return redirect("gasto_detail", pk=pk)
    if creado:
        messages.success(request, f"Pago {pago.folio} generado por ${pago.monto:,.2f}. Pendiente de aprobación.")
    else:
        messages.info(request, f"El pago {pago.folio} ya se había generado (envío duplicado ignorado).")
    return redirect("pago_detail", pk=pago.pk)


# ---------------------------------------------------------------- PAGOS

@login_required
def pago_list(request):
    qs = Pago.objects.select_related("gasto", "gasto__proveedor", "cuenta")
    f = {k: request.GET.get(k, "") for k in ("estado", "cuenta")}
    if f["estado"]:
        qs = qs.filter(estado=f["estado"])
    cuenta = parse_entero(f["cuenta"])
    if cuenta is not None:
        qs = qs.filter(cuenta_id=cuenta)
    total = qs.aggregate(t=Sum("monto"))["t"] or 0
    return render(request, "finanzas/pago_list.html", {
        "page": _paginar(request, qs), "f": f, "total": total,
        "estados": Pago.Estado.choices, "cuentas": CuentaBancaria.objects.all(),
    })


@login_required
def pago_detail(request, pk):
    pago = get_object_or_404(Pago.objects.select_related("gasto", "gasto__proveedor", "cuenta"), pk=pk)
    return render(request, "finanzas/pago_detail.html", {
        "pago": pago, "bitacora": pago.bitacora.select_related("usuario"), "motivo_form": MotivoForm(),
        "saldo_suficiente": pago.cuenta.saldo >= pago.monto,
    })


def _accion_pago(request, pk, fn, ok_msg, nivel=messages.SUCCESS, **kwargs):
    try:
        p = fn(pk, request.user, **kwargs)
        messages.add_message(request, nivel, ok_msg.format(folio=p.folio))
    except ReglaNegocioError as e:
        messages.error(request, str(e))
    return redirect("pago_detail", pk=pk)


@login_required
@require_POST
def pago_aprobar(request, pk):
    return _accion_pago(request, pk, services.aprobar_pago, "Pago {folio} aprobado.")


@login_required
@require_POST
def pago_cancelar(request, pk):
    form = MotivoForm(request.POST)
    motivo = form.cleaned_data["motivo"] if form.is_valid() else ""
    return _accion_pago(request, pk, services.cancelar_pago, "Pago {folio} cancelado.",
                        nivel=messages.WARNING, motivo=motivo)


@login_required
@require_POST
def pago_efectuar(request, pk):
    return _accion_pago(request, pk, services.efectuar_pago,
                        "Pago {folio} efectuado. Se descontó el saldo de la cuenta.")


# ---------------------------------------------------------------- CUENTAS

@login_required
def cuenta_list(request):
    cuentas = CuentaBancaria.objects.all()
    return render(request, "finanzas/cuenta_list.html", {
        "cuentas": cuentas,
        "total": cuentas.filter(activa=True).aggregate(t=Sum("saldo"))["t"] or 0,
    })


@login_required
def cuenta_create(request):
    form = CuentaForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        c = services.crear_cuenta(request.user, **form.cleaned_data)
        messages.success(request, f"Cuenta {c.nombre} creada.")
        return redirect("cuenta_detail", pk=c.pk)
    return render(request, "finanzas/form.html", {"form": form, "titulo": "Nueva cuenta bancaria",
                                                   "volver": "cuenta_list"})


@login_required
def cuenta_edit(request, pk):
    cuenta = get_object_or_404(CuentaBancaria, pk=pk)
    form = CuentaEditForm(request.POST or None, instance=cuenta)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Cuenta actualizada.")
        return redirect("cuenta_detail", pk=pk)
    return render(request, "finanzas/form.html", {"form": form, "titulo": f"Editar {cuenta.nombre}",
                                                   "volver": "cuenta_list"})


@login_required
def cuenta_detail(request, pk):
    cuenta = get_object_or_404(CuentaBancaria, pk=pk)
    movs = cuenta.movimientos.select_related("pago", "usuario")
    historial = [{"fecha": timezone.localtime(m.fecha).strftime("%Y-%m-%d %H:%M"),
                  "saldo": _f(m.saldo_resultante)} for m in reversed(list(movs[:60]))]
    stats = movs.values("tipo").annotate(t=Sum("monto"))
    return render(request, "finanzas/cuenta_detail.html", {
        "cuenta": cuenta, "page": _paginar(request, movs, 20), "historial": historial,
        "abono_form": AbonoForm(), "stats": {s["tipo"]: s["t"] for s in stats},
    })


@login_required
@require_POST
def cuenta_abonar(request, pk):
    form = AbonoForm(request.POST)
    if form.is_valid():
        try:
            services.abonar_cuenta(pk, request.user, form.cleaned_data["monto"], form.cleaned_data["descripcion"])
            messages.success(request, "Abono registrado.")
        except ReglaNegocioError as e:
            messages.error(request, str(e))
    else:
        messages.error(request, "Monto inválido.")
    return redirect("cuenta_detail", pk=pk)


# ---------------------------------------------------------------- PROVEEDORES

@login_required
def proveedor_list(request):
    qs = Proveedor.objects.annotate(
        n=Count("gastos", filter=~Q(gastos__estado=Gasto.Estado.CANCELADO)),
        total=Sum("gastos__monto", filter=~Q(gastos__estado=Gasto.Estado.CANCELADO)))
    return render(request, "finanzas/proveedor_list.html", {"proveedores": qs})


@login_required
def proveedor_form(request, pk=None):
    obj = get_object_or_404(Proveedor, pk=pk) if pk else None
    form = ProveedorForm(request.POST or None, instance=obj)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Proveedor guardado.")
        return redirect("proveedor_list")
    return render(request, "finanzas/form.html", {
        "form": form, "titulo": "Editar proveedor" if obj else "Nuevo proveedor", "volver": "proveedor_list"})
