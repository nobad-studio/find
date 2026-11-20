"""run_action (0.9.1): open a Windows Settings page, a Windows tool or an app by the id a search answer gave."""
from ..protocol import INVALID_PARAMS, RpcError, ok, str_param


def methods(api, events=None):
    def run_action(params, conn=None):
        aid = str_param(params, "id")
        if not aid or len(aid) > 200:
            raise RpcError(INVALID_PARAMS, "'id' must be an action id from a search answer")
        return ok(api.run_action(aid))

    return {"run_action": run_action}
