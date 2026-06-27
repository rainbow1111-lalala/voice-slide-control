#!/usr/bin/env python3
"""
voice-slide-control · web control panel
========================================
A tiny local web UI to set up and run the voice slide controller:
  • showcases what the tool does
  • walks you through adding a cloud API key (Groq / OpenAI / custom), and tests it
  • or switches to the fully-offline local Vosk model
  • saves config.yaml + .env, then starts/stops the listener with a live log

Run:
    python app.py
    # open http://127.0.0.1:5001
"""

import io
import json
import os
import queue
import subprocess
import sys
import threading
import zipfile
from collections import deque
from pathlib import Path

import requests
import yaml
from flask import Flask, Response, jsonify, request, send_from_directory

ROOT = Path(__file__).parent.resolve()
CONFIG_PATH = ROOT / "config.web.yaml"
ENV_PATH = ROOT / ".env"
VOSK_CN_SMALL = ROOT / "models" / "vosk-model-small-cn-0.22"
VOSK_EN_SMALL = ROOT / "models" / "vosk-model-small-en-us-0.15"

# Downloadable offline models (not shipped in the repo — fetched on demand)
VOSK_MODELS = {
    "zh": ("vosk-model-small-cn-0.22",
           "https://alphacephei.com/vosk/models/vosk-model-small-cn-0.22.zip"),
    "en": ("vosk-model-small-en-us-0.15",
           "https://alphacephei.com/vosk/models/vosk-model-small-en-us-0.15.zip"),
}

PROVIDERS = {
    "groq": {
        "base_url": "https://api.groq.com/openai/v1",
        "model": "whisper-large-v3-turbo",
        "api_key_env": "GROQ_API_KEY",
        "signup": "https://console.groq.com/keys",
        "models": [
            {"id": "whisper-large-v3-turbo", "label": "whisper-large-v3-turbo · fast / 快"},
            {"id": "whisper-large-v3", "label": "whisper-large-v3 · accurate / 更准"},
        ],
    },
    "openai": {
        "base_url": "https://api.openai.com/v1",
        "model": "gpt-4o-transcribe",
        "api_key_env": "OPENAI_API_KEY",
        "signup": "https://platform.openai.com/api-keys",
        "models": [
            {"id": "gpt-4o-transcribe", "label": "gpt-4o-transcribe · most accurate / 最准"},
            {"id": "gpt-4o-mini-transcribe", "label": "gpt-4o-mini-transcribe · balanced / 均衡"},
            {"id": "whisper-1", "label": "whisper-1"},
        ],
    },
}

app = Flask(__name__)

# ── running process + live log fan-out ────────────────────────────────────
_proc = {"p": None}
_log = deque(maxlen=400)
_subscribers = []          # list[queue.Queue]
_lock = threading.Lock()


def _broadcast(line):
    _log.append(line)
    with _lock:
        for q in list(_subscribers):
            try:
                q.put_nowait(line)
            except queue.Full:
                pass


def _reader(p):
    for raw in iter(p.stdout.readline, ""):
        _broadcast(raw.rstrip("\n"))
    _broadcast("— listener stopped —")
    _proc["p"] = None


# ── helpers ───────────────────────────────────────────────────────────────
def _load_env_key(env_name):
    if ENV_PATH.exists():
        for line in ENV_PATH.read_text().splitlines():
            if line.startswith(env_name + "="):
                return line.split("=", 1)[1].strip()
    return os.environ.get(env_name, "")


def _save_env_key(env_name, value):
    lines = []
    if ENV_PATH.exists():
        lines = [l for l in ENV_PATH.read_text().splitlines()
                 if not l.startswith(env_name + "=")]
    if value:
        lines.append(f"{env_name}={value}")
    ENV_PATH.write_text("\n".join(lines) + "\n")


def _build_config(data):
    backend = data.get("backend", "api")
    nexts = [w.strip() for w in data.get("next", []) if w.strip()]
    backs = [w.strip() for w in data.get("back", []) if w.strip()]
    n_slides = int(data.get("slides", 12) or 12)

    cfg = {
        "audio": {"device": data.get("device"), "samplerate": 16000},
        "control": {
            "next_key": data.get("next_key", "right"),
            "prev_key": "left",
            "cooldown_sec": 1.0,
            "match": "contains",
            "trigger_on": "final",
        },
        "hotwords": {"next": nexts, "back": backs},
        "vad": {
            "start_rms": int(data.get("start_rms") or 500),
            "end_silence_ms": int(data.get("end_silence_ms") or 350),
        },
        "slides": [{"name": f"slide {i+1}", "keywords": []} for i in range(n_slides)],
    }
    if backend == "api":
        prov = data.get("provider", "groq")
        p = PROVIDERS.get(prov, PROVIDERS["groq"])
        # NOTE: no `prompt` bias — listing commands makes whisper echo them
        # (it even injected 返回, firing the wrong way). Homophones (页/夜/个)
        # are handled downstream by pinyin matching instead.
        cfg["recognizer"] = {
            "backend": "api",
            "base_url": data.get("base_url") or p["base_url"],
            "model": data.get("model") or p["model"],
            "api_key_env": p["api_key_env"] if prov in PROVIDERS else "OPENAI_API_KEY",
            # Always auto-detect: forcing a language drops short clips in the
            # OTHER language to empty (tested: forced en → None). Auto handles
            # Chinese + English both. The UI "language" only picks default commands.
            "language": None,
        }
    else:
        cfg["recognizer"] = {
            "backend": "vosk",
            "model_path": str(VOSK_CN_SMALL if data.get("language", "zh") == "zh" else VOSK_EN_SMALL),
            "restrict_to_keywords": False,
            "alternatives": 5,
        }
    return cfg


