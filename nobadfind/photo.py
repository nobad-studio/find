"""Photo meaning: find photos by what's in them ("dog on a beach"), even when their name and text say nothing.

A local image-text model, SigLIP base (Google, Apache-2.0; ONNX export by Xenova, 8-bit), turns each photo and
each question into vectors in the same space. The model (about 211 MB) is downloaded only when the user allows it
(setting allow_photo_model_download), from one pinned revision, every file checked by size and SHA-256.

Photos are untrusted: they're decoded by Windows' own image decoders (the ones Explorer uses for thumbnails) in a
separate low-priority worker process, never opened in another program, and size-limited. Only the 224 x 224
picture the model needs is ever made.
"""
import os
import re
import threading

import numpy as np

from .const import DATA_DIR

PHOTO_DIR = os.path.join(DATA_DIR, "photo-model")
PHOTO_REV = "4649052661e53c7000355844105f8a1792088239"
PHOTO_URL = "https://huggingface.co/Xenova/siglip-base-patch16-224/resolve/{rev}/{path}"
PHOTO_FILES = {   # local name: (path in the repository, size in bytes, SHA-256)
    "vision.onnx": ("onnx/vision_model_quantized.onnx", 99499129,
                    "ef14a954f3d57e1806666432bd9785004c1dc27100aa260eee0cb0f10a5de058"),
    "text.onnx": ("onnx/text_model_quantized.onnx", 111475220,
                  "ad0329b1f35acc66d8953ff2559ce358da8eb0a7011794cf951523d63a4dbce2"),
    "tokenizer.json": ("tokenizer.json", 2398744,
                       "4a17c975210be5ab4c36b47d8dae4eefb866dbfb1e676e394aad85dc30a3ae08"),
}
PHOTO_DIM = 768
SIDE = 224
TEXT_LEN = 64
EOS = 1                                   # "</s>": SigLIP pads with it too
OUT_OF_MEMORY = "out of memory"           # the worker job's limit: read again (as extract.OUT_OF_MEMORY)
MAX_PHOTO_BYTES = 60 * 1024 * 1024
MIN_PHOTO_BYTES = 12 * 1024               # smaller files are icons, buttons and thumbnails
MAX_PIXELS = 80_000_000                   # a small file may claim a huge picture: not decoded
PHOTO_EXT = {".jpg", ".jpeg", ".png", ".webp", ".heic", ".heif", ".bmp", ".tif", ".tiff", ".gif"}


def model_ready(model_dir=PHOTO_DIR):
    for name, (_path, size, _sha) in PHOTO_FILES.items():
        p = os.path.join(model_dir, name)
        if not os.path.isfile(p) or os.path.getsize(p) != size:
            return False
    return True


def download_model(model_dir=PHOTO_DIR, progress=None):
    """Same checks as the text model (embed.download_model): HTTPS only, exact size, SHA-256 before use."""
    from .embed import _fetch_verified
    os.makedirs(model_dir, exist_ok=True)
    for name, (path, size, sha) in PHOTO_FILES.items():
        _fetch_verified(PHOTO_URL.format(rev=PHOTO_REV, path=path), os.path.join(model_dir, name), size, sha,
                        name, progress)


# ---------- images (in the worker process) ----------
def _open_decoder(data):
    """Windows' decoder for encoded image bytes -> (decoder, oriented width, oriented height), or None when the
    picture is too small or too large to use (short side under 64, or more than MAX_PIXELS)."""
    from winrt.windows.graphics.imaging import BitmapDecoder
    from winrt.windows.storage.streams import DataWriter, InMemoryRandomAccessStream
    stream = InMemoryRandomAccessStream()
    w = DataWriter(stream)
    w.write_bytes(data)
    w.store_async().get()
    w.flush_async().get()
    w.detach_stream()
    stream.seek(0)
    dec = BitmapDecoder.create_async(stream).get()
    width, height = dec.oriented_pixel_width, dec.oriented_pixel_height
    if min(width, height) < 64 or width * height > MAX_PIXELS:
        return None
    return dec, width, height


