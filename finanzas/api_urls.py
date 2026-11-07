from django.urls import include, path
from rest_framework.routers import DefaultRouter

from . import api

router = DefaultRouter()
router.register("gastos", api.GastoViewSet)
router.register("pagos", api.PagoViewSet)
router.register("cuentas", api.CuentaViewSet)
router.register("movimientos", api.MovimientoViewSet)
router.register("proveedores", api.ProveedorViewSet)

urlpatterns = [
    path("resumen/", api.resumen, name="api_resumen"),
    path("", include(router.urls)),
]
