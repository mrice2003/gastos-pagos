"""Carga datos de demostración (sólo si la base está vacía)."""
import random
import uuid
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from finanzas import services
from finanzas.models import CuentaBancaria, Gasto, MovimientoCuenta, Pago, Proveedor

PROVEEDORES = [
    ("Papelería del Centro SA de CV", "PCE010101AB1", "ventas@papeleriacentro.mx"),
    ("Telmex Empresarial", "TME840315KT6", "empresas@telmex.example"),
    ("CFE Suministrador", "CSS160330CP7", "facturacion@cfe.example"),
    ("Soluciones TI Norte", "STN190505QX2", "contacto@soltinorte.mx"),
    ("Transportes Rápidos del Bajío", "TRB120720MN4", "cobranza@trb.mx"),
    ("Despacho Contable Hernández", "DCH050911LP9", "admin@dchernandez.mx"),
]

GASTOS = [
    ("Papelería y consumibles de oficina", "MATERIALES", 0, "3480.50"),
    ("Servicio de internet y telefonía", "SERVICIOS", 1, "2899.00"),
    ("Energía eléctrica bimestral", "SERVICIOS", 2, "12450.00"),
    ("Licencias de software anuales", "TECNOLOGIA", 3, "48000.00"),
    ("Flete de mercancía a Querétaro", "OPERACION", 4, "15600.00"),
    ("Honorarios contables del mes", "SERVICIOS", 5, "9500.00"),
    ("Mantenimiento de servidores", "TECNOLOGIA", 3, "22300.00"),
    ("Tóner e impresiones", "MATERIALES", 0, "5120.75"),
    ("Viáticos visita a cliente Monterrey", "VIATICOS", 4, "7840.00"),
    ("Declaración de impuestos (asesoría)", "IMPUESTOS", 5, "6200.00"),
    ("Equipo de cómputo (2 laptops)", "TECNOLOGIA", 3, "38900.00"),
    ("Paquetería y mensajería", "OPERACION", 4, "2150.00"),
    ("Telefonía celular corporativa", "SERVICIOS", 1, "4380.00"),
    ("Material de limpieza", "MATERIALES", 0, "1890.40"),
    ("Capacitación de personal", "OTROS", 5, "14500.00"),
    ("Fletes de distribución local", "OPERACION", 4, "8750.00"),
    ("Hosting y dominio", "TECNOLOGIA", 3, "3600.00"),
    ("Energía eléctrica (sucursal)", "SERVICIOS", 2, "5430.00"),
    ("Mobiliario de oficina", "MATERIALES", 0, "18200.00"),
    ("Comidas con clientes", "VIATICOS", 5, "3275.00"),
]

# Destino de cada gasto: (estado final deseado)
DESTINO = ["PAGADO", "PAGADO", "PAGADO", "PARCIAL", "PAGADO", "PAGADO", "PAGO_APROBADO",
           "PAGADO", "PENDIENTE", "PAGO_PENDIENTE", "PARCIAL", "PAGADO", "APROBADO", "CANCELADO",
           "PENDIENTE", "PAGADO", "PAGADO", "APROBADO", "PENDIENTE", "PAGADO"]


class Command(BaseCommand):
    help = "Carga datos de demostración si no existen gastos."

    @transaction.atomic
    def handle(self, *args, **opts):
        if Gasto.objects.exists():
            self.stdout.write("Ya existen datos; se omite la carga de demostración.")
            return
        random.seed(42)
        User = get_user_model()
        user = User.objects.filter(is_superuser=True).first()
        if user is None:
            user, _ = User.objects.get_or_create(username="sistema", defaults={"is_active": False})

        provs = [Proveedor.objects.get_or_create(nombre=n, defaults={"rfc": r, "email": e})[0]
                 for n, r, e in PROVEEDORES]
        cuentas = []
        for banco, nombre, numero, saldo in [
            ("BBVA", "Operativa principal", "012180001234567890", "250000.00"),
            ("Banorte", "Nómina y servicios", "072180009876543210", "120000.00"),
            ("Santander", "Reserva", "014180005555444433", "60000.00"),
        ]:
            c = CuentaBancaria.objects.filter(numero=numero).first() or services.crear_cuenta(
                user, banco=banco, nombre=nombre, numero=numero, saldo_inicial=Decimal(saldo))
            cuentas.append(c)
        # Fecha del saldo inicial: hace 6 meses
        hoy = timezone.now()
        MovimientoCuenta.objects.filter(cuenta__in=cuentas, descripcion="Saldo inicial").update(fecha=hoy - timedelta(days=185))

        for i, ((concepto, cat, prov, monto), destino) in enumerate(zip(GASTOS, DESTINO)):
            dias = 175 - i * 9
            fecha = (hoy - timedelta(days=dias)).date()
            g = services.crear_gasto(user, proveedor=provs[prov], concepto=concepto, categoria=cat,
                                     monto=Decimal(monto), fecha=fecha,
                                     fecha_vencimiento=fecha + timedelta(days=30))
            if destino == "PENDIENTE":
                continue
            if destino == "CANCELADO":
                services.cancelar_gasto(g.pk, user, "Proveedor no entregó el servicio")
                continue
            services.aprobar_gasto(g.pk, user)
            if destino == "APROBADO":
                continue
            cuenta = cuentas[i % 3]
            monto_pago = g.monto if destino != "PARCIAL" else (g.monto / 2).quantize(Decimal("0.01"))
            pago, _ = services.generar_pago(g.pk, user, cuenta=cuenta, monto=monto_pago,
                                            referencia=f"REF{1000 + i}", idempotency_key=uuid.uuid4())
            if destino == "PAGO_PENDIENTE":
                continue
            services.aprobar_pago(pago.pk, user)
            if destino == "PAGO_APROBADO":
                continue
            services.efectuar_pago(pago.pk, user)
            fecha_pago = hoy - timedelta(days=max(dias - random.randint(3, 12), 0))
            Pago.objects.filter(pk=pago.pk).update(fecha_pago=fecha_pago)
            MovimientoCuenta.objects.filter(pago=pago).update(fecha=fecha_pago)

        # Recalcular saldo_resultante en orden cronológico tras ajustar fechas
        for c in cuentas:
            saldo = Decimal("0")
            for m in c.movimientos.order_by("fecha", "id"):
                saldo += m.monto if m.tipo == MovimientoCuenta.Tipo.ABONO else -m.monto
                MovimientoCuenta.objects.filter(pk=m.pk).update(saldo_resultante=saldo)
        self.stdout.write(self.style.SUCCESS(
            f"Datos de demostración cargados: {len(provs)} proveedores, {len(cuentas)} cuentas, "
            f"{len(GASTOS)} gastos, {Pago.objects.count()} pagos."))
