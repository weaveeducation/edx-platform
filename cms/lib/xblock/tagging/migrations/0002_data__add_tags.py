# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import migrations

_init_data = [
    {
        'name': 'difficulty',
        'title': 'Difficulty',
        'values': ['Easy', 'Medium', 'Hard'],
    },
    {
        'name': 'learning_outcome',
        'title': 'Learning outcome',
        'values': ['Learned nothing', 'Learned a few things', 'Learned everything']
    }
]


def tags_init_forwards(apps, schema_editor):
    """Add the tag categories and available values."""
    tag_categories_model = apps.get_model("tagging", "TagCategories")
    tag_available_values_model = apps.get_model("tagging", "TagAvailableValues")
    for tag in _init_data:
        category = tag_categories_model.objects.create(name=tag['name'], title=tag['title'])
        for val in tag['values']:
            tag_available_values_model.objects.create(category=category, value=val)


def tags_init_backwards(apps, schema_editor):
    """Remove the tag categories and available values."""
    tag_available_values_model = apps.get_model("tagging", "TagAvailableValues")
    tag_categories_model = apps.get_model("tagging", "TagCategories")
    tag_available_values_model.objects.all().delete()
    tag_categories_model.objects.all().delete()


class Migration(migrations.Migration):

    dependencies = [
        ('tagging', '0001_initial'),
    ]

    operations = [
        migrations.RunPython(tags_init_forwards, tags_init_backwards),
    ]
