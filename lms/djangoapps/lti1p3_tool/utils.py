import hashlib
from django.conf import settings


def get_lineitem_tag(usage_key):
    return 'edx-block-' + hashlib.md5(settings.SECRET_KEY + str(usage_key)).hexdigest()
