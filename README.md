# 🎙️ Voice Slide Control

> [中文文档](README.zh.md)

**You speak, it turns.** Say a command and your slides advance — no clicker, no reaching for the laptop. Your voice is the clicker.

Works with **PowerPoint · WPS · PDF · web decks** (e.g. HTML exported from Gamma).

---

## How it works

```
You speak  →  command recognized ("next")  →  one arrow key is pressed  →  slide advances
   🎙️                ☁️ / 🔒                         ⌨️                        ▶️
```

The trick is step three: the app doesn't integrate with any presentation software. It just simulates an arrow key to whatever window is in front. PowerPoint, WPS, PDF readers and web decks all advance on the arrow key in full-screen mode, so one app covers every format.

Two recognition backends:

| | ☁️ Cloud API (recommended) | 🔒 Local model |
|---|---|---|
| Accuracy | High, robust even on fast speech | OK, weaker on fast short commands |
| Network | Required | Fully offline |
| Cost | Your own API key (free tiers exist) | Free |
| Download | No model download | ~42MB model |

---

## 🚀 Quick start (no terminal needed)

### 1 · Download

On the GitHub page: **Code → Download ZIP**, then unzip.

### 2 · Double-click to launch

- **macOS**: double-click **`start.command`**
  - If macOS blocks it the first time, **right-click → Open → Open** (once only).
- **Windows**: double-click **`start.bat`**

The first launch sets up the environment automatically (1–2 minutes, once), then opens the control panel at `http://127.0.0.1:5001`.

### 3 · Get a free API key (Groq recommended)

> Want fully offline with no key? Jump to [Offline mode](#-offline-mode).

1. Sign up at **https://console.groq.com/keys** (free)
2. Click **Create API Key** and copy it (looks like `gsk_...`)
3. Back in the panel: pick **Groq** → paste the key → click **Test connection**
4. A green ✅ means it works — click **Save**

**OpenAI** also works: switch the provider to OpenAI and paste an `sk-...` key. For best accuracy pick the `gpt-4o-transcribe` model.

### 4 · Grant permissions (important)

To hear you and press keys for you, the app it runs under needs permission:

**macOS** — System Settings → Privacy & Security:
- 🎤 **Microphone** → enable Terminal (or your terminal app)
- ♿ **Accessibility** → enable Terminal (required to simulate keystrokes)

> After granting, click Stop then Start listening again so it takes effect.

**Windows** — Settings → Privacy & security → Microphone → allow desktop apps. (No accessibility permission needed for keystrokes.)

### 5 · Present

1. Click **Start listening**
2. Open your deck, go **full-screen**, keep that window focused
3. Finish a slide and say **“next”** (or **“back”** to go back)

The live log on the right shows what it heard and whether it turned.

---

## 🧭 The control panel

Everything is point-and-click, no files to edit:

- **Recognition**: switch Cloud API / Local model
- **API key**: pick provider, choose model, paste key, test connection
- **Commands**: add/remove forward & back trigger phrases as tags (live hot-reload while listening)
- **Options**: language, microphone, next key, mic sensitivity, reaction speed
- **Run**: Save → Start / Stop with a live log

The UI is bilingual (English default, 中/EN toggle top-right).

---

## 🔒 Offline mode

No network, no key — use the local Vosk model (offline, free):

1. Download a model into `models/`:
   ```bash
   cd models
   curl -LO https://alphacephei.com/vosk/models/vosk-model-small-cn-0.22.zip
   unzip vosk-model-small-cn-0.22.zip
   ```
   (For English, use `vosk-model-small-en-us-0.15`.)
2. In the panel switch to **Local model**, Save → Start.

⚠️ The small model is limited on fast short commands. For reliability, use the cloud API.

---

## 🌏 Chinese commands & homophones

Short Chinese commands collide as homophones — 下一页 (next page) and 下一夜 (next night) sound identical, so the model often transcribes the wrong character (页/夜, 张/章). The app matches commands by **pinyin**, not characters, so 下一页 / 下一夜 / 夏夜… all resolve to the same command. It also keeps a short pre-roll of audio so the first syllable isn't clipped.

---

## 🛠️ For developers

```
voice-slide-control/
├── start.command / start.bat   # double-click launcher (auto-installs on first run)
├── app.py                      # local web control panel (Flask)
├── web/index.html              # single-page frontend
├── voice_slides.py             # core engine (also runnable from the CLI)
├── config.*.yaml               # example configs (api / local / zh / en)
└── requirements.txt
```

Run the engine directly (skip the web UI):

```bash
python -m venv .venv && .venv/bin/pip install -r requirements.txt
export GROQ_API_KEY=gsk_...                       # cloud mode
.venv/bin/python voice_slides.py --config config.api.zh.yaml --debug
.venv/bin/python voice_slides.py --list-devices   # find your mic index
```

**Self-hosted recognition**: any OpenAI-compatible `/audio/transcriptions` endpoint works — point `base_url` at it (e.g. a whisper server on your own machine).

---

## ❓ Troubleshooting: started, but nothing happens

Read the live log on the right:

1. **No `[rms]` numbers at all** → mic isn't captured. Check mic permission and device.
2. **`[rms]` doesn't rise when you speak** → same: mic permission / device.
3. **rms rises but no `[FINAL]`** → no transcription. Test your API key, or check the network; in offline mode the command wasn't recognized.
4. **`▶ next` appears but the slide doesn't move** → **Accessibility** permission (macOS) isn't granted. Grant it and restart listening.
5. **Occasional false turns during normal speech** → use less collision-prone commands, or drop very short aliases.

> Common root cause: launch from your own terminal app so microphone and accessibility prompts can be granted.

---

## License

MIT
