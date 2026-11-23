"""The governor: turns sensor samples into a work level and a reason.

``Brain`` is pure logic: time comes only from ``Sample.t`` (seconds; ``Brain.pause_until`` is on the
same clock and is shown as a wall-clock time, so callers feed ``time.time()``). ``Governor`` is the
thread that reads the real sensors every couple of seconds, runs the brain and applies the result.
"""
import datetime
import os
import threading
import time
from collections import deque
from dataclasses import dataclass

from . import hardware as _hw
from . import jobs as _jobs
from .const import CREATIVE_APPS
from . import notify, winapi
from .log import log

FULL, GENTLE, LIGHT, PAUSED = "full", "gentle", "light", "paused"
ORDER = [PAUSED, LIGHT, GENTLE, FULL]
CPU_CAP = {FULL: None, GENTLE: 35, LIGHT: 15, PAUSED: 5}
ECO_LEVELS = (LIGHT, PAUSED)        # workers in efficiency mode (EcoQoS)

# Every tunable number lives here.
LIMITS = {
    "HOT_CPU": 85,
    "HOT_GPU": 85,
    "HOT_FOR": 10,
    "LOW_FREE_MB": 1500,
    "TIGHT_FREE_MB": 3000,   # safety net at Boost: below this, one worker (Light) before memory runs out
    "STEP_UP_AFTER": 30,
    "IDLE_AFTER": 120,
    "IDLE_CPU_MAX": 50,
    "LAG_FIND_CORES": 0.5,   # NOBAD Find counts as working (so a lag may be learned) from half a core
    # 2026-11-21, the combined state of Windows. Each rule turns on after ON_FOR seconds of its condition and off
    # only after its clear condition held OFF_FOR seconds and it was on for at least RULE_HOLD (no flapping).
    "HIGH_COMMIT": 85,       # commit charge (% of the commit limit) where the models go, then Light, then Paused
    "COMMIT_CLEAR": 80,
    "COMMIT_LIGHT_AFTER": 20,    # seconds of high commit (after the models were let go) before Light
    "COMMIT_PAUSE_AFTER": 60,    # ... and before Paused
    "DISK_SLOW_MS": 50,      # average ms per transfer on the indexed drives: the walk and the readers slow down
    "DISK_BUSY": 90,         # ... or the disk busy this % of the time
    "DISK_CLEAR_MS": 20,
    "DISK_CLEAR_BUSY": 60,
    "THERMAL_LIMIT": 90,     # Windows holds the processor below this % of its speed (passive cooling): one level down
    "THERMAL_CLEAR": 99,
    "ON_FOR": 4,             # seconds a measured condition must hold to turn its rule on
    "OFF_FOR": 10,           # seconds its clear condition must hold to turn it off
    "RULE_HOLD": 30,         # the least time a rule stays on once it turned on
}

_EASING = {
    PAUSED: "Paused: waiting a moment before starting again",
    LIGHT: "Light: easing back in",
    GENTLE: "Gentle: easing back in",
    FULL: "Full: easing back in",
}


@dataclass
class Sample:
    t: float
    cpu: float | None
    gpu: float | None
    mem_load: int
    free_mb: int
    find_cpu: float
    foreground: str
    game: bool
    presentation: bool
    hung: bool
    battery: bool
    call: bool
    idle_s: float
    foreground_is_self: bool = False     # the window in front is NOBAD Find's own (main window or bar)
    # 2026-11-21: None = unknown, never "bad"
    commit_pct: float | None = None      # commit charge, % of the commit limit (winapi.commit_status)
    commit_free_mb: int | None = None    # what Windows can still promise
    disk_busy: float | None = None       # % of the time the indexed drives' disks are busy (winapi.DiskSampler)
    disk_ms: float | None = None         # average ms per transfer there
    battery_saver: bool | None = None    # Windows' battery saver (winapi.battery_saver)
    thermal: float | None = None         # lowest thermal-zone passive limit, % (100 = no throttling)
    gpu_mem: dict | None = None          # hardware.gpu_memory_free: {"kind", "free_mb", "used_mb", "budget_mb"}


@dataclass
class Decision:
    level: str
    reason: str
    gpu: bool = True             # graphics-card work allowed (no: battery saver, a creative app in front)
    io_slow: bool = False        # the disk is slow: the names walk and the readers slow down (not the meaning step)
    release_models: bool = False     # let go of the models now (high commit; once per episode)


