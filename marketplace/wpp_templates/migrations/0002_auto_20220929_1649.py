# Generated by Django 3.2.4 on 2022-09-29 19:49

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("wpp_templates", "0001_initial"),
    ]

    operations = [
        migrations.AlterField(
            model_name="templateheader",
            name="example",
            field=models.CharField(default=None, max_length=2048, null=True),
        ),
        migrations.AlterField(
            model_name="templatetranslation",
            name="body",
            field=models.CharField(max_length=2048, null=True),
        ),
    ]
