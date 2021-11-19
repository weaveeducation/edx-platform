from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect
from .api_client import BadgrApi
from .models import Assertion
from .service import issue_badge_assertion
from lms.djangoapps.courseware.module_render import get_module_by_usage_id
from opaque_keys.edx.keys import CourseKey, UsageKey
from opaque_keys import InvalidKeyError
from django.http import Http404, JsonResponse
from django.views.decorators.http import require_POST
from xmodule.modulestore.django import modulestore


@require_POST
@login_required
def issue_badge(request, course_id, usage_id):
    try:
        course_key = CourseKey.from_string(course_id)
    except InvalidKeyError:
        raise Http404

    with modulestore().bulk_operations(course_key):
        try:
            usage_key = UsageKey.from_string(usage_id)
        except InvalidKeyError:
            raise Http404

        instance, tracking_context = get_module_by_usage_id(
            request, course_id, str(usage_key)
        )

        result, badge_data, error = issue_badge_assertion(request.user, course_key, instance)
        return JsonResponse({
            'result': result,
            'data': badge_data,
            'error': error
        })


@login_required
def open_badge(request, assertion_id):
    assertion = Assertion.objects.filter(user=request.user, external_id=assertion_id).first()
    if assertion:
        api_client = BadgrApi()
        badge_data = api_client.get_assertion(assertion_id)
        return redirect(badge_data['openBadgeId'])
    else:
        raise Http404
