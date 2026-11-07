from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("finanzas", "0001_initial"),
    ]

    operations = [
        migrations.AlterField(
            model_name="cuentabancaria",
            name="moneda",
            field=models.CharField(choices=[("MXN", "Peso mexicano")], default="MXN", max_length=3),
        ),
    ]
