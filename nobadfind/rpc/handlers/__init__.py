"""Thin RPC handlers: check the shape of the parameters, call the existing Api method, shape its result.

Every check happens inside the Api methods; there is no second copy of the logic.
The shapes are contract/methods.schema.json (tests/test_rpc_contract.py holds the two together).
"""
from . import launch, models, notifications, search, settings, status, system, update, vision

# They wait for the user (a folder dialog, a permission prompt): the server answers them on threads of their own.
SLOW = {"pick_folder", "wsearch_set", "use_instead_of_windows_search", "turbo_set", "turbo_helper"}

# State reports: the server answers them on a small lane of their own, so a slow one never makes a search wait.
# "Reports" is not "pure": some may do small background work on a cold engine (tests/test_rpc.py LANE_KNOWN_EFFECTS
# names each one's effects and tests/test_rpc.py checks none of them saves settings, downloads or writes the index).
# The Dart side retries a "busy: try again" for these names (ui_flutter/lib/engine/rpc.dart statusLane, kept equal).
STATUS_LANE = {"status", "status_full", "hardware", "capability_state", "models", "scope_info", "turbo_state",
               "wsearch_state", "performance_state"}
# Dict reads only: answered on the connection's reader thread, never refused as busy or delayed (the liveness beat).
STATUS_INLINE = {"status"}


def methods(api, events=None, about=system.about):
    """name -> fn(params, conn) for every method in the contract. `about` gives hello's app, version and pid."""
    out = {}
    for mod in (system, search, status, settings, models, update, launch, vision, notifications):
        out.update(mod.methods(api, events))
    out["hello"] = system.hello(sorted(set(out) | {"hello"}), about)
    return out
