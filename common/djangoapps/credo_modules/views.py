import json

from collections import OrderedDict
from courseware.courses import get_course_by_id
from django.conf import settings
from django.db import transaction
from django.http import Http404
from django.shortcuts import redirect
from django.core.urlresolvers import resolve, reverse, NoReverseMatch
from django.contrib.auth import login
from django.contrib.auth.models import User
from django.db.models import Q
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

    def __init__(self, alias="", required=False, title="", default="", options=None, allow_non_suggested=False,
                 order=None, info=False, hidden=False, minlength=None, maxlength=None,
                 minnumber=None, maxnumber=None, isnumber=None, isalnum=False):
        self.alias = alias
        self.required = required
        self.title = title
        self.default = str(default) if default is not None else None
        self.options = options
        self.allow_non_suggested = allow_non_suggested
        self.order = order
        self.info = info
        self.hidden = hidden
        self.minnumber = str(minnumber) if minnumber is not None else None
        self.maxnumber = str(maxnumber) if maxnumber is not None else None
        self.minlength = str(minlength) if minlength is not None else None
        self.maxlength = str(maxlength) if maxlength is not None else None
        self.isnumber = isnumber
        self.isalnum = isalnum

    @classmethod
    def init_from_course(cls, course, default_fields=None):
        res_unsorted = OrderedDict()
        for k, v in course.credo_additional_profile_fields.iteritems():
            order = None
            try:
                order = int(v['order']) if 'order' in v else None
            except ValueError:
                pass

            allow_non_suggested = None
            options = v['options'] if 'options' in v and v['options'] else None
            if options:
                allow_non_suggested = v['allow_non_suggested'] if 'allow_non_suggested' in v else None
                if allow_non_suggested:
                    options.append('Other')

            minlength = None
            maxlength = None
            minnumber = None
            maxnumber = None
            isnumber = None
            isalnum = False

            default_tmp = default_fields[k].encode('utf-8')\
                if default_fields and (k in default_fields) else v.get('default')
            if options:
                if not default_tmp or default_tmp in options:
                    default = default_tmp
                else:
                    default = 'Other'
            else:
                default = default_tmp

                validation = v.get('validation', {})
                minlength = validation.get('string', {}).get('min', None)
                maxlength = validation.get('string', {}).get('max', None)
                isalnum = validation.get('string', {}).get('alnum', False)
                minnumber = validation.get('number', {}).get('min', None)
                maxnumber = validation.get('number', {}).get('max', None)

                if minlength:
                    try:
                        minlength = int(minlength)
                    except ValueError:
                        minlength = None

                if maxlength:
                    try:
                        maxlength = int(maxlength)
                    except ValueError:
                        maxlength = None

                if minnumber:
                    try:
                        minnumber = int(minnumber)
                    except ValueError:
                        minnumber = None

                if maxnumber:
                    try:
                        maxnumber = int(maxnumber)
                    except ValueError:
                        maxnumber = None

                isalnum = True if isalnum else False

                isnumber = 'number' in validation
                if isnumber:
                    minlength = None
                    maxlength = None
                    isalnum = False
                    try:
                        default = int(default)
                    except ValueError:
                        default = None

                    if minnumber is not None and default is not None and default < minnumber:
                        default = None
                    elif maxnumber is not None and default is not None and default > maxnumber:
                        default = None

            kwargs = {
                'alias': k,
                'required': v['required'] if 'required' in v and v['required'] else False,
                'title': v['title'] if 'title' in v and v['title'] else k,
                'default': default,
                'options': options,
                'allow_non_suggested': allow_non_suggested,
                'order': order,
                'info': bool(v.get('info')),
                'hidden': False,
                'minlength': minlength,
                'maxlength': maxlength,
                'minnumber': minnumber,
                'maxnumber': maxnumber,
                'isnumber': isnumber,
                'isalnum': isalnum
            }
            res_unsorted[k] = StudentProfileField(**kwargs)

            if options and allow_non_suggested:
                kk = k + '__custom'
                kwargs = {
                    'alias': kk,
                    'required': False,
                    'title': 'Please describe',
                    'default': default_tmp if default == 'Other' and default_tmp else '',
                    'options': None,
                    'allow_non_suggested': None,
                    'order': order + 0.5,
                    'info': False,
                    'hidden': False if default == 'Other' and default_tmp else True,
                    'minlength': None,
                    'maxlength': None,
                    'minnumber': None,
                    'maxnumber': None,
                    'isnumber': None,
                    'isalnum': None
                }
                res_unsorted[kk] = StudentProfileField(**kwargs)
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

    def _is_valid(self, value, field):
        if field.isnumber:
            try:
                value = int(value)
            except ValueError:
                return False, ''.join([field.title, " field must be digit"])
            if field.minnumber is not None and value < int(field.minnumber):
                return False, ''.join([field.title, " field must be greater or equal than ", str(field.minnumber)])
            if field.maxnumber is not None and value > int(field.maxnumber):
                return False, ''.join([field.title, " field must be less or equal than ", str(field.maxnumber)])
        else:
            if field.minlength is not None and len(value) < int(field.minlength):
                return False, ''.join([field.title, " field must contains at least %s characters"
                                       % str(field.minlength)])
            if field.maxlength is not None and len(value) > int(field.maxlength):
                return False, ''.join([field.title, " field must contains at most %s characters"
                                       % str(field.maxlength)])
            if field.isalnum and not value.isalnum():
                return False, ''.join([field.title, " field must contains only letters and digits"])
        return True, None

    @method_decorator(login_required)
    @method_decorator(transaction.atomic)
    def post(self, request, course_id):
        course_key = CourseKey.from_string(course_id)
        course = get_course_by_id(course_key)

        if not course.credo_additional_profile_fields:
            return JsonResponse({}, status=404)
        else:
            data = request.POST.copy()
            fields_version = additional_profile_fields_hash(course.credo_additional_profile_fields)

            to_save_fields = {}
            errors = {}
            form_fields = StudentProfileField.init_from_course(course)

            fields_to_replace = []

            for field_alias, field in form_fields.iteritems():
                passed_field = data.get(field_alias, '')
                if not passed_field and field.required:
                    errors[field_alias] = ''.join([field.title, " field is required"])
                else:
                    is_valid, err_msg = self._is_valid(data.get(field_alias, ''), field)
                    if is_valid:
                        to_save_fields[field_alias] = passed_field
                        if field_alias.endswith('__custom'):
                            fields_to_replace.append(field_alias)
                    else:
                        errors[field_alias] = err_msg

            for field_to_replace in fields_to_replace:
                original_field_name = field_to_replace[0:-len('__custom')]
                if data[original_field_name] == 'Other':
                    to_save_fields[original_field_name] = data[field_to_replace]
                else:
                    to_save_fields[original_field_name] = data[original_field_name]
                to_save_fields.pop(field_to_replace)

            if errors:
                return JsonResponse(errors, status=400)
            else:
                to_save_fields_json = json.dumps(to_save_fields, sort_keys=True)
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


@login_required
def login_as_user(request):
    if not request.user.is_superuser:
        return JsonResponse({
            "success": False,
            "errorMessage": "Invalid request"
        })

    word = request.GET.get('user', '')
    word = word.strip()
    if not word:
        return JsonResponse({
            "success": False,
            "errorMessage": "Invalid request"
        })

    edx_user = None
    if word.isdigit():
        try:
            edx_user = User.objects.get(id=int(word))
        except User.DoesNotExist:
            pass

    if not edx_user:
        try:
            edx_user = User.objects.get(Q(username=word) | Q(email=word))
        except User.DoesNotExist:
            return JsonResponse({
                "success": False,
                "userid": None,
                "errorMessage": "User not found"
            })

    login(request, edx_user, backend=settings.AUTHENTICATION_BACKENDS[0])
    return redirect(reverse('dashboard'))
