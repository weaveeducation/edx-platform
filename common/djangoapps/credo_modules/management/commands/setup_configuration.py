import datetime
import logging
import uuid

from django_celery_beat.models import CrontabSchedule, PeriodicTask
from django.db import connection
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.contrib.sites.models import Site
from oauth2_provider.models import Application
from waffle.models import Flag, Switch

from lms.djangoapps.lms_xblock.models import XBlockAsidesConfig
from lms.djangoapps.certificates.models import CertificateGenerationConfiguration
from common.djangoapps.credo_modules.models import Feature, FeatureStatus, LoginRedirectAllowedHost, TrackingLogConfig
from openedx.core.djangoapps.theming.models import SiteTheme
from openedx.core.djangoapps.site_configuration.models import SiteConfiguration
from openedx.core.djangoapps.oauth_dispatch.models import ApplicationAccess

logger = logging.getLogger(__name__)
User = get_user_model()

PROD_ENV = "prod"
TEST_ENV = "test"
NEXT_ENV = "next"
ADMIN_EMAIL = "dmitry.viskov@epicsoftwaredev.com"


class Command(BaseCommand):
    """
    Examples:
        python manage.py lms setup_configuration --env=prod --islocal --settings devstack
        python manage.py lms setup_configuration --env=next --settings devstack
        python manage.py lms setup_configuration --env=test --settings devstack
    """

    help = "Setup sites configuration"
    allowed_envs = (PROD_ENV, TEST_ENV, NEXT_ENV)

    def add_arguments(self, parser):
        parser.add_argument("--env", required=True, action="store", type=str)
        parser.add_argument("--islocal", action="store_true", default=False)

    def handle(self, env, islocal, *args, **options):
        HTTP_PROTOCOL = "http" if islocal else "https"
        NW_HOST = f"nimblywise.{'test' if islocal else 'com'}"
        WEAVE_HOST = f"weaveeducation.{'test' if islocal else 'com'}"
        CREDO_HOST = f"credocourseware.{'test' if islocal else 'com'}"

        if env not in self.allowed_envs:
            raise Exception(f"Invalid env: {env}")

        env_part = "" if env == PROD_ENV else env + "."

        nw_base_domain = f"{env_part}{NW_HOST}"
        nw_lms_domain = f"lms.{env_part}{NW_HOST}"
        nw_cms_domain = f"cms.{env_part}{NW_HOST}"
        nw_preview_domain = f"preview.{env_part}{NW_HOST}"
        nw_constructor_domain = f"constructor.{env_part}{NW_HOST}"
        nw_insights_domain = f"insights.{env_part}{NW_HOST}"
        nw_skills_domain = f"skills.{env_part}{NW_HOST}"
        nw_learning_domain = f"learning.{env_part}{NW_HOST}"

        weave_base_domain = f"{env_part}{WEAVE_HOST}"
        weave_lms_domain = f"lms.{env_part}{WEAVE_HOST}"
        weave_cms_domain = f"cms.{env_part}{WEAVE_HOST}"
        weave_preview_domain = f"preview.{env_part}{WEAVE_HOST}"
        weave_constructor_domain = f"constructor.{env_part}{WEAVE_HOST}"
        weave_insights_domain = f"insights.{env_part}{WEAVE_HOST}"
        weave_skills_domain = f"skills.{env_part}{WEAVE_HOST}"
        weave_learning_domain = f"learning.{env_part}{WEAVE_HOST}"

        credo_base_domain = f"{env_part}{CREDO_HOST}"
        credo_lms_domain = f"{env_part}{CREDO_HOST}"
        credo_frame_lms_domain = f"frame.{env_part}{CREDO_HOST}"
        credo_cms_domain = f"studio.{env_part}{CREDO_HOST}"
        credo_preview_domain = f"preview.{env_part}{CREDO_HOST}"
        credo_constructor_domain = f"constructor.{env_part}{CREDO_HOST}"
        credo_insights_domain = f"insights.{env_part}{CREDO_HOST}"
        if env == PROD_ENV and not islocal:
            credo_insights_domain = "insights.credoeducation.com"
        credo_skills_domain = f"skills.{env_part}{CREDO_HOST}"
        credo_learning_domain = f"learning.{env_part}{CREDO_HOST}"
        credo_frame_learning_domain = f"learning-frame.{env_part}{CREDO_HOST}"

        print('---------------> Create/Update Sites')

        nw_lms_site, _ = Site.objects.get_or_create(domain=nw_lms_domain, defaults={"name": "NimblyWise LMS"})
        nw_cms_site, _ = Site.objects.get_or_create(domain=nw_cms_domain, defaults={"name": "NimblyWise CMS"})
        nw_preview_site, _ = Site.objects.get_or_create(domain=nw_preview_domain, defaults={"name": "NimblyWise Preview"})

        weave_lms_site, _ = Site.objects.get_or_create(domain=weave_lms_domain, defaults={"name": "Weave LMS"})
        weave_cms_site, _ = Site.objects.get_or_create(domain=weave_cms_domain, defaults={"name": "Weave CMS"})
        weave_preview_site, _ = Site.objects.get_or_create(domain=weave_preview_domain, defaults={"name": "Weave Preview"})

        credo_lms_site, _ = Site.objects.get_or_create(domain=credo_lms_domain, defaults={"name": "Credo LMS"})
        credo_frame_site, _ = Site.objects.get_or_create(domain=credo_frame_lms_domain, defaults={"name": "Credo Frame"})
        credo_cms_site, _ = Site.objects.get_or_create(domain=credo_cms_domain, defaults={"name": "Credo CMS"})
        credo_preview_site, _ = Site.objects.get_or_create(domain=credo_preview_domain, defaults={"name": "Credo Preview"})

        print('---------------> Create/Update Site Themes')

        th, _ = SiteTheme.objects.get_or_create(site=nw_lms_site)
        th.theme_dir_name = "weave-edx-theme"
        th.save()

        th, _ = SiteTheme.objects.get_or_create(site=nw_preview_site)
        th.theme_dir_name = "weave-edx-theme"
        th.save()

        th, _ = SiteTheme.objects.get_or_create(site=weave_lms_site)
        th.theme_dir_name = "weave-edx-theme"
        th.save()

        th, _ = SiteTheme.objects.get_or_create(site=weave_preview_site)
        th.theme_dir_name = "weave-edx-theme"
        th.save()

        th, _ = SiteTheme.objects.get_or_create(site=credo_lms_site)
        th.theme_dir_name = "credo-theme"
        th.save()

        th, _ = SiteTheme.objects.get_or_create(site=credo_frame_site)
        th.theme_dir_name = "credo-theme"
        th.save()

        th, _ = SiteTheme.objects.get_or_create(site=credo_preview_site)
        th.theme_dir_name = "credo-theme"
        th.save()

        print('---------------> Create/Update Site Configurations')

        cfg, _ = SiteConfiguration.objects.get_or_create(site=nw_lms_site)
        cfg.enabled = True
        cfg.site_values = {
            "BASE_COOKIE_DOMAIN": nw_base_domain,
            "CONSTRUCTOR_LINK": f"{HTTP_PROTOCOL}://{nw_constructor_domain}",
            "ENABLE_COMBINED_LOGIN_REGISTRATION": True,
            "platform_name": "Weave",
            "PLATFORM_NAME": "Weave",
            "site_domain": nw_lms_domain,
            "logo_image_url": "images/weave-logo.png",
            "LMS_BASE": nw_lms_domain,
            "CMS_BASE": nw_cms_domain,
            "LMS_ROOT_URL": f"{HTTP_PROTOCOL}://{nw_lms_domain}",
            "SITE_NAME": nw_lms_domain,
            "SESSION_COOKIE_DOMAIN": f".{nw_base_domain}",
            "HIDE_PROFILE": False,
            "TECH_SUPPORT_EMAIL": "support@nimblywise.com",
            "PREVIEW_LMS_BASE": nw_preview_domain,
            "INSIGHTS_LINK": f"{HTTP_PROTOCOL}://{nw_insights_domain}",
            "SHOW_NW_HELP": True,
            "email_error_support": "support@nimblywise.com",
            "email_from_address": "support@nimblywise.com",
            "ACTIVATION_EMAIL_FROM_ADDRESS": "support@nimblywise.com",
            "SKILLS_MFE_URL": f"{HTTP_PROTOCOL}://{nw_skills_domain}",
            "supervisor_generate_pdf": True,
            "urls": {
                "PRIVACY": "https://weaveeducation.com/privacy-policy/",
                "ABOUT": "https://weaveeducation.com"
            },
            "LEARNING_MICROFRONTEND_URL": f"{HTTP_PROTOCOL}://{nw_learning_domain}",
            "SOCIAL_AUTH_EDX_OAUTH2_URL_ROOT": f"{HTTP_PROTOCOL}://{nw_lms_domain}",
            "SOCIAL_AUTH_EDX_OAUTH2_PUBLIC_URL_ROOT": f"{HTTP_PROTOCOL}://{nw_lms_domain}"
        }
        cfg.save()

        cfg, _ = SiteConfiguration.objects.get_or_create(site=nw_cms_site)
        cfg.enabled = True
        cfg.site_values = {
            "BASE_COOKIE_DOMAIN": nw_base_domain,
            "ENABLE_COMBINED_LOGIN_REGISTRATION": True,
            "platform_name": "Weave",
            "PLATFORM_NAME": "Weave",
            "site_domain": nw_cms_domain,
            "CMS_BASE": nw_cms_domain,
            "LMS_BASE": nw_lms_domain,
            "LMS_ROOT_URL": f"{HTTP_PROTOCOL}://{nw_lms_domain}",
            "SITE_NAME": nw_cms_domain,
            "SESSION_COOKIE_DOMAIN": f".{nw_base_domain}",
            "TECH_SUPPORT_EMAIL": "support@nimblywise.com",
            "PREVIEW_LMS_BASE": nw_preview_domain,
            "INSIGHTS_LINK": f"{HTTP_PROTOCOL}://{nw_insights_domain}",
            "SHOW_NW_HELP": True,
            "email_error_support": "support@nimblywise.com",
            "email_from_address": "support@nimblywise.com",
            "studio_logo_image_url": f"{HTTP_PROTOCOL}://{weave_lms_domain}/static/weave-edx-theme/images/weave-logo-mini.png",
            "SKILLS_MFE_URL": f"{HTTP_PROTOCOL}://{nw_skills_domain}",
            "supervisor_generate_pdf": True,
            "LEARNING_MICROFRONTEND_URL": f"{HTTP_PROTOCOL}://{nw_learning_domain}",
            "SOCIAL_AUTH_EDX_OAUTH2_URL_ROOT": f"{HTTP_PROTOCOL}://{nw_lms_domain}",
            "SOCIAL_AUTH_EDX_OAUTH2_PUBLIC_URL_ROOT": f"{HTTP_PROTOCOL}://{nw_lms_domain}"
        }
        cfg.save()

        cfg, _ = SiteConfiguration.objects.get_or_create(site=nw_preview_site)
        cfg.enabled = True
        cfg.site_values = {
            "BASE_COOKIE_DOMAIN": nw_base_domain,
            "CONSTRUCTOR_LINK": f"{HTTP_PROTOCOL}://{nw_constructor_domain}",
            "ENABLE_COMBINED_LOGIN_REGISTRATION": True,
            "platform_name": "Weave",
            "PLATFORM_NAME": "Weave",
            "site_domain": nw_preview_domain,
            "logo_image_url": "images/weave-logo.png",
            "LMS_BASE": nw_preview_domain,
            "CMS_BASE": nw_cms_domain,
            "LMS_ROOT_URL": f"{HTTP_PROTOCOL}://{nw_preview_domain}",
            "SITE_NAME": nw_preview_domain,
            "SESSION_COOKIE_DOMAIN": f".{nw_base_domain}",
            "HIDE_PROFILE": False,
            "TECH_SUPPORT_EMAIL": "support@nimblywise.com",
            "PREVIEW_LMS_BASE": nw_preview_domain,
            "INSIGHTS_LINK": f"{HTTP_PROTOCOL}://{nw_insights_domain}",
            "SHOW_NW_HELP": True,
            "email_error_support": "support@nimblywise.com",
            "email_from_address": "support@nimblywise.com",
            "SKILLS_MFE_URL": f"{HTTP_PROTOCOL}://{nw_skills_domain}",
            "supervisor_generate_pdf": True,
            "LEARNING_MICROFRONTEND_URL": f"{HTTP_PROTOCOL}://{nw_learning_domain}",
            "SOCIAL_AUTH_EDX_OAUTH2_URL_ROOT": f"{HTTP_PROTOCOL}://{nw_lms_domain}",
            "SOCIAL_AUTH_EDX_OAUTH2_PUBLIC_URL_ROOT": f"{HTTP_PROTOCOL}://{nw_lms_domain}"
        }
        cfg.save()

        cfg, _ = SiteConfiguration.objects.get_or_create(site=weave_lms_site)
        cfg.enabled = True
        cfg.site_values = {
            "BASE_COOKIE_DOMAIN": weave_base_domain,
            "CONSTRUCTOR_LINK": f"{HTTP_PROTOCOL}://{weave_constructor_domain}",
            "ENABLE_COMBINED_LOGIN_REGISTRATION": True,
            "platform_name": "Weave",
            "PLATFORM_NAME": "Weave",
            "site_domain": weave_lms_domain,
            "logo_image_url": "images/weave-logo.png",
            "LMS_BASE": weave_lms_domain,
            "CMS_BASE": weave_cms_domain,
            "LMS_ROOT_URL": f"{HTTP_PROTOCOL}://{weave_lms_domain}",
            "SITE_NAME": weave_lms_domain,
            "SESSION_COOKIE_DOMAIN": f".{weave_base_domain}",
            "HIDE_PROFILE": False,
            "SHOW_NW_HELP": True,
            "TECH_SUPPORT_EMAIL": "supportteam@weaveeducation.com",
            "PREVIEW_LMS_BASE": weave_preview_domain,
            "INSIGHTS_LINK": f"{HTTP_PROTOCOL}://{weave_insights_domain}",
            "email_error_support": "supportteam@weaveeducation.com",
            "email_from_address": "supportteam@weaveeducation.com",
            "ACTIVATION_EMAIL_FROM_ADDRESS": "supportteam@weaveeducation.com",
            "SKILLS_MFE_URL": f"{HTTP_PROTOCOL}://{weave_skills_domain}",
            "supervisor_generate_pdf": True,
            "urls": {
                "PRIVACY": "https://weaveeducation.com/privacy-policy/",
                "ABOUT": "https://weaveeducation.com"
            },
            "LEARNING_MICROFRONTEND_URL": f"{HTTP_PROTOCOL}://{weave_learning_domain}",
            "SOCIAL_AUTH_EDX_OAUTH2_URL_ROOT": f"{HTTP_PROTOCOL}://{weave_lms_domain}",
            "SOCIAL_AUTH_EDX_OAUTH2_PUBLIC_URL_ROOT": f"{HTTP_PROTOCOL}://{weave_lms_domain}"
        }
        cfg.save()

        cfg, _ = SiteConfiguration.objects.get_or_create(site=weave_cms_site)
        cfg.enabled = True
        cfg.site_values = {
            "BASE_COOKIE_DOMAIN": weave_base_domain,
            "ENABLE_COMBINED_LOGIN_REGISTRATION": True,
            "platform_name": "Weave",
            "PLATFORM_NAME": "Weave",
            "site_domain": weave_cms_domain,
            "CMS_BASE": weave_cms_domain,
            "LMS_BASE": weave_lms_domain,
            "LMS_ROOT_URL": f"{HTTP_PROTOCOL}://{weave_lms_domain}",
            "SITE_NAME": weave_cms_domain,
            "SESSION_COOKIE_DOMAIN": f".{weave_base_domain}",
            "TECH_SUPPORT_EMAIL": "supportteam@weaveeducation.com",
            "PREVIEW_LMS_BASE": weave_preview_domain,
            "INSIGHTS_LINK": f"{HTTP_PROTOCOL}://{weave_insights_domain}",
            "SHOW_NW_HELP": True,
            "email_error_support": "supportteam@weaveeducation.com",
            "email_from_address": "supportteam@weaveeducation.com",
            "studio_logo_image_url": f"{HTTP_PROTOCOL}://{weave_lms_domain}/static/weave-edx-theme/images/weave-logo-mini.png",
            "SKILLS_MFE_URL": f"{HTTP_PROTOCOL}://{weave_skills_domain}",
            "supervisor_generate_pdf": True,
            "LEARNING_MICROFRONTEND_URL": f"{HTTP_PROTOCOL}://{weave_learning_domain}",
            "SOCIAL_AUTH_EDX_OAUTH2_URL_ROOT": f"{HTTP_PROTOCOL}://{weave_lms_domain}",
            "SOCIAL_AUTH_EDX_OAUTH2_PUBLIC_URL_ROOT": f"{HTTP_PROTOCOL}://{weave_lms_domain}"
        }
        cfg.save()

        cfg, _ = SiteConfiguration.objects.get_or_create(site=weave_preview_site)
        cfg.enabled = True
        cfg.site_values = {
            "BASE_COOKIE_DOMAIN": weave_base_domain,
            "CONSTRUCTOR_LINK": f"{HTTP_PROTOCOL}://{weave_constructor_domain}",
            "ENABLE_COMBINED_LOGIN_REGISTRATION": True,
            "platform_name": "Weave",
            "PLATFORM_NAME": "Weave",
            "site_domain": weave_preview_domain,
            "logo_image_url": "images/weave-logo.png",
            "LMS_BASE": weave_preview_domain,
            "CMS_BASE": weave_cms_domain,
            "LMS_ROOT_URL": f"{HTTP_PROTOCOL}://{weave_preview_domain}",
            "SITE_NAME": weave_preview_domain,
            "SESSION_COOKIE_DOMAIN": f".{weave_base_domain}",
            "HIDE_PROFILE": False,
            "TECH_SUPPORT_EMAIL": "supportteam@weaveeducation.com",
            "PREVIEW_LMS_BASE": weave_preview_domain,
            "INSIGHTS_LINK": f"{HTTP_PROTOCOL}://{weave_insights_domain}",
            "SHOW_NW_HELP": True,
            "email_error_support": "supportteam@weaveeducation.com",
            "email_from_address": "supportteam@weaveeducation.com",
            "SKILLS_MFE_URL": f"{HTTP_PROTOCOL}://{weave_skills_domain}",
            "supervisor_generate_pdf": True,
            "LEARNING_MICROFRONTEND_URL": f"{HTTP_PROTOCOL}://{weave_learning_domain}",
            "SOCIAL_AUTH_EDX_OAUTH2_URL_ROOT": f"{HTTP_PROTOCOL}://{weave_lms_domain}",
            "SOCIAL_AUTH_EDX_OAUTH2_PUBLIC_URL_ROOT": f"{HTTP_PROTOCOL}://{weave_lms_domain}"
        }
        cfg.save()

        cfg, _ = SiteConfiguration.objects.get_or_create(site=credo_lms_site)
        cfg.enabled = True
        cfg.site_values = {
            "BASE_COOKIE_DOMAIN": credo_base_domain,
            "CONSTRUCTOR_LINK": f"{HTTP_PROTOCOL}://{credo_constructor_domain}",
            "ENABLE_COMBINED_LOGIN_REGISTRATION": True,
            "platform_name": "Credo Learning Tools",
            "PLATFORM_NAME": "Credo Learning Tools",
            "site_domain": credo_lms_domain,
            "logo_image_url": "images/credo-reference-logo.jpg",
            "LMS_BASE": credo_lms_domain,
            "CMS_BASE": credo_cms_domain,
            "LMS_ROOT_URL": f"{HTTP_PROTOCOL}://{credo_lms_domain}",
            "SITE_NAME": credo_lms_domain,
            "SESSION_COOKIE_DOMAIN": f".{credo_base_domain}",
            "HIDE_PROFILE": False,
            "DISABLE_REGISTER_BUTTON": True,
            "TECH_SUPPORT_EMAIL": "support@credoreference.com",
            "PREVIEW_LMS_BASE": credo_preview_domain,
            "INSIGHTS_LINK": f"{HTTP_PROTOCOL}://{credo_insights_domain}",
            "SHOW_NW_HELP": False,
            "email_from_address": "info@credocourseware.com",
            "email_error_support": "support@credoreference.com",
            "ACTIVATION_EMAIL_FROM_ADDRESS": "registration@credocourseware.com",
            "INSTRUCTOR_DASHBOARD_CERT_TAB": False,
            "SKILLS_MFE_URL": f"{HTTP_PROTOCOL}://{credo_skills_domain}",
            "supervisor_generate_pdf": True,
            "urls": {
                "TOS_AND_HONOR": "https://corp.credoreference.com/terms-and-conditions.html",
                "PRIVACY": "https://corp.credoreference.com/terms-and-conditions.html",
                "ABOUT": "https://corp.credoreference.com"
            },
            "LEARNING_MICROFRONTEND_URL": f"{HTTP_PROTOCOL}://{credo_learning_domain}",
            "SOCIAL_AUTH_EDX_OAUTH2_URL_ROOT": f"{HTTP_PROTOCOL}://{credo_lms_domain}",
            "SOCIAL_AUTH_EDX_OAUTH2_PUBLIC_URL_ROOT": f"{HTTP_PROTOCOL}://{credo_lms_domain}"
        }
        cfg.save()

        cfg, _ = SiteConfiguration.objects.get_or_create(site=credo_frame_site)
        cfg.enabled = True
        cfg.site_values = {
            "BASE_COOKIE_DOMAIN": credo_base_domain,
            "CONSTRUCTOR_LINK": f"{HTTP_PROTOCOL}://{credo_constructor_domain}",
            "ENABLE_COMBINED_LOGIN_REGISTRATION": True,
            "platform_name": "Credo Learning Tools",
            "PLATFORM_NAME": "Credo Learning Tools",
            "site_domain": credo_lms_domain,
            "logo_image_url": "images/credo-reference-logo.jpg",
            "LMS_BASE": credo_frame_lms_domain,
            "CMS_BASE": credo_cms_domain,
            "LMS_ROOT_URL": f"{HTTP_PROTOCOL}://{credo_frame_lms_domain}",
            "SITE_NAME": credo_frame_lms_domain,
            "SESSION_COOKIE_DOMAIN": f".{credo_lms_domain}",
            "HIDE_PROFILE": False,
            "DISABLE_REGISTER_BUTTON": True,
            "TECH_SUPPORT_EMAIL": "support@credoreference.com",
            "PREVIEW_LMS_BASE": credo_preview_domain,
            "INSIGHTS_LINK": f"{HTTP_PROTOCOL}://{credo_insights_domain}",
            "SHOW_NW_HELP": False,
            "email_from_address": "info@credocourseware.com",
            "email_error_support": "support@credoreference.com",
            "ACTIVATION_EMAIL_FROM_ADDRESS": "registration@credocourseware.com",
            "INSTRUCTOR_DASHBOARD_CERT_TAB": False,
            "DISABLE_LOGO_HOME_URL": True,
            "SKILLS_MFE_URL": f"{HTTP_PROTOCOL}://{credo_skills_domain}",
            "supervisor_generate_pdf": True,
            "urls": {
                "TOS_AND_HONOR": "https://corp.credoreference.com/terms-and-conditions.html",
                "PRIVACY": "https://corp.credoreference.com/terms-and-conditions.html",
                "ABOUT": "https://corp.credoreference.com"
            },
            "LEARNING_MICROFRONTEND_URL": f"{HTTP_PROTOCOL}://{credo_frame_learning_domain}",
            "SOCIAL_AUTH_EDX_OAUTH2_URL_ROOT": f"{HTTP_PROTOCOL}://{credo_lms_domain}",
            "SOCIAL_AUTH_EDX_OAUTH2_PUBLIC_URL_ROOT": f"{HTTP_PROTOCOL}://{credo_lms_domain}"
        }
        cfg.save()

        cfg, _ = SiteConfiguration.objects.get_or_create(site=credo_cms_site)
        cfg.enabled = True
        cfg.site_values = {
            "BASE_COOKIE_DOMAIN": credo_base_domain,
            "ENABLE_COMBINED_LOGIN_REGISTRATION": True,
            "platform_name": "Credo Learning Tools",
            "PLATFORM_NAME": "Credo Learning Tools",
            "site_domain": credo_cms_domain,
            "CMS_BASE": credo_cms_domain,
            "LMS_BASE": credo_lms_domain,
            "LMS_ROOT_URL": f"{HTTP_PROTOCOL}://{credo_lms_domain}",
            "SITE_NAME": credo_cms_domain,
            "SESSION_COOKIE_DOMAIN": f".{credo_base_domain}",
            "TECH_SUPPORT_EMAIL": "support@credoreference.com",
            "PREVIEW_LMS_BASE": credo_preview_domain,
            "INSIGHTS_LINK": f"{HTTP_PROTOCOL}://{credo_insights_domain}",
            "SHOW_NW_HELP": False,
            "email_from_address": "info@credocourseware.com",
            "email_error_support": "support@credoreference.com",
            "DISABLE_REGISTER_BUTTON": True,
            "studio_logo_image_url": f"{HTTP_PROTOCOL}://{credo_lms_domain}/static/credo-theme/images/credo-reference-logo.jpg",
            "highlights_enabled": False,
            "SKILLS_MFE_URL": f"{HTTP_PROTOCOL}://{credo_skills_domain}",
            "supervisor_generate_pdf": True,
            "LEARNING_MICROFRONTEND_URL": f"{HTTP_PROTOCOL}://{credo_learning_domain}",
            "SOCIAL_AUTH_EDX_OAUTH2_URL_ROOT": f"{HTTP_PROTOCOL}://{credo_lms_domain}",
            "SOCIAL_AUTH_EDX_OAUTH2_PUBLIC_URL_ROOT": f"{HTTP_PROTOCOL}://{credo_lms_domain}"
        }
        cfg.save()

        cfg, _ = SiteConfiguration.objects.get_or_create(site=credo_preview_site)
        cfg.enabled = True
        cfg.site_values = {
            "BASE_COOKIE_DOMAIN": credo_base_domain,
            "CONSTRUCTOR_LINK": f"{HTTP_PROTOCOL}://{credo_constructor_domain}",
            "ENABLE_COMBINED_LOGIN_REGISTRATION": True,
            "platform_name": "Credo Learning Tools",
            "PLATFORM_NAME": "Credo Learning Tools",
            "site_domain": credo_preview_domain,
            "logo_image_url": "images/credo-reference-logo.jpg",
            "LMS_BASE": credo_preview_domain,
            "CMS_BASE": credo_cms_domain,
            "LMS_ROOT_URL": f"{HTTP_PROTOCOL}://{credo_preview_domain}",
            "SITE_NAME": credo_preview_domain,
            "SESSION_COOKIE_DOMAIN": f".{credo_base_domain}",
            "HIDE_PROFILE": False,
            "DISABLE_REGISTER_BUTTON": True,
            "TECH_SUPPORT_EMAIL": "support@credoreference.com",
            "PREVIEW_LMS_BASE": credo_preview_domain,
            "INSIGHTS_LINK": f"{HTTP_PROTOCOL}://{credo_insights_domain}",
            "SHOW_NW_HELP": False,
            "email_from_address": "info@credocourseware.com",
            "email_error_support": "support@credoreference.com",
            "INSTRUCTOR_DASHBOARD_CERT_TAB": False,
            "SKILLS_MFE_URL": f"{HTTP_PROTOCOL}://{credo_skills_domain}",
            "supervisor_generate_pdf": True,
            "LEARNING_MICROFRONTEND_URL": f"{HTTP_PROTOCOL}://{credo_learning_domain}",
            "SOCIAL_AUTH_EDX_OAUTH2_URL_ROOT": f"{HTTP_PROTOCOL}://{credo_lms_domain}",
            "SOCIAL_AUTH_EDX_OAUTH2_PUBLIC_URL_ROOT": f"{HTTP_PROTOCOL}://{credo_lms_domain}"
        }
        cfg.save()

        print('---------------> Create/Update Custom Features')

        instructor_dashboard_dp_feature, _ = Feature.objects.get_or_create(
            feature_name=Feature.INSTRUCTOR_DASHBOARD_REPORTS_DATAPICKER
        )
        instructor_dashboard_dp_feature.status = FeatureStatus.PUBLISHED
        instructor_dashboard_dp_feature.save()

        print('---------------> Create/Update Xblocks')

        xblock_aside_cfg = XBlockAsidesConfig.objects.all().first()
        if not xblock_aside_cfg:
            xblock_aside_cfg = XBlockAsidesConfig()
            xblock_aside_cfg.enabled = True
            xblock_aside_cfg.disabled_blocks = "about course_info static_tab"
            xblock_aside_cfg.save()

        xblock_cms_cfg_data = XBlockAsidesConfig.objects.raw("SELECT * FROM xblock_config_studioconfig")
        studio_cfg_found = False
        for studio_cfg_item in xblock_cms_cfg_data:
            studio_cfg_found = True
        if not studio_cfg_found:
            with connection.cursor() as cursor:
                cursor.execute("INSERT INTO xblock_config_studioconfig values "
                               "(NULL, NOW(), 1, 'about course_info static_tab', NULL)")

        print('---------------> Setup Waffle Flags/Switches')

        flags = {
            "course_home_mfe_progress_tab": True,
            "certificates_revamp.use_updated": True,
            "course_experience.disable_dates_tab": True,
            "contentstore.enable_copy_paste_feature": True,
            "instructor.enable_data_download_v2": True,
            "grades.writable_gradebook": False,
            "grades.enforce_freeze_grade_after_course_end": False,
            "grades.rejected_exam_overrides_grade": False,
            "studio.enable_checklists_quality": False,
        }

        for flag, perm in flags.items():
            flag_obj, _ = Flag.objects.get_or_create(name=flag)
            if not flag_obj:
                flag_obj = Flag(name=flag)
            flag_obj.everyone = True
            flag_obj.superusers = True
            flag_obj.staff = perm
            flag_obj.authenticated = perm
            flag_obj.save()

        switches = [
            "certificates.auto_certificate_generation",
            "grades.disable_regrade_on_policy_change",
            "student.courseenrollment_admin",
            "enable_new_course_outline",
            "completion.enable_completion_tracking",
            "completion.enable_visual_progress"
        ]

        for switch in switches:
            switch_obj, _ = Switch.objects.get_or_create(name=switch)
            if not switch_obj:
                switch_obj = Switch(name=switch)
            switch_obj.active = True
            switch_obj.save()

        print('---------------> Update CertificateGenerationConfiguration model')

        cert_conf_obj = CertificateGenerationConfiguration.objects.all().first()
        if not cert_conf_obj:
            cert_conf_obj = CertificateGenerationConfiguration()
            cert_conf_obj.enabled = True
            cert_conf_obj.save()

        print('---------------> Update LoginRedirectAllowedHost model')

        allowed_redirects_list = [
            nw_cms_domain,
            nw_learning_domain,
            nw_skills_domain,
            credo_cms_domain,
            credo_learning_domain,
            credo_skills_domain,
            weave_cms_domain,
            weave_learning_domain,
            weave_skills_domain,
        ]
        for redirect_host in allowed_redirects_list:
            redirect_obj = LoginRedirectAllowedHost.objects.filter(host=redirect_host).first()
            if not redirect_obj:
                redirect_obj = LoginRedirectAllowedHost(
                    host=redirect_host,
                    is_active=True,
                    require_https=not islocal
                )
                redirect_obj.save()

        print('---------------> Setup TrackingLogConfig')

        tl_obj = TrackingLogConfig.objects.filter(key="last_log_time").first()
        if not tl_obj:
            TrackingLogConfig(
                key="last_log_time",
                value=datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')
            ).save()

        tl_obj = TrackingLogConfig.objects.filter(key="update_process_num").first()
        if not tl_obj:
            TrackingLogConfig(
                key="update_process_num",
                value="1"
            ).save()

        tl_obj = TrackingLogConfig.objects.filter(key="last_usage_log_time").first()
        if not tl_obj:
            TrackingLogConfig(
                key="last_usage_log_time",
                value=datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')
            ).save()

        tl_obj = TrackingLogConfig.objects.filter(key="update_usage_process_num").first()
        if not tl_obj:
            TrackingLogConfig(
                key="update_usage_process_num",
                value="1"
            ).save()

        tl_obj = TrackingLogConfig.objects.filter(key="last_enrollment_log_time").first()
        if not tl_obj:
            TrackingLogConfig(
                key="last_enrollment_log_time",
                value=datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')
            ).save()

        tl_obj = TrackingLogConfig.objects.filter(key="update_enrollment_process_num").first()
        if not tl_obj:
            TrackingLogConfig(
                key="update_enrollment_process_num",
                value="1"
            ).save()

        tl_obj = TrackingLogConfig.objects.filter(key="update_props_process_num").first()
        if not tl_obj:
            TrackingLogConfig(
                key="update_props_process_num",
                value="1"
            ).save()

        print('---------------> Setup Periodic Tasks')

        cron_def, _ = CrontabSchedule.objects.get_or_create(
            minute="*",
            hour="*",
            day_of_week="*",
            day_of_month="*",
            month_of_year="*",
        )
        cron_1, _ = CrontabSchedule.objects.get_or_create(
            minute="*/5",
            hour="*",
            day_of_week="*",
            day_of_month="*",
            month_of_year="*",
        )
        cron_2, _ = CrontabSchedule.objects.get_or_create(
            minute="0",
            hour="*",
            day_of_week="*",
            day_of_month="*",
            month_of_year="*",
        )

        PeriodicTask.objects.get_or_create(
            name="openedx.core.djangoapps.content.block_structure.tasks.update_structure_of_all_courses",
            task="openedx.core.djangoapps.content.block_structure.tasks.update_structure_of_all_courses",
            defaults={
                "enabled": True,
                "crontab": cron_1
            }
        )

        PeriodicTask.objects.get_or_create(
            name="lms.djangoapps.courseware.tasks.exec_delayed_tasks",
            task="lms.djangoapps.courseware.tasks.exec_delayed_tasks",
            defaults={
                "enabled": True,
                "crontab": cron_def
            }
        )

        print('---------------> Setup Oauth')

        studio_worker_user = User.objects.filter(username="studio_worker").first()
        if not studio_worker_user:
            studio_worker_user = User.objects.create_user(
                email="studio_worker@example.com",
                username="studio_worker",
                password=str(uuid.uuid4()),
                is_staff=True,
                is_superuser=True,
                is_active=True
            )

        studio_sso_app = Application.objects.filter(name="studio-sso").first()
        if not studio_sso_app:
            studio_sso_app = Application(
                name="studio-sso",
                user=studio_worker_user,
                client_type=Application.CLIENT_CONFIDENTIAL,
                authorization_grant_type=Application.GRANT_AUTHORIZATION_CODE,
                skip_authorization=True
            )
            studio_sso_app.save()

        studio_sso_app = Application.objects.filter(name="studio-sso").first()
        if not studio_sso_app:
            studio_sso_app = Application(
                name="studio-sso",
                user=studio_worker_user,
                client_type=Application.CLIENT_CONFIDENTIAL,
                authorization_grant_type=Application.GRANT_AUTHORIZATION_CODE,
                skip_authorization=True,
                redirect_uris=f"{HTTP_PROTOCOL}://{nw_cms_domain}/complete/edx-oauth2/ "
                              f"{HTTP_PROTOCOL}://{weave_cms_domain}/complete/edx-oauth2/ "
                              f"{HTTP_PROTOCOL}://{credo_cms_domain}/complete/edx-oauth2/"
            )
            studio_sso_app.save()

        studio_backend_service_app = Application.objects.filter(name="studio-backend-service").first()
        if not studio_backend_service_app:
            studio_backend_service_app = Application(
                name="studio-backend-service",
                user=studio_worker_user,
                client_type=Application.CLIENT_CONFIDENTIAL,
                authorization_grant_type=Application.GRANT_CLIENT_CREDENTIALS,
                client_id="studio-backend-service-key",
                client_secret="studio-backend-service-secret",
                skip_authorization=False,
            )
            studio_backend_service_app.save()

        constructor_app = Application.objects.filter(name="constructor production").first()
        if not constructor_app:
            constructor_app = Application(
                name="constructor production",
                client_type=Application.CLIENT_CONFIDENTIAL,
                authorization_grant_type=Application.GRANT_AUTHORIZATION_CODE,
                skip_authorization=True,
                redirect_uris=f"{HTTP_PROTOCOL}://{nw_constructor_domain} "
                              f"{HTTP_PROTOCOL}://{nw_constructor_domain}/login "
                              f"{HTTP_PROTOCOL}://{nw_constructor_domain}/logout "
                              f"{HTTP_PROTOCOL}://{nw_constructor_domain}/complete/edx-oauth2/ "
                              f"{HTTP_PROTOCOL}://{weave_constructor_domain} "
                              f"{HTTP_PROTOCOL}://{weave_constructor_domain}/login "
                              f"{HTTP_PROTOCOL}://{weave_constructor_domain}/logout "
                              f"{HTTP_PROTOCOL}://{weave_constructor_domain}/complete/edx-oauth2/ "
                              f"{HTTP_PROTOCOL}://{credo_constructor_domain} "
                              f"{HTTP_PROTOCOL}://{credo_constructor_domain}/login "
                              f"{HTTP_PROTOCOL}://{credo_constructor_domain}/logout "
                              f"{HTTP_PROTOCOL}://{credo_constructor_domain}/complete/edx-oauth2/ "
            )
            constructor_app.save()

        insights_app = Application.objects.filter(name="insights production").first()
        if not insights_app:
            insights_app = Application(
                name="insights production",
                client_type=Application.CLIENT_CONFIDENTIAL,
                authorization_grant_type=Application.GRANT_AUTHORIZATION_CODE,
                skip_authorization=True,
                redirect_uris=f"{HTTP_PROTOCOL}://{nw_insights_domain} "
                              f"{HTTP_PROTOCOL}://{nw_insights_domain}/login "
                              f"{HTTP_PROTOCOL}://{nw_insights_domain}/logout "
                              f"{HTTP_PROTOCOL}://{nw_insights_domain}/complete/edx-oauth2/ "
                              f"{HTTP_PROTOCOL}://{weave_insights_domain} "
                              f"{HTTP_PROTOCOL}://{weave_insights_domain}/login "
                              f"{HTTP_PROTOCOL}://{weave_insights_domain}/logout "
                              f"{HTTP_PROTOCOL}://{weave_insights_domain}/complete/edx-oauth2/ "
                              f"{HTTP_PROTOCOL}://{credo_insights_domain} "
                              f"{HTTP_PROTOCOL}://{credo_insights_domain}/login "
                              f"{HTTP_PROTOCOL}://{credo_insights_domain}/logout "
                              f"{HTTP_PROTOCOL}://{credo_insights_domain}/complete/edx-oauth2/ "
            )
            insights_app.save()

            app_access = ApplicationAccess.objects.filter(application=studio_sso_app).first()
            if not app_access:
                ApplicationAccess(
                    application=studio_sso_app,
                    scopes=["user_id"]
                ).save()

            app_access = ApplicationAccess.objects.filter(application=constructor_app).first()
            if not app_access:
                ApplicationAccess(
                    application=constructor_app,
                    scopes=["user_id", "profile", "email"]
                ).save()

            app_access = ApplicationAccess.objects.filter(application=insights_app).first()
            if not app_access:
                ApplicationAccess(
                    application=insights_app,
                    scopes=["user_id", "profile", "email"]
                ).save()

        print('---------------> Done')
