# Generated by Django 3.2.4 on 2023-03-13 18:52

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('wpp_templates', '0003_alter_templatemessage_name'),
    ]

    operations = [
        migrations.AlterField(
            model_name='templatebutton',
            name='text',
            field=models.CharField(max_length=30, null=True),
        ),
    ]
