from django.urls import path

from . import views

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("gastos/", views.gasto_list, name="gasto_list"),
    path("gastos/nuevo/", views.gasto_create, name="gasto_create"),
    path("gastos/<int:pk>/", views.gasto_detail, name="gasto_detail"),
    path("gastos/<int:pk>/editar/", views.gasto_edit, name="gasto_edit"),
    path("gastos/<int:pk>/aprobar/", views.gasto_aprobar, name="gasto_aprobar"),
    path("gastos/<int:pk>/cancelar/", views.gasto_cancelar, name="gasto_cancelar"),
    path("gastos/<int:pk>/generar-pago/", views.gasto_generar_pago, name="gasto_generar_pago"),
    path("pagos/", views.pago_list, name="pago_list"),
    path("pagos/<int:pk>/", views.pago_detail, name="pago_detail"),
    path("pagos/<int:pk>/aprobar/", views.pago_aprobar, name="pago_aprobar"),
    path("pagos/<int:pk>/cancelar/", views.pago_cancelar, name="pago_cancelar"),
    path("pagos/<int:pk>/efectuar/", views.pago_efectuar, name="pago_efectuar"),
    path("cuentas/", views.cuenta_list, name="cuenta_list"),
    path("cuentas/nueva/", views.cuenta_create, name="cuenta_create"),
    path("cuentas/<int:pk>/", views.cuenta_detail, name="cuenta_detail"),
    path("cuentas/<int:pk>/editar/", views.cuenta_edit, name="cuenta_edit"),
    path("cuentas/<int:pk>/abonar/", views.cuenta_abonar, name="cuenta_abonar"),
    path("proveedores/", views.proveedor_list, name="proveedor_list"),
    path("proveedores/nuevo/", views.proveedor_form, name="proveedor_create"),
    path("proveedores/<int:pk>/editar/", views.proveedor_form, name="proveedor_edit"),
]
