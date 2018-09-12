import json

from collections import OrderedDict
from courseware.courses import get_course_by_id
from django.db import transaction
from django.http import Http404
from django.shortcuts import redirect
from django.core.urlresolvers import resolve, reverse, NoReverseMatch
from django.views.generic.base import View
from django.contrib.auth.decorators import login_required
from django.utils.http import urlunquote
from django.utils.decorators import method_decorator
from credo_modules.models import CredoModulesUserProfile
from credo_modules.utils import additional_profile_fields_hash
from util.json_request import JsonResponse

from edxmako.shortcuts import render_to_response
from opaque_keys.edx.keys import CourseKey


class StudentProfileField(object):

    alias = ""
    required = False
    title = ""
    default = ""
    options = []
    order = None

    def __init__(self, alias="", required=False, title="", default="", options=None, order=None):
        self.alias = alias
        self.required = required
        self.title = title
        self.default = default
        self.options = options
        self.order = order

    @classmethod
    def init_from_course(cls, course, default_fields=None):
        res_unsorted = OrderedDict()
        for k, v in course.credo_additional_profile_fields.iteritems():
            order = None
            try:
                order = int(v['order']) if 'order' in v else None
            except ValueError:
                pass

            kwargs = {
                'alias': k,
                'required': v['required'] if 'required' in v and v['required'] else False,
                'title': v['title'] if 'title' in v and v['title'] else k,
                'default': default_fields[k] if default_fields and (k in default_fields) else v['default'],
                'options': v['options'] if 'options' in v and v['options'] else None,
                'order': order
            }
            res_unsorted[k] = StudentProfileField(**kwargs)
        return OrderedDict(sorted(res_unsorted.items(), key=lambda t: t[1].order if t[1].order is not None else t[0]))


def show_student_profile_form(request, course, simple_layout=False, redirect_to=None):
    course_key = course.id

    profiles = CredoModulesUserProfile.objects.filter(user=request.user, course_id=course_key)
    if len(profiles) > 0:
        profile = profiles[0]
        profile_fields = json.loads(profile.meta)
    else:
        profile_fields = {}

    fields = StudentProfileField.init_from_course(course, profile_fields)
    context = {
        'fields': fields.values(),
        'redirect_url': redirect_to if redirect_to else '',
        'course_id': unicode(course.id),
    }
    if simple_layout:
        context.update({
            'disable_accordion': True,
            'allow_iframing': True,
            'disable_header': True,
            'disable_footer': True,
            'disable_window_wrap': True,
            'disable_preview_menu': True,
        })

    return render_to_response("credo_additional_profile.html", context)


class StudentProfileView(View):

    @method_decorator(login_required)
    @method_decorator(transaction.atomic)
    def get(self, request, course_id):
        redirect_to = request.GET.get('next', None)
        course_key = CourseKey.from_string(course_id)
        course = get_course_by_id(course_key)
        simple_layout = False
        views_with_simple_layout = ('render_xblock_course', 'lti_launch')

        if not course.credo_additional_profile_fields:
            if not redirect_to:
                try:
                    redirect_to = reverse('dashboard')
                except NoReverseMatch:
                    redirect_to = reverse('home')
            else:
                redirect_to = urlunquote(redirect_to)
            return redirect(redirect_to)

        if redirect_to:
            try:
                redirect_url_info = resolve(redirect_to)
                if redirect_url_info.view_name in views_with_simple_layout:
                    simple_layout = True
            except Http404:
                pass

        return show_student_profile_form(request, course, simple_layout=simple_layout, redirect_to=redirect_to)

    @method_decorator(login_required)
    @method_decorator(transaction.atomic)
    def post(self, request, course_id):
        course_key = CourseKey.from_string(course_id)
        course = get_course_by_id(course_key)

        if not course.credo_additional_profile_fields:
            return JsonResponse({}, status=404)
        else:
            data = request.POST.copy()

            to_save_fields = {}
            errors = {}
            form_fields = StudentProfileField.init_from_course(course)

            for field_alias, field in form_fields.iteritems():
                passed_field = data.get(field_alias, '')
                if not passed_field and field.required:
                    errors[field_alias] = ''.join([field.title, " field is required"])
                else:
                    to_save_fields[field_alias] = passed_field

            if errors:
                return JsonResponse(errors, status=400)
            else:
                to_save_fields_json = json.dumps(to_save_fields, sort_keys=True)
                fields_version = additional_profile_fields_hash(course.credo_additional_profile_fields)
                profiles = CredoModulesUserProfile.objects.filter(user=request.user, course_id=course_key)

                if len(profiles) > 0:
                    profile = profiles[0]
                    profile.meta = to_save_fields_json
                    profile.fields_version = fields_version
                    profile.save()
                else:
                    profile = CredoModulesUserProfile(user=request.user, course_id=course_key,
                                                      meta=to_save_fields_json, fields_version=fields_version)
                    profile.save()
                return JsonResponse({"success": True})