class _Latch:
    """A rule's on/off state with hysteresis: on after its condition held `on_for` seconds; off only after its
    clear condition held `off_for` seconds and it has been on `hold` seconds. Anything else keeps the state. Time
    only from the samples."""

    def __init__(self, on_for=None, off_for=None, hold=None):
        self.on_for = LIMITS["ON_FOR"] if on_for is None else on_for
        self.off_for = LIMITS["OFF_FOR"] if off_for is None else off_for
        self.hold = LIMITS["RULE_HOLD"] if hold is None else hold
        self.on = False
        self.since = None            # when it turned on
        self._want_since = None      # when the condition (off) or the clear condition (on) started holding

    def update(self, t, cond, clear):
        if not self.on:
            if not cond:
                self._want_since = None
            else:
                if self._want_since is None:
                    self._want_since = t
                if t - self._want_since >= self.on_for:
                    self.on, self.since, self._want_since = True, t, None
                    return True              # turned on now
            return False
        if not clear:
            self._want_since = None
        else:
            if self._want_since is None:
                self._want_since = t
            if t - self._want_since >= self.off_for and t - self.since >= self.hold:
                self.on, self.since, self._want_since = False, None, None
        return False


def _app_listed(exe, names):
    exe = (exe or "").lower()
    return bool(exe) and any(exe == (n or "").lower() for n in (names or ()))


def workers_for(level, plan):
    if level == FULL:
        return plan["text_workers_idle"]
    if level == GENTLE:
        return plan["text_workers"]
    if level == LIGHT:
        return 1
    return 0


# Per-operation concurrency (2026-11-21), the one place these limits live: for each operation
# effective = min(user, cpu, memory, governor) (vision: and the graphics card), recomputed every governor tick
# (Governor.limits). OP_MB: the memory one more stream of it needs, so free RAM bounds how many run at once.
OPS = ("walk", "readers", "photo", "vision")
OP_MB = {"walk": 16, "readers": 300, "photo": 100, "vision": 1500}
WALK_SLOW_SHARE = 4      # a slow disk (or Light): a quarter of the walk threads
VISION_GPU_MB = 1024     # free graphics memory one vision stream needs; at most one stream per graphics card


