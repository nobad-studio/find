"""Dev check: do the ctypes structs in nobadfind/vlm/llama_api.py match llama.cpp b12602's headers?

    python tools/vlm_header_check.py <headers dir>

The folder holds llama.h, mtmd.h, mtmd-helper.h (and, for the optional C build, ggml.h, ggml-backend.h,
ggml-cpu.h, ggml-opt.h, gguf.h) from tag b12602; never commit them. For each struct the header's fields are parsed
(names, order, C types) and compared with the ctypes `_fields_`; a second ctypes struct is built from the HEADER's
types alone and its sizeof/offsets are compared with llama_api's. When a C compiler (cl, clang or gcc) is on PATH, a
tiny C program built against the headers prints the real sizeof/offsetof and those are compared too.
Exit code 0 when everything matches.
"""
import ctypes
import os
import re
import shutil
import subprocess
import sys
import tempfile
from collections import namedtuple

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from nobadfind.vlm import llama_api as L  # noqa: E402

STRUCTS = [
    (L.ModelParams, "llama.h", "llama_model_params"),
    (L.ContextParams, "llama.h", "llama_context_params"),
    (L.SamplerChainParams, "llama.h", "llama_sampler_chain_params"),
    (L.Batch, "llama.h", "llama_batch"),
    (L.MtmdContextParams, "mtmd.h", "mtmd_context_params"),
    (L.MtmdInputText, "mtmd.h", "mtmd_input_text"),
    (L.ChatMessage, "llama.h", "llama_chat_message"),
]

# functions whose argument list is checked against the header (find 1.1: the log callbacks the talk worker sets)
FUNCS = [
    ("llama.h", "llama_log_set", L.LLAMA_FUNCS),
    ("mtmd.h", "mtmd_log_set", L.MTMD_FUNCS),
    ("mtmd-helper.h", "mtmd_helper_log_set", L.MTMD_FUNCS),
]

Field = namedtuple("Field", "name ctype line")


class StructFields(list):
    """The parsed fields, plus `.line`: where `struct name {` is in the header."""
    def __init__(self, fields, line):
        super().__init__(fields)
        self.line = line

PTR = ("ptr", ctypes.sizeof(ctypes.c_void_p))
SCALARS = {
    "bool": ("bool", 1), "float": ("float", 4),
    "int": ("int", 4, True), "int32_t": ("int", 4, True), "uint32_t": ("int", 4, False),
    "int64_t": ("int", 8, True), "uint64_t": ("int", 8, False), "double": ("float", 8),
    "int8_t": ("int", 1, True),"size_t": ("int", ctypes.sizeof(ctypes.c_size_t), False),
    "llama_token": ("int", 4, True), "llama_pos": ("int", 4, True), "llama_seq_id": ("int", 4, True),
}
POINTER_TYPEDEFS = {"ggml_backend_dev_t", "llama_progress_callback", "ggml_backend_sched_eval_callback",
                    "ggml_abort_callback", "mtmd_progress_callback", "ggml_log_callback"}


def _strip_comments(text):
    text = re.sub(r"/\*.*?\*/", lambda m: re.sub(r"[^\n]", " ", m.group()), text, flags=re.S)
    return re.sub(r"//[^\n]*", "", text)


def parse_struct(path, cname):
    """The fields of `struct cname { ... }` in the header at `path`, in order."""
    with open(path, encoding="utf-8") as f:
        text = _strip_comments(f.read())
    m = re.search(r"\bstruct\s+" + re.escape(cname) + r"\s*\{", text)
    if not m:
        raise ValueError(f"struct {cname} not found in {path}")
    struct_line = text.count("\n", 0, m.start()) + 1
    body_start = m.end()
    end = text.index("}", body_start)
    fields = []
    pos = body_start
    for stmt in text[body_start:end].split(";"):
        line = text.count("\n", 0, pos + len(stmt) - len(stmt.lstrip())) + 1
        pos += len(stmt) + 1
        stmt = " ".join(stmt.split())
        if not stmt:
            continue
        if "," in stmt or "[" in stmt or "(" in stmt:
            raise ValueError(f"{cname}: unsupported declaration {stmt!r}")
        m2 = re.fullmatch(r"(.*?)([A-Za-z_]\w*)", stmt)
        fields.append(Field(m2.group(2), " ".join(m2.group(1).replace("*", " * ").split()), line))
    return StructFields(fields, struct_line)


