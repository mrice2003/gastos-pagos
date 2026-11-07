from decimal import Decimal

from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import Q, Sum

CENTAVO = Decimal("0.01")


class Proveedor(models.Model):
    nombre = models.CharField(max_length=150, unique=True)
    rfc = models.CharField("RFC", max_length=13, blank=True)
    email = models.EmailField(blank=True)
    telefono = models.CharField(max_length=20, blank=True)
    creado = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["nombre"]
        verbose_name_plural = "proveedores"

    def __str__(self):
        return self.nombre


class CuentaBancaria(models.Model):
    class Moneda(models.TextChoices):
        MXN = "MXN", "Peso mexicano"
        USD = "USD", "Dólar"

    banco = models.CharField(max_length=80)
    nombre = models.CharField("alias", max_length=100)
    numero = models.CharField("número de cuenta / CLABE", max_length=20, unique=True)
    moneda = models.CharField(max_length=3, choices=Moneda.choices, default=Moneda.MXN)
    saldo_inicial = models.DecimalField(max_digits=14, decimal_places=2, default=0,
                                        validators=[MinValueValidator(0)])
    saldo = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    activa = models.BooleanField(default=True)
    creado = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["banco", "nombre"]
        verbose_name = "cuenta bancaria"
        verbose_name_plural = "cuentas bancarias"
        constraints = [
            models.CheckConstraint(condition=Q(saldo__gte=0), name="cuenta_saldo_no_negativo"),
        ]

    def __str__(self):
        return f"{self.banco} - {self.nombre} (…{self.numero[-4:]})"


class Gasto(models.Model):
    class Estado(models.TextChoices):
        PENDIENTE = "PENDIENTE", "Pendiente"
        APROBADO = "APROBADO", "Aprobado"
        PAGADO_PARCIAL = "PAGADO_PARCIAL", "Pagado parcial"
        PAGADO = "PAGADO", "Pagado"
        CANCELADO = "CANCELADO", "Cancelado"

    class Categoria(models.TextChoices):
        OPERACION = "OPERACION", "Operación"
        NOMINA = "NOMINA", "Nómina"
        SERVICIOS = "SERVICIOS", "Servicios"
        MATERIALES = "MATERIALES", "Materiales"
        VIATICOS = "VIATICOS", "Viáticos"
        TECNOLOGIA = "TECNOLOGIA", "Tecnología"
        IMPUESTOS = "IMPUESTOS", "Impuestos"
        OTROS = "OTROS", "Otros"

    folio = models.CharField(max_length=12, unique=True, editable=False, blank=True)
    proveedor = models.ForeignKey(Proveedor, on_delete=models.PROTECT, related_name="gastos")
    concepto = models.CharField(max_length=200)
    categoria = models.CharField(max_length=20, choices=Categoria.choices, default=Categoria.OPERACION)
    monto = models.DecimalField(max_digits=14, decimal_places=2,
                                validators=[MinValueValidator(CENTAVO)])
    fecha = models.DateField()
    fecha_vencimiento = models.DateField(null=True, blank=True)
    notas = models.TextField(blank=True)
    estado = models.CharField(max_length=20, choices=Estado.choices, default=Estado.PENDIENTE)
    creado_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
                                   related_name="gastos_creados")
    aprobado_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
                                     related_name="gastos_aprobados", null=True, blank=True)
    creado = models.DateTimeField(auto_now_add=True)
    actualizado = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-fecha", "-id"]
        constraints = [
            models.CheckConstraint(condition=Q(monto__gt=0), name="gasto_monto_positivo"),
        ]

    def __str__(self):
        return f"{self.folio} - {self.concepto}"

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        if not self.folio:
            self.folio = f"G-{self.pk:05d}"
            super().save(update_fields=["folio"])

    # --- montos derivados ---
    def _suma_pagos(self, *estados):
        total = self.pagos.filter(estado__in=estados).aggregate(t=Sum("monto"))["t"]
        return total or Decimal("0")

    @property
    def monto_pagado(self):
        return self._suma_pagos(Pago.Estado.EFECTUADO)

    @property
    def monto_comprometido(self):
        """Pagos vivos (pendientes, aprobados o efectuados)."""
        return self._suma_pagos(Pago.Estado.PENDIENTE, Pago.Estado.APROBADO, Pago.Estado.EFECTUADO)

    @property
    def saldo_pendiente(self):
        return self.monto - self.monto_pagado

    @property
    def disponible_para_pago(self):
        """Lo que todavía se puede programar como pago nuevo."""
        return max(self.monto - self.monto_comprometido, Decimal("0"))

    @property
    def porcentaje_pagado(self):
        return int(self.monto_pagado * 100 / self.monto) if self.monto else 0

    @property
    def puede_aprobar(self):
        return self.estado == self.Estado.PENDIENTE

    @property
    def puede_cancelar(self):
        return (self.estado in (self.Estado.PENDIENTE, self.Estado.APROBADO)
                and not self.pagos.filter(estado=Pago.Estado.EFECTUADO).exists())

    @property
    def puede_generar_pago(self):
        return (self.estado in (self.Estado.APROBADO, self.Estado.PAGADO_PARCIAL)
                and self.disponible_para_pago > 0)


