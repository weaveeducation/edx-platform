import datetime
import pytz

from django.contrib.auth import get_user_model
from django.db import models
from jsonfield.fields import JSONField


User = get_user_model()


class Configuration(models.Model):
    updated_at = models.DateTimeField(auto_now=True)
    data = JSONField(default=dict, blank=True, null=True)
    name = models.CharField(max_length=255, verbose_name='Title')
    is_active = models.BooleanField(default=False, verbose_name='Activity')
    is_default = models.BooleanField(default=False, verbose_name='Is Default')

    DATE_TEMPLATE = '%Y-%m-%d %H:%M:%S.%f'

    @classmethod
    def get_config(cls):
        try:
            item = cls.objects.get()
            return item
        except Configuration.DoesNotExist:
            return Configuration(data={})

    def _get_value(self, key, default=None):
        if key in self.data:
            return self.data[key]
        return default

    def get_access_token(self):
        return self._get_value('access_token')

    def get_refresh_token(self):
        return self._get_value('refresh_token')

    def get_min_percentage(self):
        return self._get_value('min_percentage')

    def get_issuer_entity_id(self):
        return self._get_value('issuer_entity_id')

    def get_token_type(self):
        return self._get_value('token_type')

    def get_account_login(self):
        return self._get_value('account_login')

    def get_account_password(self):
        return self._get_value('account_password')

    def get_badgr_login_page(self):
        return self._get_value('badgr_login_page')

    def get_expires_dt(self):
        expires_dt_str = self._get_value('expires_dt')
        if expires_dt_str:
            return datetime.datetime.strptime(expires_dt_str, '%Y-%m-%d %H:%M:%S').replace(tzinfo=pytz.utc)
        return None

    def update_param(self, key, value):
        self.data[key] = value
        self.save()


class Issuer(models.Model):
    title = models.CharField(max_length=255, verbose_name='Title')
    external_id = models.CharField(max_length=255, unique=True, verbose_name='External Entity ID')
    is_active = models.BooleanField(default=False, verbose_name='Activity')
    description = models.TextField(default=None, null=True, verbose_name='Description')
    url = models.CharField(max_length=255, verbose_name='External URL')
    image_url = models.CharField(max_length=255, verbose_name='Image URL')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return '<Issuer id=%s, title=%s, external_id=%s>' % (self.id, self.title, self.external_id)


class Badge(models.Model):
    title = models.CharField(max_length=255, verbose_name='Title')
    external_id = models.CharField(max_length=255, unique=True, verbose_name='External Entity ID')
    issuer = models.ForeignKey(Issuer, on_delete=models.CASCADE)
    is_active = models.BooleanField(default=False, verbose_name='Activity')
    description = models.TextField(default=None, null=True, verbose_name='Description')
    criteria_narrative = models.TextField(default=None, null=True, verbose_name='Criteria Narrative')
    url = models.CharField(max_length=255, verbose_name='External URL')
    image_url = models.CharField(max_length=255, verbose_name='Image URL')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return '<Badge id=%s, title=%s, external_id=%s>' % (self.id, self.title, self.external_id)

    @classmethod
    def get_all(cls, issuer_external_id):
        issuer = Issuer.objects.filter(is_active=True, external_id=issuer_external_id).first()
        if issuer:
            data = cls.objects.filter(issuer=issuer, is_active=True).order_by('title')
            return [{'id': item.external_id, 'title': item.title} for item in data]
        return []


class Assertion(models.Model):
    external_id = models.CharField(max_length=255, verbose_name='External id')
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    badge = models.ForeignKey(Badge, on_delete=models.CASCADE)
    url = models.CharField(max_length=255, verbose_name='External URL')
    image_url = models.CharField(max_length=255, verbose_name='Image URL')
    course_id = models.CharField(max_length=255, null=False, db_index=True)
    block_id = models.CharField(max_length=255, null=False, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
