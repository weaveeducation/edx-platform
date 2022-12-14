import json
from django.contrib.auth import get_user_model
from django.core.validators import URLValidator
from django.core.exceptions import ValidationError
from django.utils.translation import ugettext_lazy as _
from django.db import models
from opaque_keys.edx.django.models import CourseKeyField, UsageKeyField
from jsonfield.fields import JSONField
from Cryptodome.PublicKey import RSA
try:
    from pylti1p3.registration import Registration
except ImportError:
    pass


User = get_user_model()


class LtiToolKey(models.Model):
    name = models.CharField(max_length=255, null=False, blank=False, unique=True, help_text=_("Key name"))
    private_key = models.TextField(null=False, blank=False, help_text=_("Tool's generated Private key. "
                                                                        "Keep this value in secret"))
    public_key = models.TextField(null=False, blank=False, help_text=_("Tool's generated Public key. Provide this"
                                                                       " value to Platforms"))
    public_jwk = JSONField(null=False, blank=False, help_text=_("Tool's generated Public key (from the field above) "
                                                                "presented as JWK. Provide this value to Platforms"))

    def _generate(self):
        key = RSA.generate(4096)
        self.private_key = key.exportKey().decode("utf-8")
        self.public_key = key.publickey().exportKey().decode("utf-8")
        self.public_jwk = Registration.get_jwk(self.public_key)

    def save(self, *args, **kwargs):
        if not self.id:
            self._generate()
        super().save(*args, **kwargs)

    def regenerate(self):
        if self.id:
            self._generate()
        self.save()

    def __str__(self):
        return '<LtiToolKey id=%d, name=%s>' % (self.id, self.name)


class LtiTool(models.Model):
    title = models.CharField(max_length=255, default=_("Unknown"))
    is_active = models.BooleanField(default=True)
    issuer = models.CharField(max_length=255,
                              help_text=_("This will usually look something like 'http://example.com'. "
                                          "Value provided by LTI 1.3 Platform"))
    client_id = models.CharField(max_length=255, null=False, blank=False,
                                 help_text=_("Value provided by LTI 1.3 Platform"))
    use_by_default = models.BooleanField(default=False, help_text=_("This iss config will be used in case "
                                                                    "if client-id was not passed"))
    auth_login_url = models.CharField(max_length=1024, null=False, blank=False,
                                      help_text=_("The platform's OIDC login endpoint. "
                                                  "Value provided by LTI 1.3 Platform"),
                                      validators=[URLValidator()])
    auth_token_url = models.CharField(max_length=1024, null=False, blank=False,
                                      help_text=_("The platform's service authorization "
                                                  "endpoint. Value provided by "
                                                  "LTI 1.3 Platform"),
                                      validators=[URLValidator()])
    auth_audience = models.CharField(max_length=1024, null=True, blank=True,
                                     help_text=_("The platform's OAuth2 Audience (aud). "
                                                 "Usually could be skipped"))
    key_set_url = models.CharField(max_length=1024, null=True, blank=True,
                                   help_text=_("The platform's JWKS endpoint. "
                                               "Value provided by LTI 1.3 Platform"),
                                   validators=[URLValidator()])
    key_set = JSONField(null=True, blank=True, help_text=_("In case if platform's JWKS endpoint somehow "
                                                           "unavailable you may paste JWKS here. "
                                                           "Value provided by LTI 1.3 Platform"))
    tool_key = models.ForeignKey(LtiToolKey, on_delete=models.CASCADE)
    deployment_ids = JSONField(null=False, blank=False, default=[],
                               help_text=_("List of Deployment IDs. "
                                           "Example: [\"test-id-1\", \"test-id-2\", ...] "
                                           "Each value is provided by LTI 1.3 Platform. "))
    force_create_lineitem = models.BooleanField(default=False,
                                                help_text=_("Forcibly post grades if Platform's assignments grades "
                                                            "service is available but lineitem wasn't passed during "
                                                            "LTI communication"))
    allow_to_add_instructors_via_lti = models.BooleanField(blank=True, null=True,
                                                           help_text="Automatically adds "
                                                                     "instructor role to the user "
                                                                     "who came through the LTI if "
                                                                     "some of these parameters: "
                                                                     "'Administrator', 'Instructor', "
                                                                     "'Staff' was passed. Choose 'Yes' "
                                                                     "to enable this feature. ")
    use_names_and_role_provisioning_service = models.BooleanField(
                                                  default=False,
                                                  help_text=_("Use LTI 1.3 advantage names and role provisioning "
                                                              "service to get first name/last name/email about "
                                                              "student (not recommended for usage because "
                                                              "of performance reasons, may be needed for LTI 1.3 "
                                                              "certification)"))

    automatically_enroll_users = models.BooleanField(default=False,
                                                     help_text=_("Automatically enroll users using information "
                                                                 "from the Names and Role Provisioning service."))
    automatically_unenroll_users = models.BooleanField(default=False,
                                                       help_text=_("Automatically unenroll users using information "
                                                                   "from the Names and Role Provisioning service."))
    deep_linking_short_launch_urls = models.BooleanField(default=False,
                                                         help_text=_("Use short launch URLs as the result of "
                                                                     "deep links embedding. Pass block_id in "
                                                                     "LTI custom params"))

    def clean(self):
        if not self.key_set_url and not self.key_set:
            raise ValidationError({'key_set_url': _('Even one of "key_set_url" or "key_set" should be set')})
        if not isinstance(self.deployment_ids, list):
            raise ValidationError({'deployment_ids': _('Should be a list. Example: ["test-id-1", "test-id-2", ...]')})

    def to_dict(self):
        data = {
            "issuer": self.issuer,
            "client_id": self.client_id,
            "auth_login_url": self.auth_login_url,
            "auth_token_url": self.auth_token_url,
            "auth_audience": self.auth_audience,
            "key_set_url": self.key_set_url,
            "key_set": self.key_set,
            "deployment_ids": self.deployment_ids
        }
        return data

    def __str__(self):
        return '<LtiTool id=%d, title=%s>' % (self.id, self.title)

    class Meta:
        unique_together = ('issuer', 'client_id')


