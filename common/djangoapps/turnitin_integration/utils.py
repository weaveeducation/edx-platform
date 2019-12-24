import hmac
import hashlib
import logging

from django.conf import settings


log = logging.getLogger("turnitin")


def generate_hmac256_signature(message):
    signature = hmac.new(
        str(settings.TURNITIN_SIGNING_SECRET),
        msg=message,
        digestmod=hashlib.sha256
    ).hexdigest()
    return signature


def log_action(name, title, **kwargs):
    msg = '[initiator=' + name + ']'
    for k, v in kwargs.items():
        msg += '[' + str(k) + '=' + str(v) + ']'
    msg += ' ' + title
    log.info(msg)


