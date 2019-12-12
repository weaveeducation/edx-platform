import json

from django.contrib.auth.models import User
from django.core.validators import RegexValidator
from django.db import models
from django.db.models.signals import post_save, pre_delete
from django.dispatch import receiver
from credo_modules.models import Organization
from .api import TurnitinApi
from .utils import log_action


class TurnitinSubmissionStatus(object):
    NOT_SET = '-'
    CREATED = 'CREATED'
    PROCESSING = 'PROCESSING'
    COMPLETE = 'COMPLETE'
    ERROR = 'ERROR'


class TurnitinReportStatus(object):
    NOT_SET = ''
    IN_PROGRESS = 'PROCESSING'
    COMPLETE = 'COMPLETE'


class TurnitinApiKey(models.Model):
    is_active = models.BooleanField(default=False)
    org = models.OneToOneField(Organization)
    key = models.CharField(max_length=255, verbose_name='Authorization token')
    url_part = models.CharField(max_length=30, verbose_name='XXX url part in the "xxx.turnitin.com" hostname',
                                validators=[RegexValidator(r'^[a-z]+$', 'Only a-z characters are allowed')])
    use_sandbox = models.BooleanField(default=False, verbose_name='Use xxx.tii-sandbox.com instead of xxx.turnitin.com')
    webhook_id = models.CharField(max_length=255, verbose_name='Webhook ID', null=True, blank=True)

    class Meta(object):
        db_table = "turnitin_api_key"


class TurnitinSubmission(models.Model):
    api_key = models.ForeignKey(TurnitinApiKey)
    block_id = models.CharField(max_length=255, db_index=True)
    file_name = models.CharField(max_length=255, null=True, blank=True)
    ora_submission_id = models.CharField(max_length=255, db_index=True)
    turnitin_submission_id = models.CharField(max_length=255, null=True, blank=True, db_index=True)
    user = models.ForeignKey(User)
    status = models.CharField(max_length=30)
    data = models.TextField(null=True, blank=True)
    report_status = models.CharField(max_length=30, default=TurnitinReportStatus.NOT_SET)
    creation_time = models.DateTimeField(null=True, blank=True, auto_now_add=True)
    update_time = models.DateTimeField(null=True, blank=True, auto_now=True)

    def get_data(self):
        if self.data:
            return json.loads(self.data)
        return {}

    def set_data(self, data):
        self.data = json.dumps(data)

    def update_data(self, new_data):
        current_data = self.get_data()
        current_data.update(new_data)
        self.set_data(current_data)

    class Meta(object):
        db_table = "turnitin_submission"


class TurnitinUser(models.Model):
    user = models.ForeignKey(User)
    user_id_hash = models.CharField(max_length=255, db_index=True)

    class Meta(object):
        db_table = "turnitin_user"


@receiver(post_save, sender=TurnitinApiKey)
def create_turnitin_webhook(sender, instance, created, **kwargs):
    if created:
        api = TurnitinApi(instance)
        status_code, webhook_id, webhook_host = api.create_webhook()
        if webhook_id:
            log_action('turnitin_signals', 'Webhook created: ' + webhook_host,
                       webhook_id=webhook_id, status_code=status_code)
            instance.webhook_id = webhook_id
            instance.save()
        else:
            log_action('turnitin_signals', "Can't create turnitin webhook: " + webhook_host, status_code=status_code)
            raise Exception("Can't create turnitin webhook")


@receiver(pre_delete, sender=TurnitinApiKey)
def delete_turnitin_webhook(sender, instance, **kwargs):
    api = TurnitinApi(instance)
    if instance.webhook_id:
        status_code, res = api.remove_webhook(instance.webhook_id)
        if res:
            log_action('turnitin_signals', 'Webhook removed', webhook_id=instance.webhook_id)
        else:
            log_action('turnitin_signals', "Can't remove turnitin webhook", webhook_id=instance.webhook_id,
                       status_code=status_code)
            raise Exception("Can't remove turnitin webhook")
