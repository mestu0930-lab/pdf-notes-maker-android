# pdf_notes_app_kivy.py
# Android version – cloud-only, all desktop features except local models
#
# Compatible with: Kivy 2.3.1 · Python 3.11 (p4a) · openai >=1.0.0 · pypdf >=3.0
#
# BUGS FIXED IN PREVIOUS VERSION (carried forward):
#  1. [CRITICAL] pages_data NameError in extract_text_from_pdf
#  2. [CRITICAL] android_context AttributeError in _create_webview
#  3. [CRITICAL] temp_path NameError in _on_pdf_saved
#  4. [CRITICAL] msg["content"].split() TypeError on list content in token counting
#  5. [RUNTIME]  on_pause binding TypeError
#  6. [RUNTIME]  None-guard in load_html/print_to_pdf after failed _create_webview
#  7. [UI]       Cloud model dropdown empty on first launch
#  8. [MINOR]    _share_file: non-Android guard
#  9. [MISSING]  on_stop() added to persist settings on explicit app exit
#
# ADDITIONAL FIXES FOR KIVY 2.3.1 (this version):
#  A. [KIVY 2.3.1] Removed unused imports: BooleanProperty, NumericProperty,
#     webbrowser, cast — keep the import block clean; unused Kivy Property
#     imports can cause subtle class-level registration noise.
#  B. [PYTHON 3.8+] sign_request(): added digestmod=hashlib.sha256 to
#     hmac.new() — the digestmod argument became required (strict-mode
#     DeprecationWarning from 3.8, potential error in 3.13+).
#  C. [KIVY 2.3.1 LAYOUT] cloud_group BoxLayout: added minimum_height
#     binding identical to left_content. Without it, a BoxLayout with
#     size_hint=(1, None) defaults to height=100 in Kivy 2.3, clipping
#     all five child rows (30dp + 44dp×4 + spacing).
#  D. [KIVY 2.3.1 DISABLED] set_controls_enabled(): in Kivy 2.3, setting
#     disabled=True on a parent widget does NOT cascade to its children's
#     interactive state (touch events are blocked by the parent, but the
#     children's own .disabled flag stays False and they still accept
#     programmatic input). CloudModelSelector's TextInput and dropdown
#     Button are now disabled individually so they cannot be typed into
#     or activated while the license is pending/invalid.
# ---------------------------------------------------------------------------

import sys
import os
import tempfile
import asyncio
import requests
import markdown
import re
import time
import hmac
import hashlib
import httpx
import json
import collections
import uuid
import base64
from datetime import datetime
from threading import Thread

# ---------- Android-specific imports (safe on any platform) ----------
try:
    from jnius import autoclass
    from android.runnable import run_on_ui_thread
    from android import activity
    ON_ANDROID = True
except ImportError:
    ON_ANDROID = False
    autoclass = None
    # FIX A: 'cast' removed (was imported but never used)
    run_on_ui_thread = lambda f: f   # identity decorator on non-Android
    activity = None
    share = None

from kivy.app import App
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.label import Label
from kivy.uix.textinput import TextInput
from kivy.uix.checkbox import CheckBox
from kivy.uix.spinner import Spinner
from kivy.uix.progressbar import ProgressBar
from kivy.uix.popup import Popup
from kivy.uix.filechooser import FileChooserListView
from kivy.uix.scrollview import ScrollView
from kivy.uix.widget import Widget
from kivy.clock import Clock, mainthread
# FIX A: BooleanProperty and NumericProperty removed — imported but never used.
#         Unused Kivy Property imports at module level are harmless, but in
#         Kivy 2.3 they register themselves via the metaclass even when not
#         attached to a class, creating unnecessary descriptor overhead.
from kivy.properties import StringProperty, ObjectProperty
from kivy.core.window import Window
from kivy.uix.slider import Slider

# Core imports
from docx import Document as DocxDocument
from pypdf import PdfReader
from openai import AsyncOpenAI

# License & security
from license_manager import LicenseManager, get_embedded_license_key

SIGNING_SECRET    = b'\xe6\xc9\xc4!\xaf\xe5l\x98RY\xdf\xf9z\xa3\x1e\xef'
LICENSE_SERVER_URL = "https://mestu0930.pythonanywhere.com/api/activate"
LICENSE_CHECK_URL  = "https://mestu0930.pythonanywhere.com/api/check_license"
MAX_RECEIPT_SIZE   = 10 * 1024 * 1024

SERVICE_DISPLAY = {
    'openai':     'OpenAI',
    'groq':       'Groq',
    'google':     'Google AI Studio',
    'openrouter': 'OpenRouter',
}


def sign_request(data):
    secret    = SIGNING_SECRET
    timestamp = str(int(time.time()))
    data_json = json.dumps(data)
    payload   = data_json + timestamp
    # FIX B: pass digestmod= explicitly — required on Python 3.8+ to avoid
    # DeprecationWarning; may raise TypeError in Python 3.13+ without it.
    signature = hmac.new(
        secret,
        payload.encode('utf-8'),
        digestmod=hashlib.sha256,
    ).hexdigest()
    return {
        'data':      data_json,
        'timestamp': timestamp,
        'signature': signature,
    }


# ---------- Rate limiters ----------
class TokenBucket:
    def __init__(self, tokens_per_minute):
        self.capacity    = tokens_per_minute
        self.tokens      = tokens_per_minute
        self.rate        = tokens_per_minute / 60.0
        self.last_refill = time.monotonic()

    def _refill(self):
        now           = time.monotonic()
        elapsed       = now - self.last_refill
        self.tokens   = min(self.capacity, self.tokens + elapsed * self.rate)
        self.last_refill = now

    def consume(self, tokens):
        self._refill()
        if tokens > self.tokens:
            deficit    = tokens - self.tokens
            sleep_time = deficit / self.rate
            time.sleep(sleep_time)
            self._refill()
        self.tokens -= tokens


class RequestRateLimiter:
    def __init__(self, rpm: int):
        self.rpm        = rpm
        self.window     = 60.0
        self.timestamps = collections.deque()

    async def acquire(self):
        now = time.monotonic()
        while self.timestamps and now - self.timestamps[0] > self.window:
            self.timestamps.popleft()
        if len(self.timestamps) >= self.rpm:
            wait_time = self.timestamps[0] + self.window - now + 0.1
            if wait_time > 0:
                await asyncio.sleep(wait_time)
            now = time.monotonic()
            while self.timestamps and now - self.timestamps[0] > self.window:
                self.timestamps.popleft()
        self.timestamps.append(time.monotonic())


# ---------- Markdown helpers ----------
def clean_google_meta(md_text):
    tag = '</thought>'
    idx = md_text.rfind(tag)
    if idx != -1:
        return md_text[idx + len(tag):].strip()
    return md_text


def normalize_headings(markdown_text, level=3):
    lines = markdown_text.splitlines()
    fixed = []
    for line in lines:
        m = re.match(r'^(#{1,6})\s+(.*)', line)
        if m:
            fixed.append(f"{'#' * level} {m.group(2)}")
        else:
            fixed.append(line)
    return '\n'.join(fixed)


def fix_markdown_lists(text):
    lines     = text.splitlines()
    new_lines = []
    for i, line in enumerate(lines):
        stripped = line.lstrip()
        if '$' in stripped:
            new_lines.append(line)
            continue
        if (stripped.startswith('- ') or stripped.startswith('* ')
                or re.match(r'\d+\. ', stripped)) and i > 0:
            prev = lines[i - 1].strip()
            if (prev != '' and not prev.startswith('-')
                    and not prev.startswith('*')
                    and not re.match(r'\d+\.', prev)):
                new_lines.append('')
        new_lines.append(line)
    return '\n'.join(new_lines)


