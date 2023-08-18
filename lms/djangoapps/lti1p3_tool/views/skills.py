from django.db import transaction
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.clickjacking import xframe_options_exempt
from django.views.decorators.http import require_POST

from common.djangoapps.util.views import add_p3p_header
from .launch import _launch
from .utils import COURSE_PROGRESS_PAGE, MY_SKILLS_PAGE
try:
    from pylti1p3.contrib.django import DjangoOIDCLogin, DjangoMessageLaunch, DjangoCacheDataStorage
    from pylti1p3.contrib.django.session import DjangoSessionService
    from pylti1p3.contrib.django.request import DjangoRequest
    from pylti1p3.deep_link_resource import DeepLinkResource
    from pylti1p3.exception import OIDCException, LtiException
    from pylti1p3.lineitem import LineItem
except ImportError:
    pass


@csrf_exempt
@add_p3p_header
@xframe_options_exempt
@require_POST
def progress(request, course_id):
    with transaction.atomic():
        return _launch(request, course_id=course_id, page=COURSE_PROGRESS_PAGE)


@csrf_exempt
@add_p3p_header
@xframe_options_exempt
@require_POST
def myskills(request):
    with transaction.atomic():
        return _launch(request, page=MY_SKILLS_PAGE)

