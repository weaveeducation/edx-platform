from openedx.core.djangoapps.site_configuration import helpers as configuration_helpers


def studio_configuration_context(request):
    disable_register_button = configuration_helpers.get_value('DISABLE_REGISTER_BUTTON', False)
    studio_logo_url = configuration_helpers.get_value('studio_logo_image_url', 'images/studio-logo.png')
    studio_logo_url_is_abs = studio_logo_url.startswith('http')
    return {
        'disable_register_button': disable_register_button,
        'studio_logo_url': studio_logo_url,
        'studio_logo_url_is_abs': studio_logo_url_is_abs
    }
