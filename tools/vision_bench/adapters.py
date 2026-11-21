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


def llama_argv(build_dir, model, mmproj, images, prompt, gpu, threads=None, max_tokens=256):
    argv = [os.path.join(build_dir, "llama-mtmd-cli.exe"), "-m", model, "--mmproj", mmproj]
    for im in images:
        argv += ["--image", im]
    argv += ["-p", prompt, "--temp", "0", "-n", str(max_tokens), "-c", "4096", "-ngl", "99" if gpu else "0"]
    if threads:
        argv += ["-t", str(threads)]
    return argv


_MS = {"enc": re.compile(r"image slice encoded in\s+([\d.]+)\s*ms"),
       "dec": re.compile(r"image decoded.*?in\s+([\d.]+)\s*ms"),
       "total": re.compile(r"llama_perf_context_print:\s+total time\s*=\s*([\d.]+)\s*ms")}


def parse_llama_ms(stderr):
    """Compute time of one llama-mtmd-cli run (image encode + decode + generation), without the model load; None
    when the timing lines aren't there."""
    total = _MS["total"].findall(stderr)
    if not total:
        return None
    return (sum(float(x) for x in _MS["enc"].findall(stderr)) + sum(float(x) for x in _MS["dec"].findall(stderr))
            + float(total[-1]))


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

    def __init__(self, tools_dir=None):
        self.tools_dir = tools_dir

    def load(self, models_dir, device):
        self.dir = os.path.join(models_dir, self.candidate)
        self.build = os.path.join(self.tools_dir or "", f"llama-{device}")
        self.gpu = device != "cpu"
        self.tmp = tempfile.mkdtemp(prefix="vbench-")

    def run(self, task, image, image2, question):
        paths = []
        for i, p in enumerate([image] + ([image2] if image2 else [])):
            q = os.path.join(self.tmp, f"in{i}.png")
            decode(p, self.max_side).save(q)
            paths.append(q)
        argv = llama_argv(self.build, os.path.join(self.dir, self.model_file), os.path.join(self.dir, self.mmproj_file),
                          paths, prompt_for(task, question, self.candidate), self.gpu)
        r = subprocess.run(argv, stdin=subprocess.DEVNULL, capture_output=True, timeout=ITEM_TIMEOUT,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        err = r.stderr.decode("utf-8", "replace")
        if r.returncode != 0:
            raise RuntimeError(f"llama-mtmd-cli exit {r.returncode}: {err[-300:]}")
        self.last_ms = parse_llama_ms(err)
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

    def __init__(self, tools_dir=None):
        pass

    def load(self, models_dir, device):
        import onnxruntime as ort
        from tokenizers import Tokenizer
        d = os.path.join(models_dir, self.candidate)
        prov = {"cpu": ["CPUExecutionProvider"], "directml": ["DmlExecutionProvider", "CPUExecutionProvider"],
                "cuda": ["CUDAExecutionProvider", "CPUExecutionProvider"]}[device]
        so = ort.SessionOptions()
        so.log_severity_level = 3
        mk = lambda n: ort.InferenceSession(os.path.join(d, "onnx", n), so, providers=prov)  # noqa: E731
        self.vis, self.enc = mk("vision_encoder_int8.onnx"), mk("encoder_model_int8.onnx")
        self.dec, self.emb = mk("decoder_model_merged_int8.onnx"), mk("embed_tokens_int8.onnx")
        if device != "cpu" and self.vis.get_providers()[0] == "CPUExecutionProvider":
            raise RuntimeError(f"{device} provider not used by ONNX Runtime")
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
        feats = self.vis.run(None, {self.vis.get_inputs()[0].name: self._pixels(image)})[0]
        ids = self.tok.encode(prompt).ids
        x = np.concatenate([feats, self._embed(ids)], axis=1)
        mask = np.ones(x.shape[:2], np.int64)
        hidden = self.enc.run(None, {"inputs_embeds": x, "attention_mask": mask})[0]
        out_ids, past = [self.eos], None   # Florence-2 (BART) starts decoding from </s>
        names = [i.name for i in self.dec.get_inputs()]
        for _ in range(256):
            feed = {"inputs_embeds": self._embed([out_ids[-1]]), "encoder_attention_mask": mask}
            if "encoder_hidden_states" in names:
                feed["encoder_hidden_states"] = hidden
            if "use_cache_branch" in names:
                feed["use_cache_branch"] = np.array([past is not None])
            for i in self.dec.get_inputs():
                if i.name.startswith("past_key_values"):
                    if past is not None:
                        feed[i.name] = past[i.name]
                    else:   # first step: empty caches (use_cache_branch False computes them)
                        feed[i.name] = np.zeros((1, i.shape[1], 0, i.shape[3]), np.float32)
            outs = self.dec.run(None, feed)
            onames = [o.name for o in self.dec.get_outputs()]
            nxt = int(outs[0][0, -1].argmax())
            if nxt == self.eos:
                break
            out_ids.append(nxt)
            new = {n.replace("present", "past_key_values"): v for n, v in zip(onames[1:], outs[1:])}
            if past is not None:   # the merged graph returns empty encoder caches on the cached branch: keep ours
                for k, v in past.items():
                    if ".encoder." in k and new.get(k) is not None and new[k].shape[2] == 0:
                        new[k] = v
            past = new
        self.last_ms = (time.perf_counter() - t0) * 1000
        text = self.tok.decode(out_ids[1:], skip_special_tokens=False)
        return re.sub(r"<loc_\d+>|</?s>|<pad>", " ", text).strip()


ADAPTERS = {a.candidate: a for a in (Florence2, SmolVLM2, Qwen3VL2B, WeVisOne2B)}
