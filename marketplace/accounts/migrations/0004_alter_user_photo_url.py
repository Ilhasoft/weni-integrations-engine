# Generated by Django 3.2.4 on 2021-10-22 12:33

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0003_auto_20211001_1029"),
    ]

    operations = [
        migrations.AlterField(
            model_name="user",
            name="photo_url",
            field=models.URLField(blank=True, max_length=255),
        ),
    ]
