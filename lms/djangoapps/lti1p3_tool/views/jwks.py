from django.http import HttpResponseBadRequest, JsonResponse
from django.views.decorators.csrf import csrf_exempt

from ..models import LtiToolKey

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
def get_jwks(request, key_id):
    try:
        key = LtiToolKey.objects.get(id=key_id)
        return JsonResponse({'keys': [key.public_jwk]})
    except LtiToolKey.DoesNotExist:
        return HttpResponseBadRequest()
