"""Candidate adapters for the vision benchmark (dev only, never shipped).

Every photo is decoded here (Pillow, size- and pixel-limited) and handed to a model already resized, so every
candidate sees the same picture and no model's own decoder touches the original file.

- Florence-2-base-ft: ONNX Runtime in this process (int8 files from onnx-community), greedy decoding.
- GGUF VLMs (SmolVLM2-500M, Qwen3-VL-2B, WeVisOne-VL-2B): llama.cpp's `llama-mtmd-cli.exe`, one run per item,
  argv list (no shell), stdin closed, no server mode and no port. Its stderr timing lines give the compute time
  without the model load.
- No Ollama anywhere.
"""
import os
import re
import shutil
import subprocess
import tempfile
import time

import numpy as np

MAX_BYTES = 50 * 1024 * 1024
MAX_PIXELS = 40_000_000
ITEM_TIMEOUT = 120

_LLM_PROMPTS = {
    "detect": "List every object you can see in this photo, comma-separated.",
    "ocr": "Write out all the text in this photo exactly as written.",
    "caption": "Describe this photo in detail.",
}
_FLORENCE_TASKS = {"detect": "<OD>", "ocr": "<OCR>", "caption": "<MORE_DETAILED_CAPTION>"}
# What Florence-2's processor turns each task token into (its own fixed prompts)
_FLORENCE_TEXT = {"<OD>": "Locate the objects with category name in the image.",
                  "<OCR>": "What is the text in the image?",
                  "<MORE_DETAILED_CAPTION>": "Describe with a paragraph what is shown in the image."}


class DecodeError(Exception):
    """The photo can't be used (empty, corrupt, too big)."""


class NotSupported(Exception):
    """This candidate can't do this task (Florence-2 doesn't answer free questions)."""


def prompt_for(task, question, candidate):
    if candidate.startswith("florence"):
        if task not in _FLORENCE_TASKS:
            raise NotSupported(f"{candidate} can't do {task}")
        return _FLORENCE_TASKS[task]
    if task == "ask":
        return f"{question} Answer briefly."
    if task == "compare":
        return f"The first image and the second image are two photos. {question} Answer briefly."
    return _LLM_PROMPTS[task]


def decode(path, max_side):
    """RGB Pillow image no larger than max_side on its long side; DecodeError on anything unusable."""
    from PIL import Image
    try:
        size = os.path.getsize(path)
    except OSError as e:
        raise DecodeError(f"can't read: {e}") from None
    if size == 0 or size > MAX_BYTES:
        raise DecodeError(f"file size {size} bytes is outside 1..{MAX_BYTES}")
    try:
        with Image.open(path) as im:
            w, h = im.size
            if w * h > MAX_PIXELS:
                raise DecodeError(f"{w}x{h} is more than {MAX_PIXELS} pixels")
            im.draft("RGB", (max_side, max_side))
            out = im.convert("RGB")
    except DecodeError:
        raise
    except Exception as e:
        raise DecodeError(f"not a readable image: {type(e).__name__}") from None
    out.thumbnail((max_side, max_side))
    if max(out.size) < max_side and max(w, h) >= max_side:
        out = out.resize((round(out.size[0] * max_side / max(out.size)), round(out.size[1] * max_side / max(out.size))))
    return out


# Named speed-ups, each measured on speed AND quality (--variant). Only what a variant names changes.
_SHORT = {"detect": 64, "ocr": 160, "caption": 160, "ask": 32, "compare": 24}
VARIANTS = {
    "base": {"about": "768 px (SmolVLM2: 512 px), 256 new tokens, llama.cpp defaults"},
    "res768": {"about": "768 px images, like Florence-2 (for a like-for-like comparison)", "max_side": 768},
    "short": {"about": "answer length per task", "max_tokens": _SHORT},
    "fewtok": {"about": "short + at most 256 image tokens", "max_tokens": _SHORT, "image_max_tokens": 256},
    "fast": {"about": "fewtok + flash attention + 8-bit KV cache", "max_tokens": _SHORT, "image_max_tokens": 256,
             "flags": ["-fa", "on", "-ctk", "q8_0", "-ctv", "q8_0"]},
    "fastest": {"about": "fast with at most 160 image tokens and 512 px", "max_side": 512, "max_tokens": _SHORT,
                "image_max_tokens": 160, "flags": ["-fa", "on", "-ctk", "q8_0", "-ctv", "q8_0"]},
}


