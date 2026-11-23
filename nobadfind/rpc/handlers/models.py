"""Model downloads and tiers.

download_model, download_photo_model (0.7.0: only with the download allowed in Settings, the Api checks it) stay as
they were. models, model_use, model_download, model_remove, model_folder, auto_configure, model_language: Settings -> Models
(models.CATALOG). Progress comes as `download` events (id = the model id), changes as `models` events.
setup_offer, setup_accept, setup_later (1.2.0): the first-run models window (firstrun.py)."""
import re

from ..protocol import INVALID_PARAMS, RpcError, choice_param, ok, str_param

_ID = re.compile(r"^[a-z0-9][a-z0-9.-]{0,63}$")
FEATURES = ("text", "photo", "ocr")
FOCUSES = ("english", "multilingual", "hindi")


def _model_id(params):
    v = str_param(params, "id")
    if not _ID.match(v):
        raise RpcError(INVALID_PARAMS, "'id' must be a model id from the models list")
    return v


def _consent(params):
    v = str_param(params, "consent")
    if len(v) > 32:
        raise RpcError(INVALID_PARAMS, "'consent' is at most 32 characters")
    return v


def _model_ids(params):
    v = params.get("models")
    if not isinstance(v, list) or len(v) > 8 or not all(isinstance(x, str) and _ID.match(x) for x in v):
        raise RpcError(INVALID_PARAMS, "'models' must be a list of at most 8 model ids from the offer")
    return v


def _remind(params):
    v = params.get("remind", True)
    if not isinstance(v, bool):
        raise RpcError(INVALID_PARAMS, "'remind' must be true or false")
    return v


def _accept(api, params):
    r = api.setup_accept(_model_ids(params), _consent(params))
    return {"ok": bool(r.get("ok")), "error": str(r.get("error") or ""),
            "started": [str(x) for x in r.get("started") or []]}


def _use(api, params):
    r = api.model_use(choice_param(params, "feature", FEATURES, None), _model_id(params))
    return {"ok": bool(r.get("ok")), "error": str(r.get("error") or ""), "needs_download": bool(r.get("needs_download"))}


def methods(api, events=None):
    return {"download_model": lambda params, conn=None: ok(api.download_model()),
            "download_photo_model": lambda params, conn=None: ok(api.download_photo_model()),
            "models": lambda params, conn=None: api.models(),
            "capability_state": lambda params, conn=None: api.capability_state(),
            "model_use": lambda params, conn=None: _use(api, params),
            "model_download": lambda params, conn=None: ok(api.model_download(_model_id(params), _consent(params))),
            "model_remove": lambda params, conn=None: ok(api.model_remove(_model_id(params))),
            "model_folder": lambda params, conn=None: ok(api.model_folder(_model_id(params))),
            "auto_configure": lambda params, conn=None: api.auto_configure(),
            "setup_offer": lambda params, conn=None: api.setup_offer(),
            "setup_accept": lambda params, conn=None: _accept(api, params),
            "setup_later": lambda params, conn=None: ok(api.setup_later(_remind(params))),
            "model_language": lambda params, conn=None: ok(api.model_language(
                choice_param(params, "focus", FOCUSES, None)))}
