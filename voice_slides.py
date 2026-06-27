#!/usr/bin/env python3
"""
voice-slide-control
===================
Listen to the mic, recognise a spoken command, and press the "next" key so ANY
full-screen presentation advances: PowerPoint, WPS, a PDF viewer, or a
Gamma-exported HTML deck.

The trick: we never talk to the presentation app's API. We just simulate a
keystroke to whatever window is focused. Every one of those apps maps
Right / Space / PageDown to "next slide", so one code path covers them all.

Two speech backends (pick in config → recognizer.backend):
  • api   — any OpenAI-compatible /audio/transcriptions endpoint (OpenAI, Groq,
            or a self-hosted whisper server). High accuracy, nothing to download,
            you supply an API key via env var. RECOMMENDED.
  • vosk  — fully offline small model. No key, no network, lower accuracy.

Usage:
    python voice_slides.py --list-devices            # find your mic index
    python voice_slides.py --config config.yaml       # run
    python voice_slides.py --config config.yaml --debug

macOS: grant your terminal BOTH
    System Settings → Privacy & Security → Microphone
    System Settings → Privacy & Security → Accessibility   (needed to send keys)
"""

import argparse
import audioop
import io
import json
import os
import queue
import sys
import time
import wave

import sounddevice as sd
import yaml
from pynput.keyboard import Controller, Key

KEYMAP = {
    "right": Key.right,
    "left": Key.left,
    "space": Key.space,
    "pagedown": Key.page_down,
    "pageup": Key.page_up,
    "down": Key.down,
    "up": Key.up,
}


# ── text matching ────────────────────────────────────────────────────────
def _norm(s):
    """Lowercase, strip ALL whitespace: '下 一 页' == '下一页', 'next  slide' == 'next slide'."""
    return "".join(s.lower().split())


try:
    from pypinyin import lazy_pinyin
    _HAS_PINYIN = True
except Exception:
    _HAS_PINYIN = False


def _py(s):
    """Toneless pinyin of a string, so Chinese homophones collapse together:
    下一页 / 下一夜 → 'xiayiye'; 下一张 / 下一章 → 'xiayizhang'. Returns None if
    pypinyin isn't installed (then we fall back to character matching)."""
    if not _HAS_PINYIN:
        return None
    return "".join(lazy_pinyin(s)).lower()


def text_matches(text, keywords, mode="contains"):
    """Match by characters first, then by pinyin. Pinyin matching defeats the
    homophone problem that plagues short Chinese voice commands (页/夜, 张/章)."""
    t = _norm(text)
    tp = _py(text)
    for kw in keywords:
        k = _norm(kw)
        if mode == "exact":
            if k == t or (tp is not None and _py(kw) == tp):
                return kw
        else:  # contains
            if k in t:
                return kw
            if tp is not None:
                kp = _py(kw)
                if kp and kp in tp:
                    return kw
    return None


class Deck:
    """Tracks which slide we expect to be on (for the on-screen readout)."""

    def __init__(self, slides, hotwords):
        self.slides = slides
        self.hotwords = hotwords or {}
        self.idx = 0

    def current_keywords(self):
        if self.idx < len(self.slides):
            return [k.lower() for k in self.slides[self.idx].get("keywords", [])]
        return []

    def current_name(self):
        if self.idx < len(self.slides):
            return self.slides[self.idx].get("name", f"slide {self.idx}")
        return "end"

    def all_keywords(self):
        words = []
        for s in self.slides:
            words += s.get("keywords", [])
        for phrases in self.hotwords.values():
            words += phrases
        return [w.lower() for w in words]


# ── Vosk backend (offline) ────────────────────────────────────────────────
def _grammar_token(phrase):
    return phrase  # grammar restriction is unreliable on the small CN model; left as-is


