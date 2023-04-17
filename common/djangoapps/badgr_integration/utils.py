from common.djangoapps.credo_modules.models import Organization


def org_badgr_enabled(org):
    try:
        org = Organization.objects.get(org=org)
    except Organization.DoesNotExist:
        return False

    return org.is_badgr_enabled