def parse_func(path, name):
    """(return C type, [argument C types], line) of the declaration `... name(args);` in the header at `path`."""
    with open(path, encoding="utf-8") as f:
        text = _strip_comments(f.read())
    m = re.search(r"([A-Za-z_][\w\s\*]*?)\b" + re.escape(name) + r"\s*\(([^)]*)\)\s*;", text)
    if not m:
        raise ValueError(f"function {name} not found in {path}")
    ret = " ".join(w for w in m.group(1).replace("*", " * ").split() if not w.endswith("_API"))
    args = []
    for a in m.group(2).split(","):
        a = " ".join(a.replace("*", " * ").split())
        if not a or a == "void":
            continue
        m2 = re.fullmatch(r"(.*?)\s*([A-Za-z_]\w*)", a)
        typ = m2.group(1) if m2 and m2.group(1) and m2.group(1) not in ("const", "struct", "enum") else a
        args.append(typ)
    return ret, args, text.count("\n", 0, m.start()) + 1


def _ctypes_kind(t):
    """kind_of_ctypes, with a ctypes function-pointer type counted as a pointer."""
    if isinstance(t, type) and issubclass(t, ctypes._CFuncPtr):
        return PTR
    return kind_of_ctypes(t)


def check_funcs(headers):
    """Mismatches between FUNCS' ctypes argtypes / restype and the header's declarations."""
    problems = []
    for header, name, table in FUNCS:
        ret, args, line = parse_func(os.path.join(headers, header), name)
        restype, argtypes = table[name]
        if len(args) != len(argtypes):
            problems.append(f"{name}: {len(argtypes)} ctypes args != header {len(args)} (line {line})")
            continue
        for i, (c, t) in enumerate(zip(args, argtypes)):
            if kind_of_c(c) != _ctypes_kind(t):
                problems.append(f"{name} arg {i}: ctypes {t.__name__} != header {c!r} (line {line})")
        if (ret == "void") != (restype is None):
            problems.append(f"{name}: returns {ret!r} in the header, ctypes {restype}")
    return problems


def kind_of_c(ctype):
    if "*" in ctype:
        return PTR
    words = [w for w in ctype.split() if w != "const"]
    if words[0] == "enum":
        return ("int", 4, True)                         # MSVC: enums are int
    if words[0] == "struct":
        raise ValueError(f"struct by value inside a struct: {ctype}")
    (word,) = words
    if word in POINTER_TYPEDEFS:
        return PTR
    return SCALARS[word]


def kind_of_ctypes(t):
    size = ctypes.sizeof(t)
    if t in (ctypes.c_void_p, ctypes.c_char_p) or issubclass(t, ctypes._Pointer):
        return ("ptr", size)
    if t is ctypes.c_bool:
        return ("bool", size)
    if t in (ctypes.c_float, ctypes.c_double):
        return ("float", size)
    return ("int", size, t(-1).value < 0)


_FROM_KIND = {("bool", 1): ctypes.c_bool, ("float", 4): ctypes.c_float, PTR: ctypes.c_void_p,
              ("int", 1, True): ctypes.c_int8, ("int", 4, True): ctypes.c_int32,
              ("int", 4, False): ctypes.c_uint32, ("int", 8, False): ctypes.c_uint64}


def layout_from_header(fields):
    """A ctypes struct built only from the header's types (independent of llama_api)."""
    return type("FromHeader", (ctypes.Structure,), {"_fields_": [(f.name, _FROM_KIND[kind_of_c(f.ctype)])
                                                                  for f in fields]})


