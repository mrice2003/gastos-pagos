import uuid
from decimal import Decimal
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from . import services
from .models import Gasto, MovimientoCuenta, Pago, Proveedor
from .services import ReglaNegocioError

D = Decimal


class BaseTest(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user("tester", password="clave-segura-123")
        self.prov = Proveedor.objects.create(nombre="Proveedor X")
        self.cuenta = services.crear_cuenta(self.user, banco="BBVA", nombre="Principal",
                                            numero="0001", saldo_inicial=D("1000.00"))

    def gasto(self, monto="500.00", aprobar=True):
        g = services.crear_gasto(self.user, proveedor=self.prov, concepto="Prueba",
                                 monto=D(monto), fecha=timezone.localdate())
        if aprobar:
            services.aprobar_gasto(g.pk, self.user)
        return g

    def pago_listo(self, gasto, monto=None):
        p, _ = services.generar_pago(gasto.pk, self.user, cuenta=self.cuenta, monto=monto)
        services.aprobar_pago(p.pk, self.user)
        return p


class ReglasGastoTest(BaseTest):
    def test_gasto_debe_estar_aprobado_antes_de_pagar(self):
        g = self.gasto(aprobar=False)
        with self.assertRaisesMessage(ReglaNegocioError, "aprobado"):
            services.generar_pago(g.pk, self.user, cuenta=self.cuenta)

    def test_generar_pago_toma_saldo_pendiente_por_defecto(self):
        g = self.gasto("300.00")
        p, creado = services.generar_pago(g.pk, self.user, cuenta=self.cuenta)
        self.assertTrue(creado)
        self.assertEqual(p.monto, D("300.00"))
        self.assertEqual(p.estado, Pago.Estado.PENDIENTE)

    def test_gasto_cancelado_no_se_reactiva(self):
        g = self.gasto(aprobar=False)
        services.cancelar_gasto(g.pk, self.user)
        with self.assertRaises(ReglaNegocioError):
            services.aprobar_gasto(g.pk, self.user)
        with self.assertRaises(ReglaNegocioError):
            services.cancelar_gasto(g.pk, self.user)
        with self.assertRaises(ReglaNegocioError):
            services.generar_pago(g.pk, self.user, cuenta=self.cuenta)
        g.refresh_from_db()
        self.assertEqual(g.estado, Gasto.Estado.CANCELADO)

    def test_cancelar_gasto_cancela_sus_pagos_no_efectuados(self):
        g = self.gasto()
        p = self.pago_listo(g)
        services.cancelar_gasto(g.pk, self.user)
        p.refresh_from_db()
        self.assertEqual(p.estado, Pago.Estado.CANCELADO)

    def test_no_se_cancela_gasto_con_pagos_efectuados(self):
        g = self.gasto("500.00")
        services.efectuar_pago(self.pago_listo(g, D("100.00")).pk, self.user)
        with self.assertRaises(ReglaNegocioError):
            services.cancelar_gasto(g.pk, self.user)


    def test_editar_gasto_cancelado_no_lo_reactiva(self):
        self.client.login(username="tester", password="clave-segura-123")
        g = self.gasto("100.00", aprobar=False)
        url = reverse("gasto_edit", args=[g.pk])
        datos = {"proveedor": self.prov.pk, "concepto": "Editado", "categoria": "OPERACION",
                 "monto": "120.00", "fecha": timezone.localdate().isoformat()}
        self.client.post(url, datos)
        g.refresh_from_db()
        self.assertEqual((g.concepto, g.monto, g.estado), ("Editado", D("120.00"), Gasto.Estado.PENDIENTE))
        services.cancelar_gasto(g.pk, self.user)
        with self.assertRaises(ReglaNegocioError):
            services.editar_gasto(g.pk, concepto="Otra vez")
        g.refresh_from_db()
        self.assertEqual((g.concepto, g.estado), ("Editado", Gasto.Estado.CANCELADO))


class ReglasPagoTest(BaseTest):
    def test_pago_no_puede_exceder_saldo_de_cuenta(self):
        g = self.gasto("1500.00")
        p = self.pago_listo(g)
        with self.assertRaisesMessage(ReglaNegocioError, "Saldo insuficiente"):
            services.efectuar_pago(p.pk, self.user)
        self.cuenta.refresh_from_db()
        self.assertEqual(self.cuenta.saldo, D("1000.00"))

    def test_pago_no_puede_exceder_pendiente_del_gasto(self):
        g = self.gasto("200.00")
        with self.assertRaises(ReglaNegocioError):
            services.generar_pago(g.pk, self.user, cuenta=self.cuenta, monto=D("250.00"))

    def test_pagos_parciales(self):
        g = self.gasto("500.00")
        services.efectuar_pago(self.pago_listo(g, D("200.00")).pk, self.user)
        g.refresh_from_db()
        self.assertEqual(g.estado, Gasto.Estado.PAGADO_PARCIAL)
        self.assertEqual(g.saldo_pendiente, D("300.00"))
        services.efectuar_pago(self.pago_listo(g).pk, self.user)
        g.refresh_from_db()
        self.assertEqual(g.estado, Gasto.Estado.PAGADO)
        self.cuenta.refresh_from_db()
        self.assertEqual(self.cuenta.saldo, D("500.00"))
        self.assertEqual(MovimientoCuenta.objects.filter(tipo="CARGO").count(), 2)

    def test_misma_llave_no_duplica_pago(self):
        g = self.gasto("500.00")
        key = uuid.uuid4()
        p1, c1 = services.generar_pago(g.pk, self.user, cuenta=self.cuenta, monto=D("100"), idempotency_key=key)
        p2, c2 = services.generar_pago(g.pk, self.user, cuenta=self.cuenta, monto=D("100"), idempotency_key=key)
        self.assertTrue(c1)
        self.assertFalse(c2)
        self.assertEqual(p1.pk, p2.pk)
        self.assertEqual(g.pagos.count(), 1)

    def test_doble_envio_concurrente_por_el_total_devuelve_el_pago_existente(self):
        g = self.gasto("500.00")
        key = uuid.uuid4()
        lock_real = services._lock_gasto
        primero = {}

        def otro_envio_gana_la_carrera(gasto_id):
            if not primero:
                primero["pago"] = None
                primero["pago"], _ = services.generar_pago(gasto_id, self.user, cuenta=self.cuenta,
                                                           idempotency_key=key)
            return lock_real(gasto_id)

        with mock.patch.object(services, "_lock_gasto", side_effect=otro_envio_gana_la_carrera):
            pago, creado = services.generar_pago(g.pk, self.user, cuenta=self.cuenta, idempotency_key=key)
        self.assertFalse(creado)
        self.assertEqual(pago.pk, primero["pago"].pk)
        self.assertEqual(g.pagos.count(), 1)

    def test_no_se_programa_mas_del_total(self):
        g = self.gasto("500.00")
        services.generar_pago(g.pk, self.user, cuenta=self.cuenta)
        with self.assertRaisesMessage(ReglaNegocioError, "duplicados"):
            services.generar_pago(g.pk, self.user, cuenta=self.cuenta)

    def test_no_se_efectua_dos_veces(self):
        g = self.gasto("100.00")
        p = self.pago_listo(g)
        services.efectuar_pago(p.pk, self.user)
        with self.assertRaisesMessage(ReglaNegocioError, "ya fue efectuado"):
            services.efectuar_pago(p.pk, self.user)
        self.cuenta.refresh_from_db()
        self.assertEqual(self.cuenta.saldo, D("900.00"))

    def test_pago_debe_aprobarse_antes_de_efectuar(self):
        g = self.gasto("100.00")
        p, _ = services.generar_pago(g.pk, self.user, cuenta=self.cuenta)
        with self.assertRaises(ReglaNegocioError):
            services.efectuar_pago(p.pk, self.user)

    def test_pago_cancelado_no_se_reactiva_y_libera_monto(self):
        g = self.gasto("100.00")
        p, _ = services.generar_pago(g.pk, self.user, cuenta=self.cuenta)
        services.cancelar_pago(p.pk, self.user)
        for fn in (services.aprobar_pago, services.efectuar_pago, services.cancelar_pago):
            with self.assertRaises(ReglaNegocioError):
                fn(p.pk, self.user)
        g.refresh_from_db()
        self.assertEqual(g.disponible_para_pago, D("100.00"))

    def test_pago_efectuado_no_se_cancela(self):
        g = self.gasto("100.00")
        p = self.pago_listo(g)
        services.efectuar_pago(p.pk, self.user)
        with self.assertRaises(ReglaNegocioError):
            services.cancelar_pago(p.pk, self.user)


class VistasYApiTest(BaseTest):
    def test_login_requerido(self):
        r = self.client.get(reverse("dashboard"))
        self.assertEqual(r.status_code, 302)

    def test_paginas_principales(self):
        self.client.login(username="tester", password="clave-segura-123")
        g = self.gasto()
        p, _ = services.generar_pago(g.pk, self.user, cuenta=self.cuenta, monto=D("50"))
        for url in [reverse("dashboard"), reverse("gasto_list"), reverse("gasto_detail", args=[g.pk]),
                    reverse("pago_list"), reverse("pago_detail", args=[p.pk]), reverse("cuenta_list"),
                    reverse("cuenta_detail", args=[self.cuenta.pk]), reverse("proveedor_list"),
                    reverse("gasto_create")]:
            self.assertEqual(self.client.get(url).status_code, 200, url)

    def test_boton_generar_pago_y_doble_envio(self):
        self.client.login(username="tester", password="clave-segura-123")
        g = self.gasto("400.00")
        datos = {"cuenta": self.cuenta.pk, "monto": "150.00", "metodo": "TRANSFERENCIA",
                 "referencia": "", "idempotency_key": str(uuid.uuid4())}
        url = reverse("gasto_generar_pago", args=[g.pk])
        self.client.post(url, datos)
        self.client.post(url, datos)  # doble clic
        self.assertEqual(g.pagos.count(), 1)

    def test_api_requiere_autenticacion_y_es_solo_lectura(self):
        api = APIClient()
        self.assertIn(api.get("/api/gastos/").status_code, (401, 403))
        api.credentials(HTTP_AUTHORIZATION="Basic dGVzdGVyOmNsYXZlLXNlZ3VyYS0xMjM=")  # tester:clave-segura-123
        self.gasto()
        r = api.get("/api/gastos/")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["count"], 1)
        for url in ["/api/pagos/", "/api/cuentas/", f"/api/cuentas/{self.cuenta.pk}/movimientos/",
                    "/api/movimientos/", "/api/proveedores/", "/api/resumen/", "/api/gastos/?estado=APROBADO"]:
            self.assertEqual(api.get(url).status_code, 200, url)
        self.assertEqual(api.post("/api/gastos/", {}).status_code, 405)

    def test_filtros_invalidos_se_ignoran_en_html_y_dan_400_en_api(self):
        self.client.login(username="tester", password="clave-segura-123")
        self.gasto()
        for url in ["?proveedor=abc", "?desde=hoy", "?hasta=2024-99-99"]:
            r = self.client.get(reverse("gasto_list") + url)
            self.assertEqual(r.status_code, 200, url)
            self.assertEqual(len(r.context["page"].object_list), 1, url)
        self.assertEqual(self.client.get(reverse("pago_list") + "?cuenta=x").status_code, 200)
        api = APIClient()
        api.force_authenticate(self.user)
        for url in ["/api/gastos/?proveedor=x", "/api/gastos/?desde=hoy", "/api/gastos/?hasta=2024-99-99",
                    "/api/pagos/?gasto=x", "/api/pagos/?cuenta=x"]:
            self.assertEqual(api.get(url).status_code, 400, url)
        r = api.get(f"/api/gastos/?proveedor={self.prov.pk}&desde=2000-01-01")
        self.assertEqual(r.json()["count"], 1)

    def test_proveedores_excluyen_gastos_cancelados(self):
        self.client.login(username="tester", password="clave-segura-123")
        self.gasto("300.00")
        services.cancelar_gasto(self.gasto("5000.00", aprobar=False).pk, self.user)
        prov = self.client.get(reverse("proveedor_list")).context["proveedores"].get(pk=self.prov.pk)
        self.assertEqual(prov.n, 1)
        self.assertEqual(prov.total, D("300.00"))