def sanitize_math_delimiters(markdown_text):
    text = re.sub(r'`(\$[^`]+\$)`',       r'\1', markdown_text)
    text = re.sub(r'`(\$\$[^`]+\$\$)`',   r'\1', text)
    text = re.sub(r'\\\((.*?)\\\)',        r'$\1$',   text, flags=re.DOTALL)
    text = re.sub(r'\\\[(.*?)\\\]',        r'$$\1$$', text, flags=re.DOTALL)
    return text


# ---------- CloudModelSelector ----------
class CloudModelSelector(BoxLayout):
    model_text       = StringProperty('')
    remove_requested = ObjectProperty(None)

    def __init__(self, app_ref, **kwargs):
        super().__init__(**kwargs)
        self.app             = app_ref
        self.orientation     = 'vertical'
        self.custom_models   = []
        self.service         = 'openai'
        self.default_models  = []
        self._warned_non_default = False

        top = BoxLayout(orientation='horizontal', size_hint=(1, None), height='48dp')
        self.text_input = TextInput(hint_text='Select or enter model...', multiline=False)
        self.text_input.bind(on_text_validate=self._on_enter_pressed)
        top.add_widget(self.text_input)

        self.dropdown_btn = Button(text='▼', size_hint=(None, 1), width='48dp')
        self.dropdown_btn.bind(on_press=self.show_dropdown)
        top.add_widget(self.dropdown_btn)
        self.add_widget(top)

        self.dropdown = None

    def set_models(self, default_models, custom_models, service):
        self.service        = service
        self.default_models = default_models
        self.custom_models  = custom_models
        if self.dropdown:
            self._rebuild_dropdown()

    def show_dropdown(self, instance):
        if self.dropdown:
            self._hide_dropdown()
            return
        self._rebuild_dropdown()

    def _rebuild_dropdown(self):
        if self.dropdown:
            self.remove_widget(self.dropdown)
        self.dropdown      = BoxLayout(orientation='vertical', size_hint=(1, None))
        items_count        = len(self.default_models) + len(self.custom_models)
        self.dropdown.height = items_count * 44 * self._get_density()

        for model in self.default_models:
            btn = Button(text=model, size_hint=(1, None), height='44dp')
            btn.bind(on_press=self._on_model_btn_press)
            self.dropdown.add_widget(btn)
        for model in self.custom_models:
            row    = BoxLayout(orientation='horizontal', size_hint=(1, None), height='44dp')
            btn    = Button(text=model, size_hint=(0.8, 1))
            btn.bind(on_press=self._on_model_btn_press)
            del_btn = Button(text='✕', size_hint=(0.2, 1), background_color=(1, 0, 0, 1))
            del_btn.bind(on_press=lambda x, m=model: self._remove_custom(m))
            row.add_widget(btn)
            row.add_widget(del_btn)
            self.dropdown.add_widget(row)
        self.add_widget(self.dropdown)

    def _get_density(self):
        return Window.size[1] / 720

    def _on_model_btn_press(self, instance):
        model = instance.text
        if model not in self.default_models and not self._warned_non_default:
            self._warned_non_default = True
            self.app.show_popup(
                "Change Model?",
                "If you are not on a paid plan, using a non-default model may reduce "
                "the amount of notes you can make per day.\n\n"
                "Are you sure you want to switch?",
                ok_callback=lambda: self._set_model(model),
                cancel_callback=None,
            )
        else:
            self._set_model(model)

    def _set_model(self, model):
        self.text_input.text = model
        self._hide_dropdown()

    def _on_enter_pressed(self, instance):
        new_model = self.text_input.text.strip()
        if not new_model:
            return
        if new_model not in self.default_models and new_model not in self.custom_models:
            self.custom_models.append(new_model)
            self.app.custom_cloud_models.setdefault(self.service, [])
            self.app.custom_cloud_models[self.service].append(new_model)
            self.app.save_settings()
            self.set_models(self.default_models, self.custom_models, self.service)
        self._hide_dropdown()

    def _remove_custom(self, model_name):
        if self.remove_requested:
            self.remove_requested(self.service, model_name)
        self._hide_dropdown()

    def _hide_dropdown(self):
        if self.dropdown:
            self.remove_widget(self.dropdown)
            self.dropdown = None

    def get_selected_model(self):
        return self.text_input.text.strip()

    # FIX D helper: expose child widgets for external disable control
    def set_input_disabled(self, disabled: bool):
        """
        Kivy 2.3.1: parent.disabled=True blocks touch but does NOT set the
        .disabled flag on children. Call this to properly lock/unlock the
        selector's interactive children.
        """
        self.text_input.disabled   = disabled
        self.dropdown_btn.disabled = disabled