class GradedAssignment(models.Model):
    user = models.ForeignKey(User, related_name="lti1p3_graded_assignments", on_delete=models.CASCADE)
    course_key = CourseKeyField(max_length=255, db_index=True)
    usage_key = UsageKeyField(max_length=255)
    lti_tool = models.ForeignKey(LtiTool, on_delete=models.CASCADE)
    lti_jwt_endpoint = JSONField(null=False, blank=False)
    lti_jwt_sub = models.CharField(max_length=255)
    lti_lineitem = models.CharField(max_length=255, null=False, blank=False, db_index=True)
    lti_lineitem_tag = models.CharField(max_length=255, null=True)
    created_by_tool = models.BooleanField(default=False)
    version_number = models.IntegerField(default=0)
    disabled = models.BooleanField(default=False)

    class Meta:
        index_together = (('lti_jwt_sub', 'lti_lineitem_tag'),)
        unique_together = (('lti_lineitem', 'lti_jwt_sub'),)


class LtiUser(models.Model):
    lti_tool = models.ForeignKey(LtiTool, on_delete=models.CASCADE)
    lti_jwt_sub = models.CharField(max_length=255)
    edx_user = models.OneToOneField(User, related_name="lti1p3_users", on_delete=models.CASCADE)

    class Meta:
        unique_together = (('lti_tool', 'lti_jwt_sub'),)

    def __str__(self):
        return f"<LtiUser lti_jwt_sub={self.lti_jwt_sub} edx_user={self.edx_user.email if self.edx_user else None}>"


class LtiExternalCourse(models.Model):
    external_course_id = models.CharField(max_length=255, db_index=True)
    edx_course_id = models.CharField(max_length=255, db_index=True)
    lti_tool = models.ForeignKey(LtiTool, on_delete=models.CASCADE)
    context_memberships_url = models.TextField(null=True, blank=True)
    users_last_sync_date = models.DateTimeField(null=True, editable=False)

    class Meta:
        unique_together = (('external_course_id', 'edx_course_id'),)

    def __str__(self):
        return f"<LtiExternalCourse external_course_id={self.external_course_id} edx_course_id={self.edx_course_id}>"


class LtiUserEnrollment(models.Model):
    lti_user = models.ForeignKey(LtiUser, on_delete=models.CASCADE)
    external_course = models.ForeignKey(LtiExternalCourse, on_delete=models.CASCADE)
    properties = models.TextField(null=True, blank=True)
    created = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = (('lti_user', 'external_course'),)

    def set_properties(self, value):
        self.properties = json.dumps(value)

    def get_properties(self):
        if self.properties:
            return json.loads(self.properties)
        return {}