def vosk_stream(cfg, deck, audio_q, debug):
    from vosk import Model, KaldiRecognizer

    model = Model(cfg["recognizer"]["model_path"])
    sr = cfg["audio"]["samplerate"]
    if cfg["recognizer"].get("restrict_to_keywords") and deck.all_keywords():
        grammar = json.dumps([_grammar_token(w) for w in deck.all_keywords()] + ["[unk]"])
        rec = KaldiRecognizer(model, sr, grammar)
    else:
        rec = KaldiRecognizer(model, sr)

    # N-best: keep several hypotheses. Fast/slurred speech often puts the real
    # command in the 2nd/3rd guess, not the 1st. We match against all of them.
    alts = int(cfg["recognizer"].get("alternatives", 0) or 0)
    if alts > 1:
        rec.SetMaxAlternatives(alts)

    while True:
        data = audio_q.get()
        final = rec.AcceptWaveform(data)
        res = json.loads(rec.Result() if final else rec.PartialResult())
        if "alternatives" in res:  # N-best final result
            text = " ".join(a.get("text", "") for a in res["alternatives"])
        else:
            text = res.get("text") or res.get("partial") or ""
        if text.strip():
            yield text, final


# ── API backend (OpenAI-compatible /audio/transcriptions) ─────────────────
def _make_wav(pcm_bytes, sr):
    b = io.BytesIO()
    w = wave.open(b, "wb")
    w.setnchannels(1)
    w.setsampwidth(2)
    w.setframerate(sr)
    w.writeframes(pcm_bytes)
    w.close()
    return b.getvalue()


def api_stream(cfg, audio_q, debug):
    """Energy-based VAD: collect a speech segment, send it to the transcription
    API when you pause, yield the transcript. One API call per utterance."""
    import requests

    rc = cfg["recognizer"]
    base = rc["base_url"].rstrip("/")
    url = base + "/audio/transcriptions"
    key_env = rc.get("api_key_env", "OPENAI_API_KEY")
    key = os.environ.get(key_env, "")
    model = rc["model"]
    lang = rc.get("language")
    # Bias the model toward the command words to beat homophones
    # (e.g. 页 vs 夜 vs 个). Whisper uses this as vocabulary priming.
    prompt = rc.get("prompt")
    sr = cfg["audio"]["samplerate"]

    if not key:
        print(f"⚠️  No API key found in ${key_env}. Set it, e.g.:\n"
              f"      export {key_env}=sk-...\n", file=sys.stderr)

    vad = cfg.get("vad", {})
    start_rms = vad.get("start_rms", 500)
    # End-of-utterance silence. Lower = faster reaction; too low splits a
    # two-word command ("next page") into two segments. Tunable in the UI.
    end_silence = vad.get("end_silence_ms", 350) / 1000.0
    min_speech = vad.get("min_speech_ms", 150) / 1000.0
    max_speech = vad.get("max_speech_ms", 6000) / 1000.0

    def transcribe(pcm):
        files = {"file": ("audio.wav", _make_wav(pcm, sr), "audio/wav")}
        data = {"model": model, "response_format": "json"}
        if lang:
            data["language"] = lang
        if prompt:
            data["prompt"] = prompt
        headers = {"Authorization": f"Bearer {key}"} if key else {}
        try:
            r = requests.post(url, headers=headers, files=files, data=data, timeout=30)
            r.raise_for_status()
            return (r.json().get("text") or "").strip()
        except Exception as e:
            print(f"  ⚠️  transcription failed: {e}", file=sys.stderr)
            return ""

    buf = []
    preroll = []            # rolling buffer of audio just BEFORE speech starts
    PREROLL = 3             # blocks (~3 × 125ms = 375ms) so the word's onset isn't clipped
    in_speech = False
    speech_start = 0.0
    last_voice = 0.0
    dbg_tick = 0

    while True:
        data = audio_q.get()
        rms = audioop.rms(data, 2)
        now = time.time()

        if debug:
            dbg_tick += 1
            if dbg_tick % 16 == 0:  # ~ every 2s, so you can calibrate start_rms
                print(f"    [rms] {rms}  (start_rms={start_rms}, speaking={in_speech})")

        if rms >= start_rms:
            if not in_speech:
                in_speech = True
                speech_start = now
                buf = list(preroll)   # prepend the pre-roll so the onset is included
            buf.append(data)
            last_voice = now
            if now - speech_start >= max_speech:  # safety cap on a long segment
                in_speech = False
                text = transcribe(b"".join(buf))
                buf = []
                if text:
                    yield text, True
        else:
            if in_speech:
                buf.append(data)  # keep a little trailing audio
                if now - last_voice >= end_silence:
                    in_speech = False
                    if now - speech_start - end_silence >= min_speech:
                        text = transcribe(b"".join(buf))
                        if text:
                            yield text, True
                    buf = []
            else:
                preroll.append(data)        # keep a rolling window of recent quiet audio
                if len(preroll) > PREROLL:
                    preroll.pop(0)