# ---------- AIWorker ----------
class AIWorker:
    def __init__(self, chunks, model, prompt, max_tokens, temperature,
                 max_concurrent, api_config=None, rate_limiter=None,
                 request_rate_limiter=None, callback_progress=None,
                 callback_status=None, callback_finished=None, callback_error=None):
        self.chunks               = chunks
        self.model                = model
        self.prompt               = prompt
        self.max_tokens           = max_tokens
        self.temperature          = temperature
        self.max_concurrent       = max_concurrent
        self.api_config           = api_config
        self.rate_limiter         = rate_limiter
        self.request_rate_limiter = request_rate_limiter
        self.callback_progress    = callback_progress
        self.callback_status      = callback_status
        self.callback_finished    = callback_finished
        self.callback_error       = callback_error

    def start(self):
        Thread(target=self._run_async, daemon=True).start()

    def _run_async(self):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            results = loop.run_until_complete(self._process_chunks())
            self.callback_finished(results)
        except Exception as e:
            self.callback_error(str(e))
        finally:
            loop.close()

    async def _process_chunks(self):
        client = self._create_cloud_client()
        return await self._process_parallel(client)

    @staticmethod
    def _clean_google_response(raw_text):
        """
        Remove meta-commentary before the first heading
        (e.g. '* Input: …'). Keeps everything from the first heading onward.
        """
        m = re.search(r'(?:^|\n)#{1,6}\s', raw_text)
        if m:
            return raw_text[m.start():].lstrip('\n')
        return raw_text

    async def _process_parallel(self, client):
        semaphore = asyncio.Semaphore(self.max_concurrent)
        total     = len(self.chunks)
        completed = 0

        async def bounded_task(start, end, text, images):
            nonlocal completed
            if not text.strip():
                result = (start, end, f"[No text on pages {start}–{end}]")
            else:
                system_prompt = (
                    "You are a precise note-taking assistant. Your task is to extract and organize "
                    "key information from the provided text into well-structured notes.\n\n"
                    "CRITICAL OUTPUT FORMAT:\n"
                    "- Use Markdown for formatting: headings (#, ##), bold (**text**), italic (*text*), "
                    "bulleted lists (-), numbered lists, and tables.\n"
                    "- When creating bullet or numbered lists, **always** start each list item on a brand-new line.\n"
                    "- Do NOT put a list marker after a colon on the same line.\n"
                    "- For ALL mathematical formulas, wrap them in $...$ for inline and $$...$$ for display.\n"
                    "- NEVER use \\(...\\) or \\[...\\]. NEVER put math inside backticks or code blocks.\n"
                    "- Example: $E=mc^2$ and $$\\frac{a}{b}$$\n"
                    "- Use real emojis 😊📝✅ where they add clarity.\n"
                    "- Do NOT add any introductory phrases like 'Here are the notes' or conclusions.\n"
                    "- Do NOT add conclusions, summaries, or meta-commentary.\n"
                    "- DO NOT end the notes with any offer, question, or pleasantry. Output ONLY the raw notes.\n"
                    "- The text is a segment of a larger document. Continue the notes seamlessly.\n"
                    "- Do NOT repeat the document title or create new section headers unless they appear in the text.\n"
                    "- Output ONLY the formatted notes – no greetings, no sign-offs.\n"
                    "- Keep the tone professional and concise."
                )
                full_prompt = (
                    f"{self.prompt}\n\n"
                    f"Note: This is an excerpt from pages {start}–{end} of a longer document. "
                    f"Do not add introductory or concluding remarks. Continue the notes naturally.\n\n"
                    f"Text:\n{text}"
                )

                # Build user message content (may include images)
                user_content = [{"type": "text", "text": full_prompt}]
                if images:
                    for img_b64 in images:
                        user_content.append({
                            "type": "image_url",
                            "image_url": {"url": f"data:image/png;base64,{img_b64}"},
                        })

                messages = [
                    {"role": "system", "content": system_prompt},
                    {"role": "user",   "content": user_content},
                ]

                # Token counting: handles both str and list content blocks
                if self.rate_limiter:
                    def _extract_text_from_content(content):
                        """Return a flat string regardless of content being str or list."""
                        if isinstance(content, str):
                            return content
                        parts = []
                        for block in content:
                            if isinstance(block, dict) and block.get("type") == "text":
                                parts.append(block.get("text", ""))
                        return "\n".join(parts)

                    try:
                        import tiktoken as tk
                        enc         = tk.get_encoding("cl100k_base")
                        token_count = sum(
                            len(enc.encode(_extract_text_from_content(msg["content"])))
                            for msg in messages
                        )
                    except Exception:
                        token_count = sum(
                            len(_extract_text_from_content(msg["content"]).split())
                            for msg in messages
                        )
                    await asyncio.to_thread(self.rate_limiter.consume, token_count)

                if self.request_rate_limiter:
                    await self.request_rate_limiter.acquire()

                notes       = None
                max_retries = 2
                for attempt in range(max_retries + 1):
                    try:
                        response = await client.chat.completions.create(
                            model       = self.model,
                            messages    = messages,
                            max_tokens  = self.max_tokens,
                            temperature = self.temperature,
                        )
                        notes = response.choices[0].message.content.strip()
                        if self.api_config and self.api_config.get('service') == 'google':
                            notes = self._clean_google_response(notes)
                        break
                    except (httpx.ReadTimeout, httpx.ConnectTimeout,
                            httpx.RemoteProtocolError) as e:
                        if attempt == max_retries:
                            notes = f"[Error: timeout after retries – {str(e)}]"
                        else:
                            await asyncio.sleep(2)
                    except Exception as e:
                        notes = f"[Error: {str(e)}]"
                        break

                result = (start, end, notes)

            completed += 1
            self.callback_progress(int(completed / total * 100))
            self.callback_status(f"Processed chunk {completed}/{total}")
            return result

        async def sem_task(s, e, t, imgs):
            async with semaphore:
                return await bounded_task(s, e, t, imgs)

        tasks = [sem_task(s, e, t, imgs) for s, e, t, imgs in self.chunks]
        return await asyncio.gather(*tasks)

    def _create_cloud_client(self):
        service = self.api_config.get('service', 'openai').lower()
        api_key = self.api_config['api_key']
        timeout = httpx.Timeout(180.0, connect=15.0)
        if service == 'openai':
            return AsyncOpenAI(api_key=api_key, timeout=timeout)
        elif service == 'groq':
            return AsyncOpenAI(
                base_url="https://api.groq.com/openai/v1",
                api_key=api_key,
                timeout=timeout,
            )
        elif service == 'google':
            return AsyncOpenAI(
                base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
                api_key=api_key,
                timeout=timeout,
            )
        elif service == 'openrouter':
            return AsyncOpenAI(
                base_url="https://openrouter.ai/api/v1",
                api_key=api_key,
                timeout=timeout,
                default_headers={
                    "HTTP-Referer": "http://localhost",
                    "X-Title":      "PDF Notes Maker",
                },
            )
        else:
            raise ValueError(f"Unsupported service: {service}")


# ---------- Android WebView wrapper ----------
class AndroidWebView(Widget):
    def __init__(self, app_ref, **kwargs):
        super().__init__(**kwargs)
        self.app                 = app_ref
        self.webview             = None
        self._pdf_callback       = None
        self._html_content       = ''
        self._rendering_complete = False

    def _create_webview(self):
        if autoclass is None:
            return
        WebView        = autoclass('android.webkit.WebView')
        PythonActivity = autoclass('org.kivy.android.PythonActivity')
        context        = PythonActivity.mActivity
        self.webview   = WebView(context)
        settings = self.webview.getSettings()
        settings.setJavaScriptEnabled(True)
        settings.setAllowFileAccess(True)
        self.webview.setWebViewClient(self._get_webview_client())

    def _get_webview_client(self):
        from jnius import PythonJavaClass, java_method

        class WebViewClient(PythonJavaClass):
            __javainterfaces__ = ['android/webkit/WebViewClient']

            def __init__(self, parent):
                super().__init__()
                self.parent       = parent
                self._check_event = None

            @java_method('(Landroid/webkit/WebView;Ljava/lang/String;)V')
            def onPageFinished(self, webview, url):
                webview.evaluateJavascript(
                    """
                    (function() {
                        if (window.MathJax && MathJax.startup) {
                            MathJax.startup.promise.then(function() {
                                window.renderingComplete = true;
                            });
                        } else {
                            window.renderingComplete = true;
                        }
                    })();
                    """,
                    None,
                )
                self._check_event = Clock.schedule_interval(
                    lambda dt: self._check_rendering(webview), 0.5
                )

            def _check_rendering(self, webview):
                webview.evaluateJavascript(
                    "(function() { return window.renderingComplete; })()",
                    self._on_render_result,
                )

            def _on_render_result(self, value):
                if value == 'true':
                    if self._check_event:
                        Clock.unschedule(self._check_event)
                    self.parent._rendering_complete = True
                    if self.parent._pdf_callback:
                        self.parent._print_to_pdf()

        return WebViewClient(self)

    @run_on_ui_thread
    def load_html(self, html_content, base_url=None):
        if not ON_ANDROID:
            return
        if not self.webview:
            self._create_webview()
        if not self.webview:
            return
        self._html_content       = html_content
        self._rendering_complete = False
        self.webview.loadDataWithBaseURL(
            base_url or '', html_content, 'text/html', 'utf-8', None
        )

    @run_on_ui_thread
    def print_to_pdf(self, filepath, callback=None):
        if not ON_ANDROID:
            if callback:
                callback(False)
            return
        if not self.webview:
            if callback:
                callback(False)
            return
        self._pdf_callback = callback
        self._pdf_filepath = filepath
        if self._rendering_complete:
            self._print_to_pdf()

    def _print_to_pdf(self):
        from java.io import File
        self.webview.printToPdf(File(self._pdf_filepath), None, self._on_pdf_created)

    def _on_pdf_created(self, success):
        if self._pdf_callback:
            self._pdf_callback(success)

    def get_html(self, callback):
        """Return the full HTML via a callback (for Word export)."""
        if not self.webview:
            callback("")
            return
        self.webview.evaluateJavascript(
            "(function() { return document.documentElement.outerHTML; })()",
            lambda s: callback(s.strip('"')),
        )


