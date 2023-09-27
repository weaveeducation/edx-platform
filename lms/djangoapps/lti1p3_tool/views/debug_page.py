from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.clickjacking import xframe_options_exempt
from common.djangoapps.util.views import add_p3p_header
from .launch import _launch
from .utils import DEBUG_PAGE

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
def debug_page(request):
    return _launch(request, page=DEBUG_PAGE)
