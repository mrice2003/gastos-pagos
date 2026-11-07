import uuid

from django import forms

from .models import CuentaBancaria, Gasto, Pago, Proveedor


class BootstrapMixin:
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            widget = field.widget
            if isinstance(widget, forms.HiddenInput):
                continue
            if isinstance(widget, forms.CheckboxInput):
                widget.attrs.setdefault("class", "form-check-input")
            elif isinstance(widget, forms.Select):
                widget.attrs.setdefault("class", "form-select")
            else:
                widget.attrs.setdefault("class", "form-control")


class ProveedorForm(BootstrapMixin, forms.ModelForm):
    class Meta:
        model = Proveedor
        fields = ["nombre", "rfc", "email", "telefono"]


class GastoForm(BootstrapMixin, forms.ModelForm):
    class Meta:
        model = Gasto
        fields = ["proveedor", "concepto", "categoria", "monto", "fecha", "fecha_vencimiento", "notas"]
        widgets = {
            "fecha": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
            "fecha_vencimiento": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
            "notas": forms.Textarea(attrs={"rows": 3}),
        }


class CuentaForm(BootstrapMixin, forms.ModelForm):
    class Meta:
        model = CuentaBancaria
        fields = ["banco", "nombre", "numero", "moneda", "saldo_inicial", "activa"]


class CuentaEditForm(BootstrapMixin, forms.ModelForm):
    """Al editar no se toca el saldo: sólo cambia mediante movimientos."""
    class Meta:
        model = CuentaBancaria
        fields = ["banco", "nombre", "activa"]


class AbonoForm(BootstrapMixin, forms.Form):
    monto = forms.DecimalField(max_digits=14, decimal_places=2, min_value=0.01)
    descripcion = forms.CharField(max_length=200, initial="Depósito")


class GenerarPagoForm(BootstrapMixin, forms.Form):
    cuenta = forms.ModelChoiceField(queryset=CuentaBancaria.objects.filter(activa=True))
    monto = forms.DecimalField(max_digits=14, decimal_places=2, min_value=0.01,
                               help_text="Puede ser menor al pendiente (pago parcial).")
    metodo = forms.ChoiceField(choices=Pago.Metodo.choices)
    referencia = forms.CharField(max_length=60, required=False)
    idempotency_key = forms.UUIDField(widget=forms.HiddenInput, initial=uuid.uuid4)

    def __init__(self, *args, gasto=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["cuenta"].empty_label = None
        if gasto is not None and not self.is_bound:
            disponible = gasto.disponible_para_pago
            self.initial["monto"] = disponible
            self.fields["monto"].widget.attrs["max"] = str(disponible)
            # Preselecciona la cuenta con saldo suficiente (o la de mayor saldo)
            cuentas = self.fields["cuenta"].queryset.order_by("-saldo")
            cuenta = cuentas.filter(saldo__gte=disponible).last() or cuentas.first()
            if cuenta:
                self.initial["cuenta"] = cuenta.pk
        self.fields["cuenta"].label_from_instance = (
            lambda c: f"{c.nombre} · {c.banco} — saldo ${c.saldo:,.2f}")


class MotivoForm(BootstrapMixin, forms.Form):
    motivo = forms.CharField(max_length=255, required=False)
