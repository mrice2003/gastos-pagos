"""API REST de solo lectura (GET). Autenticación: HTTP Basic o sesión."""
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema, extend_schema_view
from rest_framework import viewsets
from rest_framework.decorators import action, api_view
from rest_framework.response import Response

from .models import CuentaBancaria, Gasto, MovimientoCuenta, Pago, Proveedor
from .serializers import (CuentaBancariaSerializer, GastoDetalleSerializer, GastoSerializer,
                          MovimientoCuentaSerializer, PagoDetalleSerializer, PagoSerializer,
                          ProveedorSerializer)
from .views import resumen_datos


def _param(nombre, desc, tipo=OpenApiTypes.STR, enum=None):
    return OpenApiParameter(nombre, tipo, OpenApiParameter.QUERY, required=False, description=desc, enum=enum)


@extend_schema_view(
    list=extend_schema(summary="Listar gastos", parameters=[
        _param("estado", "Filtra por estado", enum=Gasto.Estado.values),
        _param("categoria", "Filtra por categoría", enum=Gasto.Categoria.values),
        _param("proveedor", "ID del proveedor", OpenApiTypes.INT),
        _param("desde", "Fecha inicial (YYYY-MM-DD)", OpenApiTypes.DATE),
        _param("hasta", "Fecha final (YYYY-MM-DD)", OpenApiTypes.DATE),
    ]),
    retrieve=extend_schema(summary="Detalle de un gasto (incluye pagos y bitácora)"),
)
class GastoViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Gasto.objects.select_related("proveedor", "creado_por", "aprobado_por")

    def get_serializer_class(self):
        return GastoDetalleSerializer if self.action == "retrieve" else GastoSerializer

    def get_queryset(self):
        qs = super().get_queryset()
        p = self.request.query_params
        if p.get("estado"):
            qs = qs.filter(estado=p["estado"])
        if p.get("categoria"):
            qs = qs.filter(categoria=p["categoria"])
        if p.get("proveedor"):
            qs = qs.filter(proveedor_id=p["proveedor"])
        if p.get("desde"):
            qs = qs.filter(fecha__gte=p["desde"])
        if p.get("hasta"):
            qs = qs.filter(fecha__lte=p["hasta"])
        return qs


@extend_schema_view(
    list=extend_schema(summary="Listar pagos", parameters=[
        _param("estado", "Filtra por estado", enum=Pago.Estado.values),
        _param("gasto", "ID del gasto", OpenApiTypes.INT),
        _param("cuenta", "ID de la cuenta bancaria", OpenApiTypes.INT),
    ]),
    retrieve=extend_schema(summary="Detalle de un pago (incluye bitácora)"),
)
class PagoViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Pago.objects.select_related("gasto", "cuenta", "creado_por", "aprobado_por", "efectuado_por")

    def get_serializer_class(self):
        return PagoDetalleSerializer if self.action == "retrieve" else PagoSerializer

    def get_queryset(self):
        qs = super().get_queryset()
        p = self.request.query_params
        if p.get("estado"):
            qs = qs.filter(estado=p["estado"])
        if p.get("gasto"):
            qs = qs.filter(gasto_id=p["gasto"])
        if p.get("cuenta"):
            qs = qs.filter(cuenta_id=p["cuenta"])
        return qs


@extend_schema_view(
    list=extend_schema(summary="Listar cuentas bancarias con su saldo"),
    retrieve=extend_schema(summary="Detalle de una cuenta bancaria"),
)
class CuentaViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = CuentaBancaria.objects.all()
    serializer_class = CuentaBancariaSerializer

    @extend_schema(summary="Movimientos (cargos/abonos) de una cuenta",
                   responses=MovimientoCuentaSerializer(many=True))
    @action(detail=True)
    def movimientos(self, request, pk=None):
        qs = self.get_object().movimientos.select_related("cuenta", "pago")
        page = self.paginate_queryset(qs)
        return self.get_paginated_response(MovimientoCuentaSerializer(page, many=True).data)


@extend_schema_view(
    list=extend_schema(summary="Listar movimientos de todas las cuentas", parameters=[
        _param("tipo", "CARGO o ABONO", enum=MovimientoCuenta.Tipo.values),
    ]),
    retrieve=extend_schema(summary="Detalle de un movimiento"),
)
class MovimientoViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = MovimientoCuenta.objects.select_related("cuenta", "pago")
    serializer_class = MovimientoCuentaSerializer

    def get_queryset(self):
        qs = super().get_queryset()
        if self.request.query_params.get("tipo"):
            qs = qs.filter(tipo=self.request.query_params["tipo"])
        return qs


@extend_schema_view(
    list=extend_schema(summary="Listar proveedores"),
    retrieve=extend_schema(summary="Detalle de un proveedor"),
)
class ProveedorViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Proveedor.objects.all()
    serializer_class = ProveedorSerializer


@extend_schema(summary="Resumen / KPIs del tablero", responses=OpenApiTypes.OBJECT)
@api_view(["GET"])
def resumen(request):
    return Response(resumen_datos())
