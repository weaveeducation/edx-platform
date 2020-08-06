import hmac
import hashlib
import logging
import datetime
import json
import platform
import time
from django.conf import settings


log_json = logging.getLogger("credo_json")


def generate_hmac256_signature(message):
    signature = hmac.new(
        str(settings.TURNITIN_SIGNING_SECRET),
        msg=message,
        digestmod=hashlib.sha256
    ).hexdigest()
    return signature


def log_action(name, title, **kwargs):
    hostname = platform.node().split(".")[0]
    data = {
        'action': name,
        'message': title,
        'type': 'turnitin',
        'hostname': hostname,
        'datetime': str(datetime.datetime.now()),
        'timestamp': time.time()
    }
    if kwargs:
        data.update(kwargs)
    log_json.info(json.dumps(data))
