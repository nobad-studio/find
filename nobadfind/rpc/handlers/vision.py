"""Talk about a photo (1.1): vision_state, vision_describe, vision_ask, vision_compare, vision_cancel, vision_keep.

Thin: check the shape of the parameters, call Api.vision_*, shape the answer. Every answer carries `job` (the number
the `vision` events of that question will carry; null when no job was started). The answer itself comes as `vision`
events. Photos are named by result id only; the question is cleaned by the Api (prompts.clean_question)."""
from ...api import MAX_KEPT          # characters of a description the user keeps: the Api's one cap
from ..protocol import INVALID_PARAMS, RpcError, int_param

MAX_QUESTION = 2000                 # characters, before cleaning


def _flag(params, key):
    v = params.get(key, False)
    if not isinstance(v, bool):
        raise RpcError(INVALID_PARAMS, f"'{key}' must be true or false")
    return v


def _text(params, key, limit, none_ok=False):
    v = params.get(key)
    if v is None and none_ok:
        return None
    if not isinstance(v, str):
        raise RpcError(INVALID_PARAMS, f"'{key}' must be a string")
    if len(v) > limit:
        raise RpcError(INVALID_PARAMS, f"'{key}' is at most {limit} characters")
    return v


def _job(v):
    return v if isinstance(v, int) and not isinstance(v, bool) and v > 0 else None


def _answer(r):
    """{ok, error, job} (+ download: what to fetch first, when that is why it can't start)."""
    r = r if isinstance(r, dict) else {}
    out = {"ok": bool(r.get("ok")), "error": str(r.get("error") or ""), "job": _job(r.get("job"))}
    if r.get("download"):
        out["download"] = [{"id": str(d["id"]), "name": str(d["name"]), "size_mb": int(d["size_mb"])}
                           for d in r["download"]]
    return out


def _state(api):
    r = api.vision_state()
    return {"ok": bool(r.get("ok")), "error": "", "job": _job(r.get("job")), "not_now": str(r.get("not_now") or ""),
            "models": [{"id": str(m["id"]), "name": str(m["name"]), "deeper": bool(m["deeper"]),
                        "ready": bool(m["ready"]), "missing_mb": int(m["missing_mb"]), "ram_mb": int(m["ram_mb"]),
                        "vram_mb": int(m["vram_mb"]), "load_s": int(m.get("load_s") or 0),
                        "answer_s": [int(x) for x in (m.get("answer_s") or (0, 0))][:2],
                        "can_run": bool(m["can_run"]), "why": str(m["why"] or "")}
                       for m in r["models"]],
            "runtime": {"id": str(r["runtime"]["id"]), "ready": bool(r["runtime"]["ready"]),
                        "missing_mb": int(r["runtime"]["missing_mb"])},
            "loaded": str(r.get("loaded") or ""), "busy": bool(r.get("busy")), "running": bool(r.get("running"))}


def _keep(api, params):
    r = api.vision_keep(int_param(params, "file_id"), _text(params, "text", MAX_KEPT))
    out = _answer(r)
    out["kept"] = bool(isinstance(r, dict) and r.get("kept"))
    return out


def methods(api, events=None):
    return {
        "vision_state": lambda params, conn=None: _state(api),
        "vision_describe": lambda params, conn=None: _answer(api.vision_describe(int_param(params, "file_id"))),
        "vision_ask": lambda params, conn=None: _answer(api.vision_ask(
            int_param(params, "file_id"), _text(params, "question", MAX_QUESTION), _flag(params, "deeper"),
            _flag(params, "more"))),
        "vision_compare": lambda params, conn=None: _answer(api.vision_compare(
            int_param(params, "a"), int_param(params, "b"), _text(params, "question", MAX_QUESTION, none_ok=True))),
        "vision_cancel": lambda params, conn=None: _answer(api.vision_cancel()),
        "vision_keep": lambda params, conn=None: _keep(api, params),
    }