# ── routes ────────────────────────────────────────────────────────────────
@app.route("/")
def index():
    return send_from_directory(ROOT / "web", "index.html")


@app.route("/api/info")
def info():
    return jsonify({
        "providers": PROVIDERS,
        "vosk_cn": VOSK_CN_SMALL.exists(),
        "vosk_en": VOSK_EN_SMALL.exists(),
        "running": _proc["p"] is not None,
    })


@app.route("/api/download-model", methods=["POST"])
def download_model():
    """Fetch + unzip an offline Vosk model on demand (it's not in the repo/ZIP)."""
    data = request.get_json(force=True)
    lang = data.get("lang", "zh")
    name, url = VOSK_MODELS.get(lang, VOSK_MODELS["zh"])
    dest = ROOT / "models" / name
    if dest.exists():
        return jsonify({"ok": True, "msg": "already installed"})
    try:
        (ROOT / "models").mkdir(exist_ok=True)
        r = requests.get(url, timeout=180)
        r.raise_for_status()
        with zipfile.ZipFile(io.BytesIO(r.content)) as z:
            z.extractall(ROOT / "models")
        return jsonify({"ok": dest.exists(), "name": name})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})


@app.route("/api/devices")
def devices():
    try:
        import sounddevice as sd
        out = []
        for i, d in enumerate(sd.query_devices()):
            if d.get("max_input_channels", 0) > 0:
                out.append({"index": i, "name": d["name"]})
        return jsonify({"ok": True, "devices": out})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})


@app.route("/api/test-key", methods=["POST"])
def test_key():
    data = request.get_json(force=True)
    base = (data.get("base_url") or "").rstrip("/")
    key = data.get("key", "")
    if not base or not key:
        return jsonify({"ok": False, "error": "缺少 base_url 或 key"})
    try:
        r = requests.get(base + "/models", headers={"Authorization": f"Bearer {key}"}, timeout=15)
        if r.status_code == 200:
            return jsonify({"ok": True, "msg": "Key 有效,连接成功 ✓"})
        return jsonify({"ok": False, "error": f"HTTP {r.status_code}: {r.text[:160]}"})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})


@app.route("/api/save", methods=["POST"])
def save():
    data = request.get_json(force=True)
    cfg = _build_config(data)
    CONFIG_PATH.write_text(yaml.safe_dump(cfg, allow_unicode=True, sort_keys=False))
    if data.get("backend") == "api" and data.get("key"):
        _save_env_key(cfg["recognizer"]["api_key_env"], data["key"])
    return jsonify({"ok": True, "config_path": str(CONFIG_PATH)})


@app.route("/api/start", methods=["POST"])
def start():
    if _proc["p"] is not None:
        return jsonify({"ok": False, "error": "已在运行"})
    if not CONFIG_PATH.exists():
        return jsonify({"ok": False, "error": "请先保存配置"})
    env = dict(os.environ)
    env["PYTHONUNBUFFERED"] = "1"  # so the listener's stdout streams live to the log panel
    if ENV_PATH.exists():
        for line in ENV_PATH.read_text().splitlines():
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip()
    _log.clear()
    p = subprocess.Popen(
        [sys.executable, "-u", str(ROOT / "voice_slides.py"), "--config", str(CONFIG_PATH), "--debug"],
        cwd=str(ROOT), env=env,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, bufsize=1,
    )
    _proc["p"] = p
    threading.Thread(target=_reader, args=(p,), daemon=True).start()
    return jsonify({"ok": True})


@app.route("/api/stop", methods=["POST"])
def stop():
    p = _proc["p"]
    if p is None:
        return jsonify({"ok": False, "error": "未在运行"})
    p.terminate()
    return jsonify({"ok": True})


@app.route("/api/logs")
def logs():
    def gen():
        q = queue.Queue(maxsize=500)
        with _lock:
            _subscribers.append(q)
        # replay recent history
        for line in list(_log):
            yield f"data: {json.dumps(line)}\n\n"
        try:
            while True:
                line = q.get()
                yield f"data: {json.dumps(line)}\n\n"
        finally:
            with _lock:
                if q in _subscribers:
                    _subscribers.remove(q)
    return Response(gen(), mimetype="text/event-stream")


if __name__ == "__main__":
    print("▶ Control panel:  http://127.0.0.1:5001")
    app.run(host="127.0.0.1", port=5001, threaded=True)
