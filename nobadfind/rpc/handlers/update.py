"""update_state, update_check, update_install (0.9.0): in-app updates (update.py). Install needs consent "INSTALL"."""
from ..protocol import INVALID_PARAMS, RpcError, ok, str_param


def methods(api, events=None):
    def install(params, conn=None):
        consent = str_param(params, "consent")
        if len(consent) > 32:
            raise RpcError(INVALID_PARAMS, "'consent' is at most 32 characters")
        return ok(api.update_install(consent))

    return {"update_state": lambda params, conn=None: api.update_state(),
            "update_check": lambda params, conn=None: ok(api.update_check()),
            "update_install": install}
