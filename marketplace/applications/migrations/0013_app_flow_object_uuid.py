# Generated by Django 3.2.4 on 2022-03-31 21:40

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("applications", "0012_alter_apptypeasset_asset_type"),
    ]

    operations = [
        migrations.AddField(
            model_name="app",
            name="flow_object_uuid",
            field=models.UUIDField(null=True, unique=True),
        ),
    ]