def _scaled_rgba(dec, width, height):
    """The decoder's picture scaled to width x height (FANT), RGBA8, upright, sRGB, as bytes."""
    from winrt.windows.graphics.imaging import (BitmapAlphaMode, BitmapInterpolationMode, BitmapPixelFormat,
                                                 BitmapTransform, ColorManagementMode, ExifOrientationMode)
    t = BitmapTransform()
    t.scaled_width, t.scaled_height = width, height
    t.interpolation_mode = BitmapInterpolationMode.FANT
    px = dec.get_pixel_data_transformed_async(BitmapPixelFormat.RGBA8, BitmapAlphaMode.IGNORE, t,
                                              ExifOrientationMode.RESPECT_EXIF_ORIENTATION,
                                              ColorManagementMode.COLOR_MANAGE_TO_S_RGB).get()
    return bytes(px.detach_pixel_data())


def decode_224(data):
    """Encoded image bytes -> float32 (3, 224, 224) in the model's range, or None if it isn't a usable photo.
    Windows decodes and scales it (BitmapDecoder + BitmapTransform), turned the way the camera held it."""
    opened = _open_decoder(data)
    if opened is None:
        return None
    raw = np.frombuffer(_scaled_rgba(opened[0], SIDE, SIDE), np.uint8)   # SigLIP squeezes to 224 x 224 (no crop)
    if raw.size != SIDE * SIDE * 4:
        return None
    rgb = raw.reshape(SIDE, SIDE, 4)[:, :, :3].astype(np.float32)
    return ((rgb / 255.0 - 0.5) / 0.5).transpose(2, 0, 1)


def decode_rgb(data, side):
    """Encoded image bytes -> (RGB8 bytes, width, height) with the long side = side (aspect kept, never enlarged),
    upright and sRGB, or None if it isn't a usable photo (empty, too big a file, too small or too many pixels).
    For the picture-talking model; decoded by Windows like decode_224."""
    if not data or len(data) > MAX_PHOTO_BYTES or side < 1:
        return None
    try:
        opened = _open_decoder(data)
        if opened is None:
            return None
        dec, width, height = opened
        long_side = max(width, height)
        if long_side > side:
            width, height = max(1, round(width * side / long_side)), max(1, round(height * side / long_side))
        raw = np.frombuffer(_scaled_rgba(dec, width, height), np.uint8)
    except Exception:
        return None
    if raw.size != width * height * 4:
        return None
    return raw.reshape(-1, 4)[:, :3].tobytes(), width, height


_vision = {}                                          # model folder -> its vision session (one per model)
_threads = [2]                                        # set by init_worker from the level (indexer._photo_vectors)
QUESTION_THREADS = 4                                  # a photo question while you type: 45 ms on 2 threads, 28 on 4


def open_session(path, opts, providers=("CPUExecutionProvider",)):
    """An ONNX Runtime session. Some fp16 exports (SigLIP 2's vision, 2026-11-22) make ONNX Runtime 1.27's full
    graph optimizer fail in GetIndexFromName; those load with basic optimization, measured to give the right
    vectors (cosine 1.00000 against the fp32 export on 50 photos). Their memory arena is turned off: with basic
    optimization it grew to 1,275 MB over 20 photos, 207 MB without it (2.9 vs 3.4 photos/s). Any other load
    error is raised as it is."""
    import onnxruntime as ort
    try:
        return ort.InferenceSession(path, opts, providers=list(providers))
    except Exception as e:
        if "GetIndexFromName" not in str(e):
            raise
        opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_BASIC
        opts.enable_cpu_mem_arena = False
        return ort.InferenceSession(path, opts, providers=list(providers))


def _vision_session(model_dir):
    """The vision session of the model in model_dir (a model switch gets its own, never the old one)."""
    s = _vision.get(model_dir)
    if s is None:
        import onnxruntime as ort
        opts = ort.SessionOptions()
        opts.intra_op_num_threads = _threads[0]       # 2.4 photos/s on 2 threads, 7.1 on 8 (CPU-capped by level)
        opts.log_severity_level = 3
        _vision.clear()                               # one model in memory at a time
        s = _vision[model_dir] = open_session(os.path.join(model_dir, "vision.onnx"), opts)
    return s


def _unit(v):
    return v / np.maximum(np.linalg.norm(v, axis=-1, keepdims=True), 1e-9)