def llama_argv(build_dir, model, mmproj, images, prompt, gpu, threads=None, max_tokens=256, variant=None,
               task=None):
    v = variant or {}
    max_tokens = v.get("max_tokens", {}).get(task, max_tokens)
    argv = [os.path.join(build_dir, "llama-mtmd-cli.exe"), "-m", model, "--mmproj", mmproj]
    for im in images:
        argv += ["--image", im]
    # -v: b12602 prints its timing ("llama_perf_context_print") and device ("using device ...") lines only then
    argv += ["-p", prompt, "--temp", "0", "-n", str(max_tokens), "-c", "4096", "-ngl", "99" if gpu else "0", "-v"]
    if v.get("image_max_tokens"):
        argv += ["--image-max-tokens", str(v["image_max_tokens"])]
    argv += list(v.get("flags", []))
    if threads:
        argv += ["-t", str(threads)]
    return argv


_MS = {"load": re.compile(r"llama_perf_context_print:\s+load time\s*=\s*([\d.]+)\s*ms"),
       "total": re.compile(r"llama_perf_context_print:\s+total time\s*=\s*([\d.]+)\s*ms")}
_GPU_DEVICE = re.compile(r"using device ((?:Vulkan|CUDA)\d+)\s*\(([^)]*)\)")


class GpuNotUsed(Exception):
    """A GPU device was asked for, but the work ran on the CPU (the run is "not available", never a GPU number)."""


def parse_llama_ms(stderr):
    """Compute time of one llama-mtmd-cli run without the model load: llama.cpp's "total time" counts from the
    start of loading, so it's total - load (image encode, decode and generation are inside both). None when the
    timing lines aren't there (the caller then uses wall time)."""
    total, load = _MS["total"].findall(stderr), _MS["load"].findall(stderr)
    if not total:
        return None
    return float(total[-1]) - (float(load[-1]) if load else 0.0)


def check_offload(stderr):
    """The GPU llama.cpp used, e.g. "Vulkan0 (Intel(R) Iris(R) Xe Graphics)"; GpuNotUsed when it named none. Its
    "offloaded N/N layers to GPU" line proves nothing: b12602's CPU-only build prints it too."""
    m = _GPU_DEVICE.findall(stderr)
    if not m:
        raise GpuNotUsed("llama.cpp ran on the CPU: it reported no GPU device in use")
    return f"{m[-1][0]} ({m[-1][1]})"


def scratch_dir():
    """A temp folder for resized photo copies, under VBENCH_TMP when the parent set one (it deletes that tree
    even if this process is killed)."""
    base = os.environ.get("VBENCH_TMP")
    if base:
        os.makedirs(base, exist_ok=True)
    return tempfile.mkdtemp(prefix="vbench-", dir=base or None)


def merge_cache(past, new):
    """The decoder's cache for the next step. On the cached branch the merged graph returns EMPTY encoder caches
    (shape (0, 12, 1, 64) with onnx-community's export); the encoder's keys/values never change, so the ones from
    the first step are kept."""
    if past is None:
        return new
    out = dict(new)
    for k, v in past.items():
        if ".encoder." in k and (out.get(k) is None or out[k].size == 0):
            out[k] = v
    return out


class Adapter:
    """load(models_dir, device) once, run(...) per item -> answer text, close()."""
    candidate = ""
    last_ms = None          # compute ms of the last run (None: use wall time)

    def load(self, models_dir, device):
        raise NotImplementedError

    def run(self, task, image, image2, question):
        raise NotImplementedError

    def close(self):
        pass


