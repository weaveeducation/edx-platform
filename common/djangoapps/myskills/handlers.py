from corsheaders.signals import check_request_enabled


def cors_allow_myskills_api(sender, request, **kwargs):
    return request.path.startswith('/api/myskills')


check_request_enabled.connect(cors_allow_myskills_api)
