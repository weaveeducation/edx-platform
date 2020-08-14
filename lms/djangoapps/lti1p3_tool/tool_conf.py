from pylti1p3.exception import LtiException
from pylti1p3.tool_config.abstract import ToolConfAbstract
from pylti1p3.registration import Registration
from pylti1p3.deployment import Deployment
from .models import LtiTool


class ToolConfDb(ToolConfAbstract):
    _lti_tools = None

    def __init__(self):
        super(ToolConfDb, self).__init__()
        self._lti_tools = {}

    def get_lti_tool(self, iss, client_id):
        lti_tool = self._lti_tools.get(iss) if client_id is None else self._lti_tools.get(iss, {}).get(client_id)
        if lti_tool:
            return lti_tool

        if client_id is None:
            lti_tool = LtiTool.objects.filter(issuer=iss, is_active=True).order_by('use_by_default').first()
        else:
            try:
                lti_tool = LtiTool.objects.get(issuer=iss, client_id=client_id, is_active=True)
            except LtiTool.DoesNotExist:
                pass

        if lti_tool is None:
            raise LtiException('iss %s not found in settings' % iss)

        if client_id is None:
            self._lti_tools[iss] = lti_tool
        else:
            if iss not in self._lti_tools:
                self._lti_tools[iss] = {}
            self._lti_tools[iss][client_id] = lti_tool

        return lti_tool

    def check_iss_has_one_client(self, iss):
        return False

    def check_iss_has_many_clients(self, iss):
        return True

    def find_registration_by_issuer(self, iss, *args, **kwargs):
        pass

    def find_registration_by_params(self, iss, client_id, *args, **kwargs):
        lti_tool = self.get_lti_tool(iss, client_id)
        reg = Registration()
        reg.set_auth_login_url(lti_tool.auth_login_url) \
            .set_auth_token_url(lti_tool.auth_token_url) \
            .set_auth_audience(lti_tool.auth_audience) \
            .set_client_id(lti_tool.client_id) \
            .set_key_set(lti_tool.key_set) \
            .set_key_set_url(lti_tool.key_set_url) \
            .set_issuer(lti_tool.issuer) \
            .set_tool_private_key(lti_tool.tool_key.private_key) \
            .set_tool_public_key(lti_tool.tool_key.public_key)
        return reg

    def find_deployment(self, iss, deployment_id):
        pass

    def find_deployment_by_params(self, iss, deployment_id, client_id, *args, **kwargs):
        lti_tool = self.get_lti_tool(iss, client_id)
        if deployment_id not in lti_tool.deployment_ids:
            return None
        d = Deployment()
        return d.set_deployment_id(deployment_id)