# ---------- Main App ----------
class PDFNotesMakerApp(App):

    def build(self):
        self.title               = 'PDF Notes Maker'
        self.license_manager     = LicenseManager()
        self.api_config          = None
        self.custom_cloud_models = {}
        self.temp_input_path     = None
        self.notes_results       = None
        self.final_html          = None
        self.license_status      = None
        self._restoring_settings = False
        self._temp_pdf_path      = None   # cross-method temp path (fix #3)

        # ---- Root ----
        root = BoxLayout(orientation='vertical')

        # Status bar
        self.status_bar = Label(
            text='Checking license...', size_hint=(1, None), height='30dp'
        )
        root.add_widget(self.status_bar)

        # Main area
        splitter = BoxLayout(orientation='horizontal')

        # ---- Left panel (scrollable settings) ----
        left_panel   = ScrollView(size_hint=(0.35, 1))
        left_content = BoxLayout(
            orientation='vertical', padding='10dp', spacing='10dp',
            size_hint=(1, None),
        )
        left_content.bind(minimum_height=left_content.setter('height'))

        # ---- Cloud group ----
        # FIX C: bind minimum_height so Kivy 2.3.1 sizes the BoxLayout to fit
        #        its children instead of defaulting to 100dp.
        cloud_group = BoxLayout(
            orientation='vertical', spacing='5dp', size_hint=(1, None)
        )
        cloud_group.bind(minimum_height=cloud_group.setter('height'))

        cloud_check_row = BoxLayout(
            orientation='horizontal', size_hint=(1, None), height='30dp'
        )
        self.cloud_checkbox = CheckBox(active=False)
        cloud_check_row.add_widget(self.cloud_checkbox)
        cloud_check_row.add_widget(Label(text='☁️ Cloud API (Optional)'))
        cloud_group.add_widget(cloud_check_row)

        service_layout = BoxLayout(
            orientation='horizontal', size_hint=(1, None), height='44dp'
        )
        service_layout.add_widget(Label(text='Service:', size_hint=(0.3, 1)))
        self.service_spinner = Spinner(
            text='Google AI Studio',
            values=['OpenAI', 'Groq', 'Google AI Studio', 'OpenRouter'],
            size_hint=(0.7, 1),
        )
        self.service_spinner.bind(text=self.on_service_changed)
        service_layout.add_widget(self.service_spinner)
        cloud_group.add_widget(service_layout)

        keys_layout = BoxLayout(
            orientation='horizontal', size_hint=(1, None), height='44dp'
        )
        keys_layout.add_widget(Label(text='Saved Keys:', size_hint=(0.3, 1)))
        self.saved_keys_spinner = Spinner(text='None', size_hint=(0.7, 1))
        self.saved_keys_spinner.bind(text=self.on_saved_key_selected)
        keys_layout.add_widget(self.saved_keys_spinner)
        cloud_group.add_widget(keys_layout)

        api_row = BoxLayout(
            orientation='horizontal', size_hint=(1, None), height='44dp'
        )
        api_row.add_widget(Label(text='API Key:', size_hint=(0.3, 1)))
        self.api_key_input = TextInput(
            hint_text='Enter or select key...', multiline=False,
            password=True, size_hint=(0.4, 1),
        )
        api_row.add_widget(self.api_key_input)
        self.show_key_check = CheckBox(active=False, size_hint=(0.1, 1))
        self.show_key_check.bind(active=self.toggle_key_visibility)
        api_row.add_widget(self.show_key_check)
        cloud_group.add_widget(api_row)

        action_row = BoxLayout(
            orientation='horizontal', size_hint=(1, None), height='44dp'
        )
        self.save_api_check = CheckBox(active=True, size_hint=(0.1, 1))
        action_row.add_widget(self.save_api_check)
        action_row.add_widget(Label(text='Save', size_hint=(0.2, 1)))
        apply_btn = Button(text='Apply', size_hint=(0.3, 1))
        apply_btn.bind(on_press=self.apply_api_key)
        action_row.add_widget(apply_btn)
        action_row.add_widget(Widget())
        cloud_group.add_widget(action_row)

        left_content.add_widget(cloud_group)

        # Cloud model selector
        self.model_selector = CloudModelSelector(
            app_ref=self, size_hint=(1, None), height='120dp'
        )
        self.model_selector.remove_requested = self.remove_custom_cloud_model
        left_content.add_widget(self.model_selector)

        # Chunk size
        chunk_layout = BoxLayout(
            orientation='horizontal', size_hint=(1, None), height='44dp'
        )
        chunk_layout.add_widget(Label(text='Pages per chunk:', size_hint=(0.4, 1)))
        self.chunk_spinner = Spinner(
            text='2', values=[str(i) for i in range(1, 11)], size_hint=(0.6, 1)
        )
        chunk_layout.add_widget(self.chunk_spinner)
        left_content.add_widget(chunk_layout)

        # Max tokens
        token_layout = BoxLayout(
            orientation='horizontal', size_hint=(1, None), height='44dp'
        )
        token_layout.add_widget(Label(text='Max tokens:', size_hint=(0.4, 1)))
        self.token_slider = Slider(
            min=256, max=16384, value=4096, step=1, size_hint=(0.4, 1)
        )
        self.token_label = Label(text='4096', size_hint=(0.2, 1))
        self.token_slider.bind(
            value=lambda _, val: setattr(self.token_label, 'text', str(int(val)))
        )
        token_layout.add_widget(self.token_slider)
        token_layout.add_widget(self.token_label)
        left_content.add_widget(token_layout)

        # Temperature
        temp_layout = BoxLayout(
            orientation='horizontal', size_hint=(1, None), height='44dp'
        )
        temp_layout.add_widget(Label(text='Temperature:', size_hint=(0.4, 1)))
        self.temp_slider = Slider(
            min=0, max=100, value=20, step=1, size_hint=(0.4, 1)
        )
        self.temp_label = Label(text='0.20', size_hint=(0.2, 1))
        self.temp_slider.bind(
            value=lambda inst, val: setattr(self.temp_label, 'text', f"{val / 100:.2f}")
        )
        temp_layout.add_widget(self.temp_slider)
        temp_layout.add_widget(self.temp_label)
        left_content.add_widget(temp_layout)

        # Concurrent calls
        conc_layout = BoxLayout(
            orientation='horizontal', size_hint=(1, None), height='44dp'
        )
        conc_layout.add_widget(Label(text='Concurrent calls:', size_hint=(0.4, 1)))
        self.concurrent_spinner = Spinner(
            text='2', values=[str(i) for i in range(1, 6)], size_hint=(0.6, 1)
        )
        conc_layout.add_widget(self.concurrent_spinner)
        left_content.add_widget(conc_layout)

        # Clear API keys
        clear_btn = Button(text='🗑 Clear All API Keys', size_hint=(1, None), height='40dp')
        clear_btn.bind(on_press=self.clear_api_keys)
        left_content.add_widget(clear_btn)

        # Include images
        image_check_row = BoxLayout(
            orientation='horizontal', size_hint=(1, None), height='44dp'
        )
        image_check_row.add_widget(Label(text='Include images:', size_hint=(0.6, 1)))
        self.include_images_check = CheckBox(active=True, size_hint=(0.1, 1))
        image_check_row.add_widget(self.include_images_check)
        image_check_row.add_widget(Widget())
        left_content.add_widget(image_check_row)

        left_panel.add_widget(left_content)
        splitter.add_widget(left_panel)

        # ---- Right panel ----
        right_panel = BoxLayout(
            orientation='vertical', padding='10dp', spacing='10dp'
        )

        file_row = BoxLayout(
            orientation='horizontal', size_hint=(1, None), height='44dp'
        )
        self.upload_btn = Button(text='Browse PDF/DOCX', size_hint=(0.4, 1))
        self.upload_btn.bind(on_press=self.upload_file)
        self.file_label = Label(text='No file selected', size_hint=(0.6, 1))
        file_row.add_widget(self.upload_btn)
        file_row.add_widget(self.file_label)
        right_panel.add_widget(file_row)

        self.prompt_input = TextInput(
            text="Create comprehensive notes from the following text...",
            multiline=True, size_hint=(1, 0.2),
        )
        right_panel.add_widget(self.prompt_input)

        self.generate_btn = Button(
            text='✨ Generate Notes', size_hint=(1, None), height='48dp'
        )
        self.generate_btn.bind(on_press=self.start_generation)
        right_panel.add_widget(self.generate_btn)

        self.progress_bar = ProgressBar(max=100, size_hint=(1, None), height='20dp')
        right_panel.add_widget(self.progress_bar)
        self.status_label = Label(text='', size_hint=(1, None), height='20dp')
        right_panel.add_widget(self.status_label)

        self.preview_container = BoxLayout(size_hint=(1, 1))
        self.webview = AndroidWebView(app_ref=self)
        self.preview_container.add_widget(self.webview)
        right_panel.add_widget(self.preview_container)

        save_row = BoxLayout(orientation='horizontal', size_hint=(1, None), height='44dp')
        self.save_pdf_btn = Button(text='💾 Save PDF', disabled=True)
        self.save_pdf_btn.bind(on_press=self.save_pdf)
        self.save_word_btn = Button(text='💾 Save as Word', disabled=True)
        self.save_word_btn.bind(on_press=self.save_word)
        save_row.add_widget(self.save_pdf_btn)
        save_row.add_widget(self.save_word_btn)
        right_panel.add_widget(save_row)

        splitter.add_widget(right_panel)
        root.add_widget(splitter)

        feedback_btn = Button(text='💬 Feedback', size_hint=(1, None), height='36dp')
        feedback_btn.bind(on_press=self.show_feedback)
        root.add_widget(feedback_btn)

        # Initialise
        self.start_license_flow()
        self.load_settings()

        # Ensure cloud model dropdown is always populated on first launch.
        # If load_settings() restored the same service that was already the
        # default, the Spinner.text bind will not re-fire, so we schedule an
        # explicit call once the event loop is running.
        Clock.schedule_once(
            lambda dt: self.on_service_changed(
                self.service_spinner, self.service_spinner.text
            ),
            0,
        )

        return root

    # ---- Lifecycle ----
    def on_pause(self):
        """Must return True so Android keeps the process alive in background."""
        self.save_settings()
        return True

    def on_stop(self):
        """Called on explicit exit — persist settings."""
        self.save_settings()

    # ---- License & Activation ----
    def start_license_flow(self):
        lic = self.license_manager.load_license()
        if not lic:
            self.license_status = 'invalid'
            self.show_activation_dialog()
            return
        self.license_status = lic.get('status', 'pending')
        self.update_ui_for_license_status()
        if self.license_status == 'pending':
            Clock.schedule_interval(self.check_license_status, 30)
        else:
            Clock.schedule_interval(self.check_license_status, 14400)
        Clock.schedule_interval(self.sync_pending_requests, 300)
        Clock.schedule_once(self.sync_pending_requests, 2)

    def show_activation_dialog(self):
        content = BoxLayout(orientation='vertical', padding='10dp', spacing='10dp')
        content.add_widget(
            Label(text='🔑 Activate Your License', size_hint=(1, None), height='40dp')
        )

        email_row = BoxLayout(orientation='horizontal', size_hint=(1, None), height='44dp')
        email_row.add_widget(Label(text='Email:', size_hint=(0.3, 1)))
        self.activation_email = TextInput(hint_text='you@example.com', multiline=False)
        email_row.add_widget(self.activation_email)
        content.add_widget(email_row)

        content.add_widget(
            Label(text='💳 Price: 200 ETB\n🏦 CBE: 1000713428462\n📱 Telebirr: 0974883807')
        )

        receipt_row = BoxLayout(orientation='horizontal', size_hint=(1, None), height='44dp')
        receipt_row.add_widget(Label(text='Receipt:', size_hint=(0.3, 1)))
        self.receipt_status = Label(text='No file', size_hint=(0.4, 1))
        browse_btn = Button(text='Browse', size_hint=(0.3, 1))
        browse_btn.bind(on_press=self.upload_receipt)
        receipt_row.add_widget(self.receipt_status)
        receipt_row.add_widget(browse_btn)
        content.add_widget(receipt_row)
        self.receipt_path = None

        btn_row = BoxLayout(orientation='horizontal', size_hint=(1, None), height='44dp')
        cancel_btn   = Button(text='Cancel')
        activate_btn = Button(text='Submit Request')
        cancel_btn.bind(on_press=lambda x: popup.dismiss())
        activate_btn.bind(on_press=lambda x: self.submit_activation(popup))
        btn_row.add_widget(cancel_btn)
        btn_row.add_widget(activate_btn)
        content.add_widget(btn_row)

        popup = Popup(
            title='Activation', content=content,
            size_hint=(0.9, 0.8), auto_dismiss=False,
        )
        self.activation_popup = popup
        popup.open()

    def upload_receipt(self, instance):
        content     = BoxLayout(orientation='vertical')
        filechooser = FileChooserListView(filters=['*.png', '*.jpg', '*.jpeg', '*.pdf'])
        content.add_widget(filechooser)
        btn_layout = BoxLayout(size_hint=(1, None), height='44dp')
        select_btn = Button(text='Select')
        cancel_btn = Button(text='Cancel')
        btn_layout.add_widget(select_btn)
        btn_layout.add_widget(cancel_btn)
        content.add_widget(btn_layout)
        popup = Popup(title='Choose Receipt', content=content, size_hint=(0.9, 0.9))
        select_btn.bind(
            on_press=lambda x: self._receipt_selected(popup, filechooser.selection)
        )
        cancel_btn.bind(on_press=popup.dismiss)
        popup.open()

    def _receipt_selected(self, popup, selection):
        if selection:
            path = selection[0]
            if os.path.getsize(path) > MAX_RECEIPT_SIZE:
                self.show_popup('Error', 'File exceeds 10 MB limit.')
                self.receipt_path        = None
                self.receipt_status.text = 'No file'
            else:
                self.receipt_path        = path
                self.receipt_status.text = os.path.basename(path)
        popup.dismiss()

    def submit_activation(self, popup):
        email = self.activation_email.text.strip()
        if not email:
            self.show_popup('Error', 'Please enter your email.')
            return
        if not self.receipt_path:
            self.show_popup('Error', 'Please upload your receipt.')
            return
        app_id = get_embedded_license_key()
        if not app_id:
            self.show_popup('Error', 'No embedded app ID.')
            return
        lm   = self.license_manager
        hwid = lm.get_hwid()
        lm.save_pending_activation(email, hwid, self.receipt_path, app_id)
        placeholder_key = f"pending_{uuid.uuid4().hex[:8]}"
        lm.save_license({
            'key':          placeholder_key,
            'email':        email,
            'status':       'pending',
            'requested_at': datetime.now().isoformat(),
        })
        popup.dismiss()
        self.license_status = 'pending'
        self.update_ui_for_license_status()
        self.start_license_flow()

    def check_license_status(self, dt=None):
        lic = self.license_manager.load_license()
        if not lic:
            return
        key  = lic.get('key')
        hwid = self.license_manager.get_hwid()
        try:
            signed   = sign_request({"license_key": key, "hwid": hwid})
            response = requests.post(LICENSE_CHECK_URL, json=signed, timeout=5)
            if response.status_code == 200:
                data = response.json()
                if self.license_status == 'pending' and data.get('valid'):
                    self.license_status = 'active'
                    self.license_manager.save_license({**lic, 'status': 'active'})
                    self.update_ui_for_license_status()
                    self.show_popup('Approved!', 'Your license is now active.')
                elif self.license_status == 'active' and not data.get('valid'):
                    self.license_status = 'invalid'
                    self.show_popup('License Revoked', 'Your license is no longer valid.')
                    self.stop()
        except Exception:
            pass

    def sync_pending_requests(self, dt=None):
        lm    = self.license_manager
        queue = lm.get_pending_requests()
        if not queue:
            return
        for i, req in enumerate(queue):
            if 'license_key' in req and req['license_key']:
                continue
            data  = {
                'app_id': req['app_id'],
                'email':  req['email'],
                'hwid':   req['hwid'],
            }
            files        = {}
            receipt_path = req.get('receipt_path')
            if receipt_path and os.path.exists(receipt_path):
                files['receipt'] = (
                    os.path.basename(receipt_path),
                    open(receipt_path, 'rb'),
                    'application/octet-stream',
                )
            try:
                signed = sign_request(data)
                resp   = requests.post(
                    LICENSE_SERVER_URL, data=signed, files=files, timeout=10
                )
                if files:
                    files['receipt'][1].close()
                if resp.status_code == 200:
                    result = resp.json()
                    if result.get('success') and result.get('license_key'):
                        lm.save_license({
                            'key':          result['license_key'],
                            'email':        req['email'],
                            'status':       'pending',
                            'requested_at': datetime.now().isoformat(),
                        })
                        lm.delete_pending_request(i)
                        break
            except Exception:
                break

    def update_ui_for_license_status(self):
        if self.license_status == 'active':
            self.set_controls_enabled(True)
            self.status_bar.text = '✅ License active – ready.'
        elif self.license_status == 'pending':
            self.set_controls_enabled(False)
            self.status_bar.text = '⏳ Waiting for license approval...'
        else:
            self.set_controls_enabled(False)
            self.status_bar.text = '❌ License invalid or revoked.'

    def set_controls_enabled(self, enabled: bool):
        """
        Enable or disable all interactive controls.

        FIX D (Kivy 2.3.1): setting .disabled on a parent BoxLayout blocks
        incoming touch events at the parent level but does NOT propagate the
        .disabled flag to child widgets. A TextInput child remains writable
        via the soft-keyboard and a Button remains clickable via direct
        programmatic call. CloudModelSelector.set_input_disabled() is called
        here to explicitly disable its TextInput and dropdown Button so they
        cannot be interacted with in any way while the license is pending.
        """
        self.upload_btn.disabled         = not enabled
        self.generate_btn.disabled       = not enabled
        self.prompt_input.disabled       = not enabled
        self.chunk_spinner.disabled      = not enabled
        self.token_slider.disabled       = not enabled
        self.temp_slider.disabled        = not enabled
        self.concurrent_spinner.disabled = not enabled
        self.cloud_checkbox.disabled     = not enabled
        # FIX D: disable CloudModelSelector children individually
        self.model_selector.set_input_disabled(not enabled)

    # ---- UI helpers ----
    def on_service_changed(self, spinner, text):
        service = text.lower().replace(' ', '')
        if service == 'googleaistudio':
            service = 'google'
        self.update_cloud_models(service)
        self.update_saved_keys_spinner()

    def update_cloud_models(self, service):
        default = self.get_cloud_models(service)
        custom  = self.custom_cloud_models.get(service, [])
        self.model_selector.set_models(default, custom, service)

    def get_cloud_models(self, service):
        if service == 'openai':
            return ['gpt-4o-mini', 'gpt-3.5-turbo', 'gpt-4o']
        elif service == 'groq':
            return ['llama-3.3-70b-versatile', 'qwen/qwen3-32b']
        elif service == 'google':
            return [
                'gemini-3.1-flash-lite', 'gemini-3.5-flash',
                'google/gemma-4-31b-it', 'google/gemma-4-26b-a4b-it',
            ]
        elif service == 'openrouter':
            return [
                'openai/gpt-oss-120b:free', 'google/gemma-3-12b:free',
                'google/gemma-4-26b-a4b-it', 'google/gemma-4-31b-it',
            ]
        else:
            return []

    def toggle_key_visibility(self, checkbox, value):
        self.api_key_input.password = not value

    def update_saved_keys_spinner(self):
        service = self.service_spinner.text.lower().replace(' ', '')
        if service == 'googleaistudio':
            service = 'google'
        lm    = self.license_manager
        keys  = lm.list_named_api_keys()
        names = [name for name, data in keys.items() if data.get('service') == service]
        if names:
            self.saved_keys_spinner.values = names
            if self.saved_keys_spinner.text not in names:
                self.saved_keys_spinner.text = names[0]
        else:
            self.saved_keys_spinner.values = ['None']
            self.saved_keys_spinner.text   = 'None'

    def on_saved_key_selected(self, spinner, text):
        if text == 'None':
            return
        data = self.license_manager.get_api_key_by_name(text)
        if data:
            self.api_key_input.text     = data['api_key']
            self.api_key_input.password = not self.show_key_check.active

    def apply_api_key(self, instance):
        key = self.api_key_input.text.strip()
        if not key:
            self.show_popup('Missing API Key', 'Please enter a key.')
            return
        service = self.service_spinner.text.lower().replace(' ', '')
        if service == 'googleaistudio':
            service = 'google'
        if self.save_api_check.active:
            self._ask_key_name_and_save(key, service)
        else:
            self.api_config            = {'name': None, 'api_key': key, 'service': service}
            self.cloud_checkbox.active = True
            self.status_bar.text       = f"☁️ Using {SERVICE_DISPLAY.get(service, service)} API"

    def _ask_key_name_and_save(self, key, service):
        content    = BoxLayout(orientation='vertical', spacing='10dp')
        lbl        = Label(text='Enter a name for this API key:')
        name_input = TextInput(multiline=False)
        content.add_widget(lbl)
        content.add_widget(name_input)
        btn = Button(text='Save', size_hint=(1, None), height='44dp')
        content.add_widget(btn)
        popup = Popup(title='Name Your Key', content=content, size_hint=(0.8, 0.4))
        btn.bind(
            on_press=lambda x: self._save_named_key(popup, name_input.text, key, service)
        )
        popup.open()

    def _save_named_key(self, popup, name, key, service):
        if not name.strip():
            self.show_popup('Error', 'Name cannot be empty.')
            return
        lm = self.license_manager
        lm.save_named_api_key(name.strip(), key, service)
        self.api_config            = {'name': name.strip(), 'api_key': key, 'service': service}
        self.cloud_checkbox.active = True
        self.update_cloud_models(service)
        self.update_saved_keys_spinner()
        self.save_settings()
        popup.dismiss()
        self.status_bar.text = f"☁️ Using {SERVICE_DISPLAY.get(service, service)} API"

    def remove_custom_cloud_model(self, service, model_name):
        if (service in self.custom_cloud_models
                and model_name in self.custom_cloud_models[service]):
            self.custom_cloud_models[service].remove(model_name)
            self.update_cloud_models(service)
            self.save_settings()

    def clear_api_keys(self, instance):
        content    = BoxLayout(orientation='vertical')
        btn_layout = BoxLayout(
            orientation='horizontal', size_hint=(1, None), height='44dp'
        )
        yes_btn = Button(text='Yes')
        no_btn  = Button(text='No')
        btn_layout.add_widget(yes_btn)
        btn_layout.add_widget(no_btn)
        content.add_widget(Label(text='Delete ALL saved API keys?'))
        content.add_widget(btn_layout)
        popup = Popup(
            title='Confirm', content=content,
            size_hint=(0.7, 0.3), auto_dismiss=False,
        )
        yes_btn.bind(on_press=lambda x: self._do_clear_keys(popup))
        no_btn.bind(on_press=popup.dismiss)
        popup.open()

    def _do_clear_keys(self, popup):
        self.license_manager.delete_all_api_keys()
        self.api_config            = None
        self.cloud_checkbox.active = False
        self.update_saved_keys_spinner()
        self.api_key_input.text = ''
        self.save_settings()
        popup.dismiss()
        self.show_popup('Cleared', 'All saved API keys removed.')

    # ---- File handling ----
    def upload_file(self, instance):
        content     = BoxLayout(orientation='vertical')
        filechooser = FileChooserListView(filters=['*.pdf', '*.docx'])
        content.add_widget(filechooser)
        btn_layout = BoxLayout(size_hint=(1, None), height='44dp')
        select_btn = Button(text='Select')
        cancel_btn = Button(text='Cancel')
        btn_layout.add_widget(select_btn)
        btn_layout.add_widget(cancel_btn)
        content.add_widget(btn_layout)
        popup = Popup(title='Choose Document', content=content, size_hint=(0.9, 0.9))
        select_btn.bind(
            on_press=lambda x: self._file_selected(popup, filechooser.selection)
        )
        cancel_btn.bind(on_press=popup.dismiss)
        popup.open()

    def _file_selected(self, popup, selection):
        if selection:
            self.temp_input_path = selection[0]
            self.file_label.text = os.path.basename(selection[0])
            popup.dismiss()

    # ---- Generation ----
    def start_generation(self, instance):
        if self.license_status != 'active':
            self.show_popup('License Pending', 'Please wait for license approval.')
            return
        if not self.temp_input_path:
            self.show_popup('No Document', 'Please select a PDF/DOCX file.')
            return
        if self.cloud_checkbox.active:
            if not self.api_config:
                self.show_popup(
                    'Missing API Key',
                    'Cloud API is enabled but no key has been set.',
                )
                return
            api_config = self.api_config
        else:
            api_config = None

        model = self.model_selector.get_selected_model()
        if not model:
            self.show_popup('No Model', 'Please specify a model.')
            return

        self.generate_btn.disabled = True
        self.progress_bar.value    = 0
        self.status_label.text     = 'Reading document...'

        try:
            if self.temp_input_path.lower().endswith('.docx'):
                docx_texts = self.extract_text_from_docx(self.temp_input_path)
                page_data  = [{'text': t, 'images': []} for t in docx_texts]
                self.status_label.text = f'Loaded {len(page_data)} sections from DOCX.'
            else:
                page_data = self.extract_text_from_pdf(self.temp_input_path)
                self.status_label.text = f'Loaded {len(page_data)} pages.'

            chunk_size = int(self.chunk_spinner.text)
            chunks     = self.chunk_pages(page_data, chunk_size)
            self.status_label.text = (
                f'Loaded {len(page_data)} pages/sections, {len(chunks)} chunks.'
            )

            if not self.include_images_check.active:
                chunks = [(s, e, t, []) for s, e, t, _ in chunks]

        except Exception as e:
            self.show_popup('Error', f'Failed to read document: {e}')
            self.generate_btn.disabled = False
            return

        service_key          = api_config.get('service', '') if api_config else ''
        rate_limiter         = None
        request_rate_limiter = None

        if service_key in ('groq', 'openai'):
            rate_limiter = TokenBucket(30000)
        if service_key == 'google':
            request_rate_limiter = RequestRateLimiter(15)

        concurrent_calls = (
            1 if self.cloud_checkbox.active else int(self.concurrent_spinner.text)
        )

        self.worker = AIWorker(
            chunks, model, self.prompt_input.text,
            int(self.token_slider.value), self.temp_slider.value / 100.0,
            concurrent_calls,
            api_config           = api_config,
            rate_limiter         = rate_limiter,
            request_rate_limiter = request_rate_limiter,
            callback_progress    = self.on_progress,
            callback_status      = self.on_status,
            callback_finished    = self.on_generation_finished,
            callback_error       = self.on_error,
        )
        self.worker.start()

    def on_progress(self, value):
        @mainthread
        def _():
            self.progress_bar.value = value
        _()

    def on_status(self, text):
        @mainthread
        def _():
            self.status_label.text = text
        _()

    def on_error(self, msg):
        @mainthread
        def _():
            self.show_popup('Error', msg)
            self.generate_btn.disabled = False
        _()

    def on_generation_finished(self, results):
        @mainthread
        def _():
            self.notes_results = results
            full_md   = "\n\n".join(notes for _, _, notes in results)
            full_md   = sanitize_math_delimiters(full_md)
            full_md   = clean_google_meta(full_md)
            full_md   = normalize_headings(full_md, level=3)
            full_md   = fix_markdown_lists(full_md)
            html_body = markdown.markdown(
                full_md, extensions=['fenced_code', 'tables', 'codehilite']
            )
            template        = self.get_html_template()
            self.final_html = template.replace('{{CONTENT}}', html_body)
            self.webview.load_html(
                self.final_html,
                base_url='https://cdn.jsdelivr.net/npm/mathjax@3/es5/',
            )
            self.status_label.text     = '✅ AI processing complete!'
            self.progress_bar.value    = 0
            self.generate_btn.disabled = False
            self.save_pdf_btn.disabled  = False
            self.save_word_btn.disabled = False
        _()

    def get_html_template(self):
        return """<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<title>Notes</title>
<script src="https://cdn.jsdelivr.net/npm/mathjax@3/es5/tex-mml-chtml.js"></script>
<script>
  window.MathJax = {
    tex: {
      inlineMath: [['$','$']],
      displayMath: [['$$','$$']]
    }
  };
</script>
<style>
  body { font-family: 'Noto Sans', 'Segoe UI', sans-serif; line-height: 1.6; margin: 2em; }
  table { border-collapse: collapse; width: 100%; }
  th, td { border: 1px solid #ddd; padding: 8px; }
  th { background: #f2f2f2; }
  @media print {
    p, li, table, tr, th, td, pre, blockquote, h1, h2, h3, h4, h5, h6 {
      page-break-inside: avoid;
    }
  }
</style>
</head>
<body>{{CONTENT}}</body>
</html>"""

    # ---- Text extraction ----
    def extract_text_from_pdf(self, path):
        """Extract text (and optionally page images) from a PDF."""
        reader      = PdfReader(path)
        pages_text  = [page.extract_text() or "" for page in reader.pages]
        total_pages = len(pages_text)

        page_images = []
        try:
            File                  = autoclass('java.io.File')
            ParcelFileDescriptor  = autoclass('android.os.ParcelFileDescriptor')
            PdfRenderer           = autoclass('android.graphics.pdf.PdfRenderer')
            Bitmap                = autoclass('android.graphics.Bitmap')
            ByteArrayOutputStream = autoclass('java.io.ByteArrayOutputStream')

            pdf_file = File(path)
            pfd      = ParcelFileDescriptor.open(
                pdf_file, ParcelFileDescriptor.MODE_READ_ONLY
            )
            renderer = PdfRenderer(pfd)

            for page_num in range(renderer.getPageCount()):
                page          = renderer.openPage(page_num)
                target_width  = 1654   # A4 at 200 dpi
                target_height = 2339
                bitmap = Bitmap.createBitmap(
                    target_width, target_height, Bitmap.Config.ARGB_8888
                )
                page.render(
                    bitmap, None, None, PdfRenderer.Page.RENDER_MODE_FOR_DISPLAY
                )
                stream    = ByteArrayOutputStream()
                bitmap.compress(Bitmap.CompressFormat.PNG, 80, stream)
                img_bytes = stream.toByteArray()
                img_b64   = base64.b64encode(bytes(img_bytes)).decode('utf-8')
                page_images.append(img_b64)
                bitmap.recycle()
                page.close()

            renderer.close()
            pfd.close()
        except Exception as e:
            print(f"Android PDF rendering failed (images will be skipped): {e}")

        page_data = []
        for i in range(total_pages):
            img = page_images[i] if i < len(page_images) else None
            page_data.append({
                'text':   pages_text[i].strip(),
                'images': [img] if img else [],
            })
        return page_data

    def extract_text_from_docx(self, path):
        doc        = DocxDocument(path)
        paragraphs = [p.text.strip() for p in doc.paragraphs if p.text.strip()]
        return paragraphs if paragraphs else ["[No text found]"]

    def chunk_pages(self, page_texts, chunk_size):
        """
        page_texts — list of dicts: {'text': str, 'images': list}.
        Returns list of (start_page, end_page, combined_text, combined_images).
        """
        chunks = []
        for i in range(0, len(page_texts), chunk_size):
            chunk_slice     = page_texts[i:i + chunk_size]
            start           = i + 1
            end             = min(i + chunk_size, len(page_texts))
            combined_text   = "\n\n".join(p['text'] for p in chunk_slice)
            combined_images = []
            for p in chunk_slice:
                combined_images.extend(p['images'])
            chunks.append((start, end, combined_text, combined_images))
        return chunks

    # ---- Save / Export ----
    def save_pdf(self, instance):
        if not self.final_html:
            return
        self._temp_pdf_path = os.path.join(tempfile.gettempdir(), 'ai_notes.pdf')
        self.webview.print_to_pdf(self._temp_pdf_path, callback=self._on_pdf_saved)

    def _on_pdf_saved(self, success):
        if success:
            self._share_file(self._temp_pdf_path, 'application/pdf')
        else:
            self.show_popup('Error', 'PDF generation failed.')

    def save_word(self, instance):
        if not self.final_html:
            return
        self.webview.get_html(lambda html: self._save_word_file(html))

    def _save_word_file(self, html):
        if not html:
            self.show_popup('Error', 'Could not retrieve HTML.')
            return
        temp_path = os.path.join(tempfile.gettempdir(), 'ai_notes.doc')
        with open(temp_path, 'w', encoding='utf-8') as f:
            f.write(html)
        self._share_file(temp_path, 'application/msword')

    def _share_file(self, path, mime_type):
        if not ON_ANDROID:
            self.show_popup('File Saved', f'File saved to:\n{path}')
            return
        try:
            Intent = autoclass('android.content.Intent')
            Uri = autoclass('android.net.Uri')
            File = autoclass('java.io.File')
            PythonActivity = autoclass('org.kivy.android.PythonActivity')
            intent = Intent(Intent.ACTION_SEND)
            intent.setType(mime_type)
            uri = Uri.fromFile(File(path))
            intent.putExtra(Intent.EXTRA_STREAM, uri)
            PythonActivity.mActivity.startActivity(Intent.createChooser(intent, "Share file"))
        except Exception as e:
            self.show_popup('Share Error', str(e))

    # ---- Settings ----
    def _settings_path(self):
        return os.path.join(
            os.path.expanduser("~"), ".pdf_notes_maker", "user_settings.json"
        )

    def save_settings(self):
        try:
            settings = {
                'prompt':                 self.prompt_input.text,
                'chunk_size':             int(self.chunk_spinner.text),
                'concurrent_calls':       int(self.concurrent_spinner.text),
                'use_cloud':              self.cloud_checkbox.active,
                'cloud_model_text':       self.model_selector.get_selected_model(),
                'service':                self.service_spinner.text,
                'active_api_key_name':    self.api_config.get('name') if self.api_config else None,
                'active_api_key_service': self.api_config.get('service') if self.api_config else None,
                'custom_cloud_models':    self.custom_cloud_models,
            }
            os.makedirs(os.path.dirname(self._settings_path()), exist_ok=True)
            with open(self._settings_path(), 'w', encoding='utf-8') as f:
                json.dump(settings, f, indent=2)
        except Exception:
            pass

    def load_settings(self):
        self._restoring_settings = True
        if not os.path.exists(self._settings_path()):
            self._restoring_settings = False
            return
        try:
            with open(self._settings_path(), 'r', encoding='utf-8') as f:
                settings = json.load(f)
            self.prompt_input.text       = settings.get('prompt', self.prompt_input.text)
            self.chunk_spinner.text      = str(settings.get('chunk_size', 2))
            self.concurrent_spinner.text = str(settings.get('concurrent_calls', 2))
            self.cloud_checkbox.active   = settings.get('use_cloud', False)
            service                      = settings.get('service', 'Google AI Studio')
            self.service_spinner.text    = service
            self.custom_cloud_models     = settings.get('custom_cloud_models', {})
            cloud_model = settings.get('cloud_model_text', '')
            if cloud_model:
                self.model_selector.text_input.text = cloud_model
            api_name    = settings.get('active_api_key_name')
            api_service = settings.get('active_api_key_service', 'google')
            if api_name and self.cloud_checkbox.active:
                key_data = self.license_manager.get_api_key_by_name(api_name)
                if key_data and key_data.get('service') == api_service:
                    self.api_config = {
                        'name':    api_name,
                        'api_key': key_data['api_key'],
                        'service': api_service,
                    }
                    self.api_key_input.text     = key_data['api_key']
                    self.api_key_input.password = True
                    self.update_cloud_models(api_service)
                    self.update_saved_keys_spinner()
        except Exception:
            pass
        self.model_selector._warned_non_default = True
        self._restoring_settings = False

    # ---- Feedback ----
    def show_feedback(self, instance):
        self.show_popup('Feedback', '📱 Telegram: @SL_customer_service2bot')

    def show_popup(self, title, message, ok_callback=None, cancel_callback=None):
        content = BoxLayout(orientation='vertical', padding='10dp')
        content.add_widget(Label(text=message))
        btn = Button(text='OK', size_hint=(1, None), height='44dp')
        content.add_widget(btn)
        popup = Popup(title=title, content=content, size_hint=(0.7, 0.4))
        if ok_callback:
            btn.bind(on_press=lambda x: (popup.dismiss(), ok_callback()))
        else:
            btn.bind(on_press=popup.dismiss)
        popup.open()


if __name__ == '__main__':
    PDFNotesMakerApp().run()