def _fallback_plan(cpu):
    return {"cpu": cpu, "walk_threads": min(32, cpu * 2), "text_workers": max(1, min(8, cpu - 2)),
            "text_workers_idle": max(1, min(16, cpu - 1)), "model_threads": max(1, cpu // 2)}


def op_limits(level, plan, s=None, d=None, settings=None, cpu_count=None):
    """{op: {"user", "cpu", "memory", "governor", ["gpu",] "effective", "by"}} for the names walk, the text
    readers, the photo step (threads of the one photo worker) and the future vision step. "by" names the factor
    that set the effective number. Unknown free memory (None or 0) doesn't limit anything."""
    cpu = int((plan or {}).get("cpu") or cpu_count or os.cpu_count() or 1)
    plan = dict(_fallback_plan(cpu), **{k: v for k, v in (plan or {}).items() if v})
    free = getattr(s, "free_mb", None) or None
    spare = None if free is None else max(0, free - LIMITS["LOW_FREE_MB"])
    io_slow, gpu_ok = bool(getattr(d, "io_slow", False)), bool(getattr(d, "gpu", True))
    get = settings.get if settings is not None else (lambda k: None)

    def mem(op, user):
        return user if spare is None else min(user, spare // OP_MB[op])

    out = {}
    walk = int(plan["walk_threads"])
    gov = {FULL: walk, GENTLE: walk, LIGHT: max(1, walk // WALK_SLOW_SHARE), PAUSED: 0}[level]
    if io_slow:
        gov = min(gov, max(1, walk // WALK_SLOW_SHARE))
    out["walk"] = {"user": walk, "cpu": cpu * 4, "memory": mem("walk", walk), "governor": gov}
    readers = int(get("workers") or plan["text_workers_idle"])
    gov = workers_for(level, plan)
    if io_slow and gov:
        gov = max(1, gov // 2)
    out["readers"] = {"user": readers, "cpu": max(1, cpu - 1), "memory": mem("readers", readers), "governor": gov}
    photo = int(plan["model_threads"]) if get("photo_meaning") is not False else 0
    out["photo"] = {"user": photo, "cpu": max(1, cpu // 2), "memory": mem("photo", photo),
                    "governor": 0 if level == PAUSED else max(1, workers_for(level, plan))}
    gm = getattr(s, "gpu_mem", None)
    gpu = 1 if gpu_ok and (gm is None or gm.get("free_mb", 0) >= VISION_GPU_MB) else 0
    out["vision"] = {"user": 1, "cpu": 1, "memory": mem("vision", 1), "governor": 1 if level in (FULL, GENTLE) else 0,
                     "gpu": gpu}
    for row in out.values():
        by = min(row, key=lambda k: row[k])         # first smallest in order: user, cpu, memory, governor, gpu
        row["effective"], row["by"] = max(0, int(row[by])), by
    return out


def _app(exe, unknown="an app"):
    name = (exe or "").lower()
    if name.endswith(".exe"):
        name = name[:-4]
    return name or unknown


def _prefix(level):
    return level.capitalize()


class Brain:
    def __init__(self, settings, apps, cpu_count=None):
        self.settings = settings
        self.apps = apps
        self.cpu_count = cpu_count or os.cpu_count() or 1     # find_cpu is a percent of all of them
        self.pause_until = 0.0
        self._level = None       # level currently applied
        self._up_since = None    # when a higher level became continuously allowed
        self._hot_since = None   # when CPU/GPU became continuously hot
        self._lag_recorded = False  # this lag episode already sent to record_lag
        self.fixed = None        # a level pinned for a measurement (engine.measure_overrides, dev only)
        self.commit = _Latch()                                   # Windows close to its commit limit
        self.disk = _Latch()                                     # the indexed drives' disk is slow
        self.saver = _Latch(on_for=0)                            # battery saver: at once, off after OFF_FOR
        self.thermal = _Latch(off_for=60)                        # held back by heat; it cools slowly
        self.creative = _Latch(on_for=0)                         # a heavy creative app in front
        self._creative_exe = ""

    def _creative_apps(self):
        names = self.settings.get("creative_apps")
        return CREATIVE_APPS if names is None else names

    def _sense_rules(self, s):
        """Every 2026-11-21 rule's latch from this sample; True when high commit started now (let go of models)."""
        L = LIMITS
        started = self.commit.update(s.t, s.commit_pct is not None and s.commit_pct >= L["HIGH_COMMIT"],
                                     s.commit_pct is None or s.commit_pct < L["COMMIT_CLEAR"])
        self.disk.update(s.t, (s.disk_ms is not None and s.disk_ms >= L["DISK_SLOW_MS"])
                         or (s.disk_busy is not None and s.disk_busy >= L["DISK_BUSY"]),
                         (s.disk_ms is None or s.disk_ms < L["DISK_CLEAR_MS"])
                         and (s.disk_busy is None or s.disk_busy < L["DISK_CLEAR_BUSY"]))
        self.saver.update(s.t, s.battery_saver is True, s.battery_saver is not True)
        self.thermal.update(s.t, s.thermal is not None and s.thermal < L["THERMAL_LIMIT"],
                            s.thermal is None or s.thermal >= L["THERMAL_CLEAR"])
        front = _app_listed(s.foreground, self._creative_apps()) and not s.foreground_is_self
        self.creative.update(s.t, front, not front)
        if self.creative.on and front:
            self._creative_exe = s.foreground
        return started

    def _commit_stage(self, t):
        """0 = models let go, 1 = Light, 2 = Paused; None when commit isn't high."""
        if not self.commit.on:
            return None
        held = t - self.commit.since
        return 2 if held >= LIMITS["COMMIT_PAUSE_AFTER"] else 1 if held >= LIMITS["COMMIT_LIGHT_AFTER"] else 0

    def _wanted(self, s):
        level, reason = self._wanted_base(s)
        if self.thermal.on and level != PAUSED:
            lower = ORDER[ORDER.index(level) - 1]
            held = f" to {round(s.thermal)}% of its speed" if s.thermal is not None else ""
            return lower, (f"{_prefix(lower)}: Windows is holding the processor back{held} to cool it, "
                           "so NOBAD Find works one level lower")
        return level, reason

    def _games_mode(self):
        mode = self.settings.get("games_mode")
        return mode if mode in ("always", "smart", "off") else "smart"

    def _wanted_base(self, s):
        """The level the sensors allow right now, with its reason. CPU is what the other apps use: Find's own
        work must not count as you using the PC (Full would never hold while you're away)."""
        others = None if s.cpu is None else max(0.0, s.cpu - (s.find_cpu or 0.0))
        hot = ((others is not None and others >= LIMITS["HOT_CPU"])
               or (s.gpu is not None and s.gpu >= LIMITS["HOT_GPU"]))
        if not hot:
            self._hot_since = None
        elif self._hot_since is None:
            self._hot_since = s.t
        hot_long = hot and s.t - self._hot_since >= LIMITS["HOT_FOR"]

        early = None
        if s.t < self.pause_until:
            until = datetime.datetime.fromtimestamp(self.pause_until).strftime("%H:%M")
            early = f"Paused: you asked for a break until {until}"
        elif s.presentation:
            early = "Paused: presentation or quiet time"
        elif self.settings.get("pause_on_battery") and s.battery:
            early = "Paused: on battery"
        elif self.settings.get("pause_on_call") and s.call:
            early = "Paused: microphone or camera in use"
        if early:
            self._lag_recorded = False
            return PAUSED, early

        net = self.settings.get("safety_net") is not False
        lag = None
        if s.hung:
            lag = f"Paused: {_app(s.foreground)} isn't responding"
        elif hot_long and net:
            lag = f"Paused: the PC is busy (CPU {round(others)}%)" if (
                others is not None and others >= LIMITS["HOT_CPU"]
            ) else f"Paused: the PC is busy (graphics {round(s.gpu)}%)"
        elif s.free_mb < LIMITS["LOW_FREE_MB"]:
            lag = f"Paused: low on memory ({s.free_mb} MB free)"
        if lag:
            # learned only while Find is working, and never about Find's own window (still paused either way)
            # in cores, not a share of all CPUs: one Light worker on a 32-thread PC is only about 3%
            working = (s.find_cpu or 0.0) * self.cpu_count / 100 >= LIMITS["LAG_FIND_CORES"]
            if not self._lag_recorded and s.foreground and working and not s.foreground_is_self:
                self.apps.record_lag(s.foreground, s)
                self._lag_recorded = True
            return PAUSED, lag
        self._lag_recorded = False
        stage = self._commit_stage(s.t)
        commit = f"{round(s.commit_pct)}%" if s.commit_pct is not None else "high"
        if stage == 2:
            return PAUSED, (f"Paused: Windows is close to the memory it can promise programs (commit {commit}) "
                            "for a minute")
        boost = self.settings.get("power") == "boost"
        if net and boost and s.free_mb < LIMITS["TIGHT_FREE_MB"]:
            return LIGHT, f"Light: memory is getting tight ({s.free_mb} MB free), so NOBAD Find uses 1 worker"
        if net and hot and boost:
            return GENTLE, "Gentle: other apps need the processor, so Boost steps down"
        if stage == 1:
            return LIGHT, (f"Light: Windows is close to the memory it can promise programs (commit {commit}), "
                           "so NOBAD Find let go of its models and uses 1 worker")
        if self.saver.on:
            return LIGHT, "Light: battery saver is on, so NOBAD Find uses 1 worker and not the graphics card"

        if s.game:
            mode = self._games_mode()
            if mode == "always":
                return PAUSED, f"Paused: {_app(s.foreground, 'a game')} is running"
            if mode == "smart":
                learned = self.apps.start_level(s.foreground) if s.foreground else None
                if learned in ORDER and ORDER.index(learned) < ORDER.index(LIGHT):
                    return learned, (f"{_prefix(learned)}: NOBAD Find learned to "
                                     f"make room for {_app(s.foreground, 'a game')}")
                return LIGHT, (f"Light: {_app(s.foreground, 'a game')} is running, "
                               "so NOBAD Find uses 1 worker")
        if self.creative.on:
            return LIGHT, (f"Light: {_app(self._creative_exe, 'a creative app')} is in front, so NOBAD Find uses "
                           "1 worker and leaves the graphics card to it")
        if (s.idle_s >= LIMITS["IDLE_AFTER"] and others is not None
                and others < LIMITS["IDLE_CPU_MAX"]):
            return FULL, "Boost: every thread" if boost else "Full: you're away"
        if boost:
            return FULL, "Boost: every thread, even while you use the PC"
        return GENTLE, "Gentle: you're using the PC"

    def decide(self, s):
        if self.fixed in ORDER:
            self._level = self.fixed
            return Decision(self.fixed, f"{_prefix(self.fixed)}: fixed for a measurement")
        release = self._sense_rules(s)
        d = self._step(s)
        d.release_models = release
        d.gpu = not (self.saver.on or self.creative.on)
        d.io_slow = self.disk.on
        if d.io_slow and d.level != PAUSED:
            if s.disk_ms is not None and s.disk_ms >= LIMITS["DISK_CLEAR_MS"]:
                how = f"{round(s.disk_ms)} ms a transfer"
            elif s.disk_busy is not None:
                how = f"busy {round(s.disk_busy)}% of the time"
            else:
                how = "busy"
            d.reason += f"; the disk is slow ({how}), so the file walk and the readers slow down"
        return d

    def _step(self, s):
        wanted, reason = self._wanted(s)
        if self._level is None:
            self._level = wanted
            self._up_since = None
            return Decision(wanted, reason)
        cur, want = ORDER.index(self._level), ORDER.index(wanted)
        if want <= cur:  # same or lower: apply at once
            self._level = wanted
            self._up_since = None
            return Decision(wanted, reason)
        # A higher level is allowed: it must hold for a while, then one step.
        if self._up_since is None:
            self._up_since = s.t
        if s.t - self._up_since >= LIMITS["STEP_UP_AFTER"]:
            self._level = ORDER[cur + 1]
            self._up_since = s.t
            if self._level == wanted:
                self._up_since = None
                return Decision(wanted, reason)
        return Decision(self._level, _EASING[self._level])


HISTORY = 150            # samples kept for the live chart (5 minutes at one every 2 s)
SLOW_SENSE_EVERY = 15    # battery and call checks cost a registry walk


SESSION_GAP = 300        # seconds a game may stay out of the front (alt-tab) before its session is over


class _SafeApps:
    def __init__(self, apps):
        self._apps = apps

    def start_level(self, exe):
        try:
            return self._apps.start_level(exe)
        except Exception as e:
            log(f"app memory unavailable: {type(e).__name__}", "warn")
            return None

    def record_lag(self, exe, sample):
        try:
            self._apps.record_lag(exe, sample)
        except Exception as e:
            log(f"app memory unavailable: {type(e).__name__}", "warn")

    def quiet_session(self, exe):
        try:
            self._apps.quiet_session(exe)
        except Exception as e:
            log(f"app memory unavailable: {type(e).__name__}", "warn")


class Governor(threading.Thread):
    def __init__(self, settings, apps, activity, sense=None, every=2.0, jobs=None, watchdog=None,
                 release_idle=None, eco=None, release_models=None, plan=None, drives=None):
        super().__init__(daemon=True, name="governor")
        self.settings, self.activity = settings, activity
        self.apps = _SafeApps(apps)                 # a store error must never stop the governor
        self.brain = Brain(settings, self.apps)
        self.every = every
        self.jobs = _jobs if jobs is None else jobs
        self.watchdog = watchdog
        self.release_idle = release_idle            # models idle for a few minutes leave memory (window closed too)
        self.release_models = release_models        # high commit: every model out of memory now (indexer.release_models)
        self._plan = plan                           # the indexer's plan (threads per operation), for self.limits
        self._drives = drives                       # the drives the index is on, for the disk sensor
        self.decision = Decision(GENTLE, "Gentle: starting up")
        self.sample = None                          # the last Sample (talk and capability.assess read it)
        self.limits = op_limits(GENTLE, None, None, None, settings)     # per-operation concurrency, every tick
        self._history = deque(maxlen=HISTORY)
        self._stop_ev = threading.Event()
        self._applied = None
        self._session = {"exe": "", "seen": 0.0, "lagged": False}   # the current game session
        self._usage = {"cpu_seconds": 0.0, "memory_mb": 0}
        self._sense = sense or self._real_sense
        self._cpu, self._gpu = None, None
        self._disk = self._therm = self._gmem = None
        self._slow2 = (0.0, None, None)          # (checked at, battery saver, thermal)
        self._slow = (0.0, False, False)         # (checked at, on battery, in call)
        self._last_cpu_s = None                  # (wall time, Find's CPU seconds)
        self._eco = eco if eco is not None else (lambda on, pid, job=None: winapi.eco_qos(on, pid=pid, job=job))
        self._eco_set = {}                       # worker pid -> EcoQoS on/off as last applied
        self._now = threading.Event()            # Pause / Resume: decide again now
        self._last = None                        # the newest sample (busy_with)
        self._paused_since = None                # (since, reason) of a pause that isn't the user's own break
        self._pause_told = False                 # that pause was already worth a notification

    # ---------- control ----------
    def pause_for(self, seconds):
        self.brain.pause_until = time.time() + max(0, int(seconds))
        self.activity.add("info", f"You paused NOBAD Find for {int(seconds) // 60} min")
        self._now.set()                             # decide again at once, not at the next tick

    def now(self):
        """Settings changed how hard to work: decide again at once, not at the next tick."""
        self._now.set()

    def resume(self):
        self.brain.pause_until = 0.0
        self.activity.add("info", "You resumed NOBAD Find")
        self._now.set()

    def busy_with(self):
        """A game, a call or a presentation is on (the newest sample): notifications stay in the window then."""
        s = self._last
        return bool(s is not None and (s.game or s.call or s.presentation))

    def _long_pause(self, s, d):
        """A pause that isn't the user's own break and lasts LONG_PAUSE: one notification, so a PC that never
        gets indexed isn't silent about why."""
        if d.level != PAUSED or s.t < self.brain.pause_until:
            self._paused_since, self._pause_told = None, False
            return
        if self._paused_since is None:
            self._paused_since = s.t
        if self._pause_told or s.t - self._paused_since < notify.LONG_PAUSE:
            return
        self._pause_told = True
        why = d.reason.split(":", 1)[-1].strip() if d.reason.startswith("Paused:") else d.reason
        why = why[:1].upper() + why[1:]
        notify.post("indexing_paused_reason", f"Indexing has been paused for {notify.LONG_PAUSE // 60} minutes",
                    f"{why}. NOBAD Find goes on by itself when that ends; searching works meanwhile.", "info",
                    action="open_indexing", key="paused-long", every=3 * 3600)

    def stop(self):
        self._stop_ev.set()
        self._now.set()

    @property
    def history(self):
        return list(self._history)

    def run(self):
        while not self._stop_ev.is_set():
            try:
                self.tick()
            except Exception as e:                  # a sensor hiccup must never stop the governor
                log(f"governor tick failed: {type(e).__name__}", "warn")
            self._now.wait(self.every)              # a tick, or at once after Pause / Resume (0.9.1)
            self._now.clear()

    # ---------- one step ----------
    def tick(self):
        self._usage = self._read_usage()            # once per tick: find_cpu and find_mb share it
        s = self._sense()
        self.sample = s                             # the last reading (talk about a photo checks free memory)
        self._last = s                              # busy_with (notifications' quiet rule) reads it
        d = self.brain.decide(s)
        self._history.append({"t": s.t, "cpu": s.cpu, "gpu": s.gpu, "find_cpu": s.find_cpu,
                              "find_mb": self._usage["memory_mb"], "level": d.level})
        if d.level != self._applied:
            self._applied = d.level
            workers = getattr(self.jobs, "WORKERS", None)
            if workers is not None:
                workers.set_cpu_cap(CPU_CAP[d.level])
            self.activity.add("level", d.reason)
        self.decision = d
        try:
            self.limits = op_limits(d.level, self._plan() if self._plan is not None else None, s, d, self.settings)
        except Exception as e:
            log(f"governor could not work out the limits: {type(e).__name__}", "warn")
        if d.release_models:
            self._let_models_go(s)
        try:
            self._long_pause(s, d)
        except Exception as e:
            log(f"governor pause note failed: {type(e).__name__}", "warn")
        try:
            self._eco_workers(d.level)
        except Exception as e:
            log(f"governor could not set efficiency mode: {type(e).__name__}", "warn")
        try:
            self._track_session(s)
        except Exception as e:
            log(f"governor session tracking failed: {type(e).__name__}", "warn")
        try:
            if self.watchdog is not None:
                self.watchdog.check()
        except Exception as e:
            log(f"watchdog failed: {type(e).__name__}", "warn")
        try:
            if self.release_idle is not None:
                self.release_idle()
        except Exception as e:
            log(f"releasing idle models failed: {type(e).__name__}", "warn")
        return d

    def _let_models_go(self, s):
        """High commit: the models leave memory now (the watchdog's release path), once per episode."""
        if self.release_models is None:
            return
        try:
            self.release_models()
        except Exception as e:
            log(f"releasing models failed: {type(e).__name__}", "warn")
            return
        commit = f" ({round(s.commit_pct)}%)" if s.commit_pct is not None else ""
        self.activity.add("model", f"Windows is close to the memory it can promise programs{commit}, so NOBAD Find "
                                   "let go of its search models")

    def _eco_workers(self, level):
        """Efficiency mode (EcoQoS) for Find's worker processes at Light and Paused (a game, a call, a busy PC):
        Windows keeps them on efficiency cores at low clocks. Not at Gentle or Full, where indexing should keep its
        speed: in one test a reader ran 1.6x slower under EcoQoS (docs/measurements.md). Only pids still in the
        worker job, never this process; each set once per change."""
        workers = getattr(self.jobs, "WORKERS", None)
        if workers is None or not hasattr(workers, "pids"):
            return
        want, me = level in ECO_LEVELS, os.getpid()
        pids = [p for p in workers.pids() if p != me]
        self._eco_set = {p: v for p, v in self._eco_set.items() if p in pids}
        for pid in pids:
            if self._eco_set.get(pid) is not want and self._eco(want, pid, getattr(workers, "handle", None)):
                self._eco_set[pid] = want

    def _read_usage(self):
        outer = getattr(self.jobs, "OUTER", None)
        if outer is not None:
            try:
                return outer.usage()
            except Exception as e:
                log(f"governor could not read usage: {type(e).__name__}", "warn")
        return {"cpu_seconds": 0.0, "memory_mb": 0}

    def _track_session(self, s):
        """A game session ends when another game comes to the front, or when its exe has not been in
        front for SESSION_GAP seconds (alt-tab does not end it). A session without lag counts as quiet."""
        cur = self._session
        if cur["exe"]:
            if s.foreground == cur["exe"]:
                cur["seen"] = s.t
            elif (s.game and s.foreground) or s.t - cur["seen"] >= SESSION_GAP:
                if not cur["lagged"]:
                    self.apps.quiet_session(cur["exe"])
                cur["exe"] = ""
        if cur["exe"]:
            if s.foreground == cur["exe"] and self.brain._lag_recorded:
                cur["lagged"] = True
        elif s.game and s.foreground:
            cur.update(exe=s.foreground, seen=s.t, lagged=self.brain._lag_recorded)

    # ---------- real sensors ----------
    def _real_sense(self):
        if self._cpu is None:
            self._cpu, self._gpu = winapi.CpuSampler(), winapi.GpuSampler()
        now = time.time()
        if now - self._slow[0] >= SLOW_SENSE_EVERY:
            self._slow = (now, winapi.on_battery(), winapi.in_call())
        if self._disk is None:
            self._disk, self._therm = winapi.DiskSampler(), winapi.ThermalSampler()
            self._gmem = winapi.GpuMemorySampler()
        if now - self._slow2[0] >= SLOW_SENSE_EVERY:
            self._slow2 = (now, winapi.battery_saver(), self._therm.read())
        load, free = winapi.memory_status()
        commit, commit_free = winapi.commit_status()
        busy, ms = self._disk.read(self._drive_letters())
        return Sample(t=now, cpu=self._cpu.percent(), gpu=self._gpu.percent(), mem_load=load, free_mb=free,
                      find_cpu=self._find_cpu(now), foreground=winapi.foreground_exe(),
                      game=winapi.fullscreen_game(), presentation=winapi.presentation_mode(),
                      hung=winapi.foreground_hung(), battery=self._slow[1], call=self._slow[2],
                      idle_s=winapi.idle_seconds(), foreground_is_self=self._front_is_self(),
                      commit_pct=commit, commit_free_mb=commit_free, disk_busy=busy, disk_ms=ms,
                      battery_saver=self._slow2[1], thermal=self._slow2[2],
                      gpu_mem=_hw.gpu_memory_free(_hw.adapter_memory(), self._gmem.read()))

    def _drive_letters(self):
        try:
            return list(self._drives() or []) if self._drives is not None else []
        except Exception:
            return []

    @staticmethod
    def _front_is_self():
        hwnd = winapi.foreground_window()
        return bool(hwnd) and winapi.window_pid(hwnd) == os.getpid()

    def _find_cpu(self, now):
        secs = self._usage["cpu_seconds"]
        if not secs and getattr(self.jobs, "OUTER", None) is None:
            return 0.0
        last, self._last_cpu_s = self._last_cpu_s, (now, secs)
        if last is None or now <= last[0]:
            return 0.0
        return max(0.0, min(100.0, (secs - last[1]) / (now - last[0]) / (os.cpu_count() or 1) * 100))
