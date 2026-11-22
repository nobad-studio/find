"""get_settings, set_settings, hotkey_state, hotkey_probe, pick_folder, rescan, wipe, scope_info, turbo_state, turbo_set,
turbo_helper.

Every value goes through settings.coerce inside Api.set_settings. pick_folder shows
Windows' folder dialog from the engine, so the UI never hands the engine a folder path of its own."""
import threading

from ..protocol import INVALID_PARAMS, RpcError, bool_param, ok, str_param

_asking = threading.Lock()          # one turbo permission prompt at a time
BUSY = "Windows is already asking for permission. Answer that window first."


def methods(api, events=None):
    def set_settings(params, conn=None):
        changes = params.get("changes")
        if not isinstance(changes, dict):
            raise RpcError(INVALID_PARAMS, "'changes' must be an object of setting names and values")
        consent = params.get("consent")
        if consent is not None and not (isinstance(consent, str) and len(consent) <= 40):
            raise RpcError(INVALID_PARAMS, "'consent' must be a short string")
        r = (api.set_settings(changes, consent) if consent is not None else api.set_settings(changes)) or {}
        out = {"changed": list(r.get("changed") or []), "settings": api.get_settings()}
        if isinstance(r.get("hotkeys"), dict):
            out["hotkeys"] = r["hotkeys"]
        return out

    def hotkey_probe(params, conn=None):
        which = str_param(params, "which")
        if which not in ("hotkey", "bar_hotkey"):
            raise RpcError(INVALID_PARAMS, "'which' must be hotkey or bar_hotkey")
        spec = str_param(params, "spec")
        if len(spec) > 40:
            raise RpcError(INVALID_PARAMS, "'spec' is too long")
        return api.hotkey_probe(which, spec)

    def pick_folder(params, conn=None):
        """busy: a folder dialog is already open (it was brought to the front); path is "" then."""
        r = api.pick_folder() or {}
        return {"path": str(r.get("path") or ""), "busy": bool(r.get("busy"))}

    def turbo_set(params, conn=None):
        on = bool_param(params, "on")
        if not _asking.acquire(blocking=False):
            return {"ok": False, "error": BUSY, "state": api.turbo_state()}
        try:
            r = api.turbo_set(on) or {}
        finally:
            _asking.release()
        out = ok(r)
        out["state"] = r.get("state") if isinstance(r.get("state"), dict) else api.turbo_state()
        if events is not None:
            events.turbo(out["state"])
        return out

    def turbo_helper(params, conn=None):
        action = str_param(params, "action")
        if action not in ("update", "remove"):
            raise RpcError(INVALID_PARAMS, "'action' must be update or remove")
        if not _asking.acquire(blocking=False):
            return {"ok": False, "error": BUSY, "state": api.turbo_state()}
        try:
            r = api.turbo_helper(action) or {}
        finally:
            _asking.release()
        out = ok(r)
        out["state"] = r.get("state") if isinstance(r.get("state"), dict) else api.turbo_state()
        if events is not None:
            events.turbo(out["state"])
        return out

    return {"get_settings": lambda params, conn=None: api.get_settings(),
            "scope_info": lambda params, conn=None: api.scope_info(),
            "turbo_state": lambda params, conn=None: api.turbo_state(),
            "turbo_set": turbo_set,
            "turbo_helper": turbo_helper,
            "set_settings": set_settings,
            "hotkey_state": lambda params, conn=None: api.hotkey_state(),
            "hotkey_probe": hotkey_probe,
            "pick_folder": pick_folder,
            "rescan": lambda params, conn=None: ok(api.rescan()),
            "wipe": lambda params, conn=None: ok(api.wipe(str_param(params, "confirm")))}