class Pago(models.Model):
    class Estado(models.TextChoices):
        PENDIENTE = "PENDIENTE", "Pendiente"
        APROBADO = "APROBADO", "Aprobado"
        EFECTUADO = "EFECTUADO", "Efectuado"
        CANCELADO = "CANCELADO", "Cancelado"

    class Metodo(models.TextChoices):
        TRANSFERENCIA = "TRANSFERENCIA", "Transferencia"
        CHEQUE = "CHEQUE", "Cheque"
        TARJETA = "TARJETA", "Tarjeta"

    folio = models.CharField(max_length=12, unique=True, editable=False, blank=True)
    gasto = models.ForeignKey(Gasto, on_delete=models.PROTECT, related_name="pagos")
    cuenta = models.ForeignKey(CuentaBancaria, on_delete=models.PROTECT, related_name="pagos")
    monto = models.DecimalField(max_digits=14, decimal_places=2,
                                validators=[MinValueValidator(CENTAVO)])
    metodo = models.CharField(max_length=20, choices=Metodo.choices, default=Metodo.TRANSFERENCIA)
    referencia = models.CharField(max_length=60, blank=True)
    estado = models.CharField(max_length=20, choices=Estado.choices, default=Estado.PENDIENTE)
    # Llave de idempotencia: evita que un doble envío del formulario cree dos pagos.
    idempotency_key = models.UUIDField(unique=True)
    fecha_pago = models.DateTimeField(null=True, blank=True)
    creado_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
                                   related_name="pagos_creados")
    aprobado_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
                                     related_name="pagos_aprobados", null=True, blank=True)
    efectuado_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
                                      related_name="pagos_efectuados", null=True, blank=True)
    creado = models.DateTimeField(auto_now_add=True)
    actualizado = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-creado", "-id"]
        constraints = [
            models.CheckConstraint(condition=Q(monto__gt=0), name="pago_monto_positivo"),
        ]

    def __str__(self):
        return f"{self.folio} → {self.gasto.folio}"

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        if not self.folio:
            self.folio = f"P-{self.pk:05d}"
            super().save(update_fields=["folio"])

    @property
    def puede_aprobar(self):
        return self.estado == self.Estado.PENDIENTE

    @property
    def puede_cancelar(self):
        return self.estado in (self.Estado.PENDIENTE, self.Estado.APROBADO)

    @property
    def puede_efectuar(self):
        return self.estado == self.Estado.APROBADO


class MovimientoCuenta(models.Model):
    class Tipo(models.TextChoices):
        CARGO = "CARGO", "Cargo (salida)"
        ABONO = "ABONO", "Abono (entrada)"

    cuenta = models.ForeignKey(CuentaBancaria, on_delete=models.PROTECT, related_name="movimientos")
    # OneToOne: un pago sólo puede generar un cargo (protección contra doble cobro).
    pago = models.OneToOneField(Pago, on_delete=models.PROTECT, null=True, blank=True,
                                related_name="movimiento")
    tipo = models.CharField(max_length=10, choices=Tipo.choices)
    monto = models.DecimalField(max_digits=14, decimal_places=2,
                                validators=[MinValueValidator(CENTAVO)])
    saldo_resultante = models.DecimalField(max_digits=14, decimal_places=2)
    descripcion = models.CharField(max_length=200)
    fecha = models.DateTimeField()
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True)

    class Meta:
        ordering = ["-fecha", "-id"]
        verbose_name = "movimiento de cuenta"
        verbose_name_plural = "movimientos de cuenta"

    def __str__(self):
        return f"{self.get_tipo_display()} {self.monto} {self.cuenta}"


class BitacoraEstado(models.Model):
    """Historial de cambios de estado de gastos y pagos (auditoría)."""
    gasto = models.ForeignKey(Gasto, on_delete=models.CASCADE, null=True, blank=True,
                              related_name="bitacora")
    pago = models.ForeignKey(Pago, on_delete=models.CASCADE, null=True, blank=True,
                             related_name="bitacora")
    estado_anterior = models.CharField(max_length=20, blank=True)
    estado_nuevo = models.CharField(max_length=20)
    comentario = models.CharField(max_length=255, blank=True)
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    fecha = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-fecha", "-id"]
        verbose_name = "bitácora de estado"
        verbose_name_plural = "bitácora de estados"
