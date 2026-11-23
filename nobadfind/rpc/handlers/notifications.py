"""notifications_list, notifications_read, notifications_clear: the window's notification bell (notify.py)."""
from ..protocol import INVALID_PARAMS, RpcError, ok

MAX_IDS = 200


def methods(api, events=None):
    def read(params, conn=None):
        if "all" in params:
            if params.get("all") is not True or "ids" in params:
                raise RpcError(INVALID_PARAMS, "give 'ids' or 'all': true")
            r = api.notifications_read(all=True)
        else:
            ids = params.get("ids")
            if not isinstance(ids, list) or len(ids) > MAX_IDS or \
                    not all(isinstance(i, int) and not isinstance(i, bool) for i in ids):
                raise RpcError(INVALID_PARAMS, f"'ids' must be a list of at most {MAX_IDS} whole numbers")
            r = api.notifications_read(ids=ids)
        out = ok(r)
        out["unread"] = int((r or {}).get("unread") or 0)
        return out

    def listing(params, conn=None):
        r = api.notifications_list() or {}
        return {"items": list(r.get("items") or []), "unread": int(r.get("unread") or 0)}

    return {"notifications_list": listing,
            "notifications_read": read,
            "notifications_clear": lambda params, conn=None: ok(api.notifications_clear())}