class LlamaAdapter(Adapter):
    model_file = mmproj_file = ""
    max_side = 768

    def __init__(self, tools_dir=None, variant=None):
        self.tools_dir = tools_dir
        self.variant = VARIANTS.get(variant or "base", VARIANTS["base"])

    def load(self, models_dir, device):
        self.dir = os.path.join(models_dir, self.candidate)
        self.build = os.path.join(self.tools_dir or "", f"llama-{device}")
        self.gpu = device != "cpu"
        self.tmp = scratch_dir()

    def run(self, task, image, image2, question):
        paths = []
        side = self.variant.get("max_side", self.max_side)
        for i, p in enumerate([image] + ([image2] if image2 else [])):
            q = os.path.join(self.tmp, f"in{i}.png")
            decode(p, side).save(q)
            paths.append(q)
        argv = llama_argv(self.build, os.path.join(self.dir, self.model_file), os.path.join(self.dir, self.mmproj_file),
                          paths, prompt_for(task, question, self.candidate), self.gpu, variant=self.variant, task=task)
        r = subprocess.run(argv, stdin=subprocess.DEVNULL, capture_output=True, timeout=ITEM_TIMEOUT,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        err = r.stderr.decode("utf-8", "replace")
        if r.returncode != 0:
            raise RuntimeError(f"llama-mtmd-cli exit {r.returncode}: {err[-300:]}")
        if self.gpu:
            check_offload(err)
        self.last_ms = parse_llama_ms(err)
        for q in paths:
            os.remove(q)
        return r.stdout.decode("utf-8", "replace").strip()

    def close(self):
        shutil.rmtree(getattr(self, "tmp", ""), ignore_errors=True)


class SmolVLM2(LlamaAdapter):
    candidate = "smolvlm2-500m"
    model_file, mmproj_file = "SmolVLM2-500M-Video-Instruct-Q8_0.gguf", "mmproj-SmolVLM2-500M-Video-Instruct-Q8_0.gguf"
    max_side = 512


class Qwen3VL2B(LlamaAdapter):
    candidate = "qwen3vl-2b-q4"
    model_file, mmproj_file = "Qwen3VL-2B-Instruct-Q4_K_M.gguf", "mmproj-Qwen3VL-2B-Instruct-Q8_0.gguf"


class WeVisOne2B(LlamaAdapter):
    candidate = "wevisone-vl-2b"
    model_file, mmproj_file = "WeVisOne-VL-2B.Q4_K_M.gguf", "WeVisOne-VL-2B.mmproj-Q8_0.gguf"


class Florence2(Adapter):
    """Florence-2-base-ft as four ONNX graphs: vision encoder -> (image features + prompt embeddings) -> encoder ->
    greedy decoder with its cache. Inputs are found by name, so a re-export with other cache names still runs."""
    candidate = "florence2-base-ft"
    SIZE = 768
    MEAN, STD = np.array([0.485, 0.456, 0.406], np.float32), np.array([0.229, 0.224, 0.225], np.float32)

    def __init__(self, tools_dir=None, variant=None):
        pass

    @staticmethod
    def graphs(device):
        """The graphs for a device: int8 on CPU (one merged decoder); fp16 on a GPU, where the int8 graphs' dynamic
        quantization ops would fall back to the CPU while the session still reports the GPU. onnx-community's fp16
        MERGED decoder is an invalid graph for ONNX Runtime ("Subgraph output (logits) is an outer scope value"), so
        a GPU uses the two plain decoders: the first step, then the steps with the cache."""
        if device == "cpu":
            return [f"{g}_int8.onnx" for g in ("vision_encoder", "encoder_model", "decoder_model_merged",
                                               "embed_tokens")]
        return [f"{g}_fp16.onnx" for g in ("vision_encoder", "encoder_model", "decoder_model",
                                           "decoder_with_past_model", "embed_tokens")]

    def _arr(self, sess, name, a):
        """a in the dtype the session's input wants (fp16 graphs take float16)."""
        t = next(i.type for i in sess.get_inputs() if i.name == name)
        return a.astype(np.float16) if t == "tensor(float16)" else a.astype(np.float32) if t == "tensor(float)" else a

    def load(self, models_dir, device):
        import onnxruntime as ort
        from tokenizers import Tokenizer
        d = os.path.join(models_dir, self.candidate)
        prov = {"cpu": ["CPUExecutionProvider"], "directml": ["DmlExecutionProvider", "CPUExecutionProvider"],
                "cuda": ["CUDAExecutionProvider", "CPUExecutionProvider"]}[device]
        so = ort.SessionOptions()
        so.log_severity_level = 3
        if device == "directml":          # what ONNX Runtime asks for with DirectML
            so.enable_mem_pattern = False
            so.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
        mk = lambda n: ort.InferenceSession(os.path.join(d, "onnx", n), so, providers=prov)  # noqa: E731
        g = {n.rsplit("_", 1)[0]: mk(n) for n in self.graphs(device)}
        self.vis, self.enc, self.emb = g["vision_encoder"], g["encoder_model"], g["embed_tokens"]
        self.dec = g.get("decoder_model_merged") or g["decoder_model"]
        self.dec_past = g.get("decoder_with_past_model")       # None: the merged decoder does both
        if device != "cpu" and any(s.get_providers()[0] == "CPUExecutionProvider" for s in g.values()):
            raise GpuNotUsed(f"ONNX Runtime didn't use the {device} provider")
        self.tok = Tokenizer.from_file(os.path.join(d, "tokenizer.json"))
        self.bos, self.eos = self.tok.token_to_id("<s>"), self.tok.token_to_id("</s>")

    def _pixels(self, path):
        im = decode(path, self.SIZE).resize((self.SIZE, self.SIZE))
        a = (np.asarray(im, np.float32) / 255.0 - self.MEAN) / self.STD
        return a.transpose(2, 0, 1)[None].astype(np.float32)

    def _embed(self, ids):
        return self.emb.run(None, {self.emb.get_inputs()[0].name: np.array([ids], np.int64)})[0]

    def run(self, task, image, image2, question):
        prompt = _FLORENCE_TEXT[prompt_for(task, question, self.candidate)]
        t0 = time.perf_counter()
        vin = self.vis.get_inputs()[0].name
        feats = self.vis.run(None, {vin: self._arr(self.vis, vin, self._pixels(image))})[0]
        ids = self.tok.encode(prompt).ids
        x = np.concatenate([feats, self._embed(ids)], axis=1)
        mask = np.ones(x.shape[:2], np.int64)
        hidden = self.enc.run(None, {"inputs_embeds": self._arr(self.enc, "inputs_embeds", x),
                                     "attention_mask": mask})[0]
        out_ids, past = [self.eos], None   # Florence-2 (BART) starts decoding from </s>
        for _ in range(256):
            dec = self.dec_past if (self.dec_past is not None and past is not None) else self.dec
            names = [i.name for i in dec.get_inputs()]
            feed = {"inputs_embeds": self._arr(dec, "inputs_embeds", self._embed([out_ids[-1]])),
                    "encoder_attention_mask": mask}
            if "encoder_hidden_states" in names:
                feed["encoder_hidden_states"] = hidden
            if "use_cache_branch" in names:
                feed["use_cache_branch"] = np.array([past is not None])
            for i in dec.get_inputs():
                if i.name.startswith("past_key_values"):
                    if past is not None:
                        feed[i.name] = past[i.name]
                    else:   # first step: empty caches (use_cache_branch False computes them)
                        feed[i.name] = self._arr(dec, i.name,
                                                 np.zeros((1, i.shape[1], 0, i.shape[3]), np.float32))
            outs = dec.run(None, feed)
            onames = [o.name for o in dec.get_outputs()]
            nxt = int(outs[onames.index("logits")][0, -1].argmax())
            if nxt == self.eos:
                break
            out_ids.append(nxt)
            past = merge_cache(past, {n.replace("present", "past_key_values"): v
                                      for n, v in zip(onames, outs) if n.startswith("present")})
        self.last_ms = (time.perf_counter() - t0) * 1000
        text = self.tok.decode(out_ids[1:], skip_special_tokens=False)
        return re.sub(r"<loc_\d+>|</?s>|<pad>", " ", text).strip()


ADAPTERS = {a.candidate: a for a in (Florence2, SmolVLM2, Qwen3VL2B, WeVisOne2B)}