# ── main ──────────────────────────────────────────────────────────────────
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="config.yaml")
    ap.add_argument("--list-devices", action="store_true")
    ap.add_argument("--debug", action="store_true",
                    help="print everything the recognizer hears (and mic RMS for the api backend)")
    args = ap.parse_args()

    if args.list_devices:
        print(sd.query_devices())
        return

    with open(args.config, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)

    deck = Deck(cfg["slides"], cfg.get("hotwords"))
    kbd = Controller()
    next_key = KEYMAP[cfg["control"]["next_key"]]
    prev_key = KEYMAP[cfg["control"]["prev_key"]]
    cooldown = cfg["control"]["cooldown_sec"]
    match_mode = cfg["control"]["match"]
    trigger_on = cfg["control"].get("trigger_on", "final")
    back_words = [w.lower() for w in deck.hotwords.get("back", [])]
    fwd_words = [w.lower() for w in deck.hotwords.get("next", [])]
    backend = cfg["recognizer"]["backend"]

    audio_q = queue.Queue()

    def callback(indata, frames, t, status):
        if status:
            print(status, file=sys.stderr)
        audio_q.put(bytes(indata))

    last_fire = 0.0

    def fire(key):
        kbd.press(key)
        kbd.release(key)

    print("=" * 60)
    print(f"  config       : {args.config}")
    print(f"  backend      : {backend}")
    print(f"  next command : {fwd_words or '(per-slide keywords)'}")
    print(f"  back command : {back_words or '(none)'}")
    print("=" * 60)
    print(f"▶ Ready. On: [{deck.idx}] {deck.current_name()}")
    print("  Listening… (Ctrl+C to stop)\n")

    with sd.RawInputStream(
        samplerate=cfg["audio"]["samplerate"],
        blocksize=1600,  # ~100ms — snappier endpointing
        device=cfg["audio"]["device"],
        dtype="int16",
        channels=1,
        callback=callback,
    ):
        if backend == "vosk":
            gen = vosk_stream(cfg, deck, audio_q, args.debug)
        elif backend == "api":
            gen = api_stream(cfg, audio_q, args.debug)
        else:
            raise SystemExit(f"unknown backend: {backend!r} (use 'api' or 'vosk')")

        cfg_mtime = os.path.getmtime(args.config)
        for text, is_final in gen:
            # Hot-reload commands when the config file changes — add/remove a
            # keyword in the web panel and it takes effect live, no restart.
            try:
                m = os.path.getmtime(args.config)
                if m != cfg_mtime:
                    cfg_mtime = m
                    nc = yaml.safe_load(open(args.config, encoding="utf-8"))
                    deck.hotwords = nc.get("hotwords") or {}
                    deck.slides = nc.get("slides") or deck.slides
                    back_words = [w.lower() for w in deck.hotwords.get("back", [])]
                    fwd_words = [w.lower() for w in deck.hotwords.get("next", [])]
                    print(f"  ↻ commands reloaded · next={fwd_words} back={back_words}")
            except Exception:
                pass

            if args.debug:
                tag = "FINAL" if is_final else "partial"
                print(f"    [{tag}] {text!r}")

            if trigger_on == "final" and not is_final:
                continue

            now = time.time()
            if now - last_fire < cooldown:
                continue

            back_hit = text_matches(text, back_words, match_mode) if back_words else None
            next_hit = text_matches(text, fwd_words, match_mode) if fwd_words else None
            if not next_hit:
                next_hit = text_matches(text, deck.current_keywords(), match_mode)

            # If both directions appear in one utterance (model echo/hallucination),
            # it's ambiguous — do nothing rather than jump the wrong way.
            if back_hit and next_hit:
                if args.debug:
                    print(f"    [skip] 含义不明（前进/后退都命中）: {text!r}")
                continue

            if back_hit:
                fire(prev_key)
                deck.idx = max(0, deck.idx - 1)
                last_fire = now
                print(f"  ◀ back → [{deck.idx}] {deck.current_name()}  (heard: {text!r})")
            elif next_hit:
                fire(next_key)
                deck.idx += 1
                last_fire = now
                print(f"  ▶ next (\"{next_hit}\") → [{deck.idx}] {deck.current_name()}")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nStopped.")