def embed_photo(job):
    """Worker entry: (file_id, path, mtime, model_dir) -> (file_id, mtime, float16 bytes or b"", error)."""
    file_id, path, mtime, model_dir = job
    try:
        if os.path.getsize(path) > MAX_PHOTO_BYTES:
            return file_id, mtime, b"", "too big"
        with open(path, "rb") as f:
            data = f.read(MAX_PHOTO_BYTES + 1)
        pixels = decode_224(data)
        if pixels is None:
            return file_id, mtime, b"", "not a photo"
        out = _vision_session(model_dir).run(["pooler_output"], {"pixel_values": pixels[None]})[0]
        return file_id, mtime, _unit(out[0]).astype(np.float16).tobytes(), None
    except MemoryError:
        return file_id, mtime, b"", OUT_OF_MEMORY
    except Exception as e:                            # one bad photo never stops the others
        return file_id, mtime, b"", f"unreadable ({type(e).__name__})"


_mode = [True]


def embed_photos(jobs, fast=False):
    """Worker entry for a batch: [(file_id, path, mtime, model_dir), ...] -> results like embed_photo.
    fast: you're away from the PC, so the worker runs at normal priority for this batch."""
    if fast == _mode[0]:
        from . import winapi
        winapi.worker_priority(not fast)
        _mode[0] = not fast
    return [embed_photo(j) for j in jobs]


def init_worker(threads=2):
    from . import jobs, winapi
    _threads[0] = max(1, int(threads))
    jobs.join_workers()            # into Find's worker group (CPU-capped, ends with the app)
    winapi.worker_priority()
    # winrt carries an older C++ runtime; onnxruntime must be loaded first (see ocr._load)
    import importlib
    importlib.import_module("onnxruntime")


# ---------- questions (in the app) ----------
_CANON = re.compile(r"[^\w\s]", re.UNICODE)


PAD2 = 0                                  # SigLIP 2 (Gemma tokenizer): <pad>; <eos> is 1 there too
# How a question is asked of the photo model: the bare words and caption-like phrasings, averaged (encode_question).
QUESTION_TEMPLATES = ("{}", "a photo of {}", "a picture of {}", "a close-up photo of {}")


def question_ids(tok, text, style="siglip"):
    """TEXT_LEN token ids for a question. SigLIP learned from lower-case text without punctuation, padded with
    </s>; SigLIP 2 from lower-case text ending in <eos>, padded with <pad> (its tokenizer.json adds both)."""
    if style == "siglip2":
        ids = list(tok.encode(text.lower()).ids)[:TEXT_LEN]
        if EOS not in ids:
            ids[-1:] = [EOS]
        return ids + [PAD2] * (TEXT_LEN - len(ids))
    clean = " ".join(_CANON.sub(" ", text.lower()).split())
    ids = tok.encode(clean).ids[:TEXT_LEN]
    if ids and ids[-1] != EOS:
        ids[-1] = EOS
    return ids + [EOS] * (TEXT_LEN - len(ids))


class TextEncoder:
    """The text half of SigLIP / SigLIP 2: a question -> a vector comparable with that model's photo vectors."""

    def __init__(self, model_dir=PHOTO_DIR, threads=None, style="siglip"):
        if not os.path.isfile(os.path.join(model_dir, "text.onnx")):
            raise RuntimeError("photo model not downloaded")
        self.style = style
        import onnxruntime as ort
        from tokenizers import Tokenizer
        self.tok = Tokenizer.from_file(os.path.join(model_dir, "tokenizer.json"))
        opts = ort.SessionOptions()
        opts.intra_op_num_threads = threads or QUESTION_THREADS
        opts.log_severity_level = 3
        self.sess = open_session(os.path.join(model_dir, "text.onnx"), opts)
        self._lock = threading.Lock()
        self._asked = {}

    def encode(self, text):
        ids = question_ids(self.tok, text, self.style)
        with self._lock:
            out = self.sess.run(["pooler_output"], {"input_ids": np.array([ids], np.int64)})[0]
        return _unit(out[0]).astype(np.float32)

    def encode_question(self, text):
        """A search question as captions (QUESTION_TEMPLATES), their vectors averaged: closer to how the model
        learned what pictures show than the bare words. Cached per question, so typing doesn't redo it."""
        key = " ".join(text.lower().split())
        hit = self._asked.get(key)
        if hit is not None:
            return hit
        v = _unit(np.mean([self.encode(t.format(key)) for t in QUESTION_TEMPLATES], axis=0)).astype(np.float32)
        if len(self._asked) >= 64:
            self._asked.pop(next(iter(self._asked)))
        self._asked[key] = v
        return v