def _compiler_layouts(headers):
    """{struct: (sizeof, {field: offset})} from a real C build, or None when no compiler is found."""
    cc = next((c for c in ("cl", "clang", "gcc") if shutil.which(c)), None)
    if not cc:
        return None
    lines = ['#include <stdio.h>', '#include <stddef.h>', '#include "llama.h"', '#include "mtmd.h"',
             "int main(void) {"]
    for _, header, cname in STRUCTS:
        lines.append(f'printf("S {cname} %zu\\n", sizeof(struct {cname}));')
        for f in parse_struct(os.path.join(headers, header), cname):
            lines.append(f'printf("F {cname} {f.name} %zu\\n", offsetof(struct {cname}, {f.name}));')
    lines += ["return 0;", "}"]
    with tempfile.TemporaryDirectory() as tmp:
        src, exe = os.path.join(tmp, "layout.c"), os.path.join(tmp, "layout.exe")
        with open(src, "w") as f:
            f.write("\n".join(lines))
        cmd = ([cc, "/nologo", f"/I{headers}", src, f"/Fe{exe}", f"/Fo{tmp}{os.sep}"] if cc == "cl"
               else [cc, f"-I{headers}", src, "-o", exe])
        build = subprocess.run(cmd, capture_output=True, text=True, cwd=tmp)
        if build.returncode:
            print(f"C build with {cc} failed, using the header layout only:\n{build.stdout}{build.stderr}")
            return None
        out = subprocess.run([exe], capture_output=True, text=True, check=True).stdout
    layouts = {}
    for row in out.split("\n"):
        parts = row.split()
        if parts[:1] == ["S"]:
            layouts.setdefault(parts[1], [0, {}])[0] = int(parts[2])
        elif parts[:1] == ["F"]:
            layouts.setdefault(parts[1], [0, {}])[1][parts[2]] = int(parts[3])
    return layouts


def check(headers, verbose=False, use_compiler=False):
    """A list of mismatches (empty when every struct matches the headers)."""
    problems = []
    built = _compiler_layouts(headers) if use_compiler else None
    for cls, header, cname in STRUCTS:
        fields = parse_struct(os.path.join(headers, header), cname)
        ours = [n for n, _ in cls._fields_]
        theirs = [f.name for f in fields]
        if ours != theirs:
            problems.append(f"{cname}: fields {ours} != header {theirs}")
            continue
        hdr = layout_from_header(fields)
        c_size, c_offs = built.get(cname, (None, {})) if built else (None, {})
        if verbose:
            print(f"struct {cname} ({header}:{fields.line}): sizeof ctypes {ctypes.sizeof(cls)}, "
                  f"header {ctypes.sizeof(hdr)}" + (f", C {c_size}" if c_size is not None else ""))
        for f, (name, t) in zip(fields, cls._fields_):
            if kind_of_c(f.ctype) != kind_of_ctypes(t):
                problems.append(f"{cname}.{name}: ctypes {t.__name__} != header {f.ctype!r} (line {f.line})")
            off, hoff = getattr(cls, name).offset, getattr(hdr, name).offset
            if off != hoff or (name in c_offs and c_offs[name] != off):
                problems.append(f"{cname}.{name}: offset {off} != header {hoff} / C {c_offs.get(name)}")
            if verbose:
                print(f"  {off:4d} {hoff:4d} {c_offs.get(name, '')!s:>4} {name:<28} {f.ctype:<45} line {f.line}")
        if ctypes.sizeof(cls) != ctypes.sizeof(hdr) or (c_size is not None and c_size != ctypes.sizeof(cls)):
            problems.append(f"{cname}: sizeof {ctypes.sizeof(cls)} != header {ctypes.sizeof(hdr)} / C {c_size}")
    problems += check_funcs(headers)
    return problems


def main(argv):
    if len(argv) != 2:
        print(__doc__)
        return 2
    problems = check(argv[1], verbose=True, use_compiler=True)
    for p in problems:
        print("MISMATCH", p)
    print("OK: every struct and checked function matches" if not problems else f"{len(problems)} mismatch(es)")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
