# Generated by Django 4.0.6 on 2022-07-05 03:58

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('v2', '0006_googleuser'),
    ]

    operations = [
        migrations.AddField(
            model_name='user',
            name='google_id',
            field=models.CharField(blank=True, max_length=100, null=True, unique=True),
        ),
        migrations.DeleteModel(
            name='GoogleUser',
        ),
    ]
