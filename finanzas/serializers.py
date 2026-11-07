from rest_framework import serializers

from .models import BitacoraEstado, CuentaBancaria, Gasto, MovimientoCuenta, Pago, Proveedor


class ProveedorSerializer(serializers.ModelSerializer):
    class Meta:
        model = Proveedor
        fields = ["id", "nombre", "rfc", "email", "telefono", "creado"]


class CuentaBancariaSerializer(serializers.ModelSerializer):
    class Meta:
        model = CuentaBancaria
        fields = ["id", "banco", "nombre", "numero", "moneda", "saldo_inicial", "saldo", "activa", "creado"]


class MovimientoCuentaSerializer(serializers.ModelSerializer):
    cuenta = serializers.StringRelatedField()
    pago = serializers.SlugRelatedField(slug_field="folio", read_only=True)

    class Meta:
        model = MovimientoCuenta
        fields = ["id", "cuenta", "tipo", "monto", "saldo_resultante", "descripcion", "pago", "fecha"]


class BitacoraSerializer(serializers.ModelSerializer):
    usuario = serializers.StringRelatedField()

    class Meta:
        model = BitacoraEstado
        fields = ["estado_anterior", "estado_nuevo", "comentario", "usuario", "fecha"]


class PagoResumenSerializer(serializers.ModelSerializer):
    cuenta = serializers.StringRelatedField()

    class Meta:
        model = Pago
        fields = ["id", "folio", "monto", "estado", "cuenta", "fecha_pago"]


class PagoSerializer(serializers.ModelSerializer):
    gasto = serializers.SlugRelatedField(slug_field="folio", read_only=True)
    gasto_id = serializers.IntegerField(read_only=True)
    cuenta = serializers.StringRelatedField()
    cuenta_id = serializers.IntegerField(read_only=True)
    creado_por = serializers.StringRelatedField()
    aprobado_por = serializers.StringRelatedField()
    efectuado_por = serializers.StringRelatedField()

    class Meta:
        model = Pago
        fields = ["id", "folio", "gasto", "gasto_id", "cuenta", "cuenta_id", "monto", "metodo",
                  "referencia", "estado", "fecha_pago", "creado_por", "aprobado_por",
                  "efectuado_por", "creado", "actualizado"]


class PagoDetalleSerializer(PagoSerializer):
    bitacora = BitacoraSerializer(many=True, read_only=True)

    class Meta(PagoSerializer.Meta):
        fields = PagoSerializer.Meta.fields + ["bitacora"]


class GastoSerializer(serializers.ModelSerializer):
    proveedor = serializers.StringRelatedField()
    proveedor_id = serializers.IntegerField(read_only=True)
    creado_por = serializers.StringRelatedField()
    aprobado_por = serializers.StringRelatedField()
    monto_pagado = serializers.DecimalField(max_digits=14, decimal_places=2, read_only=True)
    saldo_pendiente = serializers.DecimalField(max_digits=14, decimal_places=2, read_only=True)

    class Meta:
        model = Gasto
        fields = ["id", "folio", "proveedor", "proveedor_id", "concepto", "categoria", "monto",
                  "monto_pagado", "saldo_pendiente", "fecha", "fecha_vencimiento", "estado",
                  "notas", "creado_por", "aprobado_por", "creado", "actualizado"]


class GastoDetalleSerializer(GastoSerializer):
    pagos = PagoResumenSerializer(many=True, read_only=True)
    bitacora = BitacoraSerializer(many=True, read_only=True)

    class Meta(GastoSerializer.Meta):
        fields = GastoSerializer.Meta.fields + ["pagos", "bitacora"]
