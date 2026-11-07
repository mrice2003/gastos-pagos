"""Reglas de negocio de gastos y pagos.

Todas las operaciones corren dentro de una transacción y bloquean las filas
involucradas (select_for_update) para que dos usuarios no puedan, por ejemplo,
efectuar el mismo pago dos veces o sobregirar una cuenta al mismo tiempo.
"""
import uuid
from decimal import Decimal

from django.db import IntegrityError, transaction
from django.utils import timezone

from .models import BitacoraEstado, CuentaBancaria, Gasto, MovimientoCuenta, Pago

GE = Gasto.Estado
PE = Pago.Estado


class ReglaNegocioError(Exception):
    """Se lanza cuando una operación viola una regla de negocio."""


def _bitacora(usuario, estado_anterior, estado_nuevo, comentario="", gasto=None, pago=None):
    BitacoraEstado.objects.create(
        gasto=gasto, pago=pago, usuario=usuario, comentario=comentario,
        estado_anterior=estado_anterior, estado_nuevo=estado_nuevo,
    )


def _lock_gasto(gasto_id):
    return Gasto.objects.select_for_update().get(pk=gasto_id)


def _lock_pago(pago_id):
    return Pago.objects.select_for_update().get(pk=pago_id)


# ---------------------------------------------------------------- GASTOS

def crear_gasto(usuario, **datos):
    with transaction.atomic():
        gasto = Gasto.objects.create(creado_por=usuario, **datos)
        _bitacora(usuario, "", GE.PENDIENTE, "Gasto registrado", gasto=gasto)
        return gasto


def aprobar_gasto(gasto_id, usuario):
    with transaction.atomic():
        gasto = _lock_gasto(gasto_id)
        if gasto.estado == GE.CANCELADO:
            raise ReglaNegocioError("Un gasto cancelado no se puede reactivar ni aprobar.")
        if gasto.estado != GE.PENDIENTE:
            raise ReglaNegocioError(f"Sólo se aprueban gastos pendientes (estado actual: {gasto.get_estado_display()}).")
        gasto.estado = GE.APROBADO
        gasto.aprobado_por = usuario
        gasto.save(update_fields=["estado", "aprobado_por", "actualizado"])
        _bitacora(usuario, GE.PENDIENTE, GE.APROBADO, "Gasto aprobado", gasto=gasto)
        return gasto


def cancelar_gasto(gasto_id, usuario, motivo=""):
    with transaction.atomic():
        gasto = _lock_gasto(gasto_id)
        if gasto.estado == GE.CANCELADO:
            raise ReglaNegocioError("El gasto ya está cancelado.")
        if gasto.estado not in (GE.PENDIENTE, GE.APROBADO):
            raise ReglaNegocioError("No se puede cancelar un gasto que ya tiene pagos efectuados.")
        if gasto.pagos.filter(estado=PE.EFECTUADO).exists():
            raise ReglaNegocioError("No se puede cancelar un gasto que ya tiene pagos efectuados.")
        # Cancelación en cascada de los pagos aún no efectuados.
        for pago in gasto.pagos.select_for_update().filter(estado__in=[PE.PENDIENTE, PE.APROBADO]):
            anterior = pago.estado
            pago.estado = PE.CANCELADO
            pago.save(update_fields=["estado", "actualizado"])
            _bitacora(usuario, anterior, PE.CANCELADO, f"Cancelado por cancelación del gasto {gasto.folio}", pago=pago)
        anterior = gasto.estado
        gasto.estado = GE.CANCELADO
        gasto.save(update_fields=["estado", "actualizado"])
        _bitacora(usuario, anterior, GE.CANCELADO, motivo or "Gasto cancelado", gasto=gasto)
        return gasto


# ---------------------------------------------------------------- PAGOS

def generar_pago(gasto_id, usuario, cuenta, monto=None, metodo=Pago.Metodo.TRANSFERENCIA,
                 referencia="", idempotency_key=None):
    """Crea un pago ligado al gasto. Si no se indica monto, se toma el saldo disponible.

    Con la misma idempotency_key se devuelve el pago ya existente en lugar de duplicarlo.
    """
    idempotency_key = idempotency_key or uuid.uuid4()
    existente = Pago.objects.filter(idempotency_key=idempotency_key).first()
    if existente:
        return existente, False

    try:
        with transaction.atomic():
            gasto = _lock_gasto(gasto_id)
            if gasto.estado == GE.CANCELADO:
                raise ReglaNegocioError("No se pueden generar pagos para un gasto cancelado.")
            if gasto.estado not in (GE.APROBADO, GE.PAGADO_PARCIAL):
                raise ReglaNegocioError("El gasto debe estar aprobado antes de generar un pago.")
            disponible = gasto.disponible_para_pago
            if disponible <= 0:
                raise ReglaNegocioError("El gasto ya tiene pagos que cubren el total; "
                                        "no se permiten pagos duplicados.")
            monto = Decimal(monto) if monto is not None else disponible
            if monto <= 0:
                raise ReglaNegocioError("El monto del pago debe ser mayor a cero.")
            if monto > disponible:
                raise ReglaNegocioError(f"El monto excede lo pendiente por pagar del gasto (${disponible:,.2f}).")
            if not cuenta.activa:
                raise ReglaNegocioError("La cuenta bancaria seleccionada está inactiva.")
            pago = Pago.objects.create(
                gasto=gasto, cuenta=cuenta, monto=monto, metodo=metodo, referencia=referencia,
                idempotency_key=idempotency_key, creado_por=usuario,
            )
            tipo = "parcial" if monto < gasto.saldo_pendiente else "total"
            _bitacora(usuario, "", PE.PENDIENTE, f"Pago {tipo} generado desde el gasto {gasto.folio}", pago=pago)
            return pago, True
    except IntegrityError:
        # Carrera entre dos envíos simultáneos con la misma llave.
        return Pago.objects.get(idempotency_key=idempotency_key), False


