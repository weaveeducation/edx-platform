from django.contrib import admin
from .models import TurnitinApiKey


class TurnitinApiKeyForm(admin.ModelAdmin):
    list_display = ('id', 'org')


admin.site.register(TurnitinApiKey, TurnitinApiKeyForm)