def aprobar_pago(pago_id, usuario):
    with transaction.atomic():
        pago = _lock_pago(pago_id)
        if pago.estado == PE.CANCELADO:
            raise ReglaNegocioError("Un pago cancelado no se puede reactivar ni aprobar.")
        if pago.estado != PE.PENDIENTE:
            raise ReglaNegocioError(f"Sólo se aprueban pagos pendientes (estado actual: {pago.get_estado_display()}).")
        if pago.gasto.estado == GE.CANCELADO:
            raise ReglaNegocioError("El gasto asociado está cancelado.")
        pago.estado = PE.APROBADO
        pago.aprobado_por = usuario
        pago.save(update_fields=["estado", "aprobado_por", "actualizado"])
        _bitacora(usuario, PE.PENDIENTE, PE.APROBADO, "Pago aprobado", pago=pago)
        return pago


def cancelar_pago(pago_id, usuario, motivo=""):
    with transaction.atomic():
        pago = _lock_pago(pago_id)
        if pago.estado == PE.CANCELADO:
            raise ReglaNegocioError("El pago ya está cancelado.")
        if pago.estado == PE.EFECTUADO:
            raise ReglaNegocioError("Un pago efectuado no se puede cancelar.")
        anterior = pago.estado
        pago.estado = PE.CANCELADO
        pago.save(update_fields=["estado", "actualizado"])
        _bitacora(usuario, anterior, PE.CANCELADO, motivo or "Pago cancelado", pago=pago)
        return pago


def efectuar_pago(pago_id, usuario):
    """Ejecuta el pago: descuenta el saldo de la cuenta y actualiza el estado del gasto."""
    with transaction.atomic():
        pago = _lock_pago(pago_id)
        if pago.estado == PE.EFECTUADO:
            raise ReglaNegocioError("Este pago ya fue efectuado (se evitó un pago duplicado).")
        if pago.estado == PE.CANCELADO:
            raise ReglaNegocioError("Un pago cancelado no se puede efectuar.")
        if pago.estado != PE.APROBADO:
            raise ReglaNegocioError("El pago debe estar aprobado antes de efectuarse.")
        gasto = _lock_gasto(pago.gasto_id)
        if gasto.estado not in (GE.APROBADO, GE.PAGADO_PARCIAL):
            raise ReglaNegocioError("El gasto debe estar aprobado para poder pagarse.")
        if pago.monto > gasto.saldo_pendiente:
            raise ReglaNegocioError("El pago excede el saldo pendiente del gasto.")
        cuenta = CuentaBancaria.objects.select_for_update().get(pk=pago.cuenta_id)
        if not cuenta.activa:
            raise ReglaNegocioError("La cuenta bancaria está inactiva.")
        if pago.monto > cuenta.saldo:
            raise ReglaNegocioError(
                f"Saldo insuficiente en {cuenta.nombre}: disponible ${cuenta.saldo:,.2f}, "
                f"pago ${pago.monto:,.2f}.")

        ahora = timezone.now()
        cuenta.saldo -= pago.monto
        cuenta.save(update_fields=["saldo"])
        MovimientoCuenta.objects.create(
            cuenta=cuenta, pago=pago, tipo=MovimientoCuenta.Tipo.CARGO, monto=pago.monto,
            saldo_resultante=cuenta.saldo, fecha=ahora, usuario=usuario,
            descripcion=f"Pago {pago.folio} - {gasto.folio} {gasto.proveedor.nombre}",
        )
        pago.estado = PE.EFECTUADO
        pago.fecha_pago = ahora
        pago.efectuado_por = usuario
        pago.save(update_fields=["estado", "fecha_pago", "efectuado_por", "actualizado"])
        _bitacora(usuario, PE.APROBADO, PE.EFECTUADO, f"Pago efectuado desde {cuenta.nombre}", pago=pago)

        anterior = gasto.estado
        gasto.estado = GE.PAGADO if gasto.saldo_pendiente <= 0 else GE.PAGADO_PARCIAL
        if gasto.estado != anterior:
            gasto.save(update_fields=["estado", "actualizado"])
            _bitacora(usuario, anterior, gasto.estado, f"Actualizado por pago {pago.folio}", gasto=gasto)
        return pago


# ---------------------------------------------------------------- CUENTAS

def abonar_cuenta(cuenta_id, usuario, monto, descripcion="Depósito"):
    monto = Decimal(monto)
    if monto <= 0:
        raise ReglaNegocioError("El abono debe ser mayor a cero.")
    with transaction.atomic():
        cuenta = CuentaBancaria.objects.select_for_update().get(pk=cuenta_id)
        cuenta.saldo += monto
        cuenta.save(update_fields=["saldo"])
        return MovimientoCuenta.objects.create(
            cuenta=cuenta, tipo=MovimientoCuenta.Tipo.ABONO, monto=monto,
            saldo_resultante=cuenta.saldo, fecha=timezone.now(), usuario=usuario,
            descripcion=descripcion,
        )


def crear_cuenta(usuario, **datos):
    with transaction.atomic():
        saldo_inicial = datos.get("saldo_inicial") or Decimal("0")
        cuenta = CuentaBancaria.objects.create(saldo=saldo_inicial, **datos)
        if saldo_inicial > 0:
            MovimientoCuenta.objects.create(
                cuenta=cuenta, tipo=MovimientoCuenta.Tipo.ABONO, monto=saldo_inicial,
                saldo_resultante=saldo_inicial, fecha=timezone.now(), usuario=usuario,
                descripcion="Saldo inicial",
            )
        return cuenta
