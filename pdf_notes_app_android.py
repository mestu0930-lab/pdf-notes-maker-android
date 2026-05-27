# pdf_notes_app_android.py
# Android-compatible version using Kivy framework
# Removed: Ollama/local models, PyQt6 desktop UI, QWebEngineView
# Kept: All AI generation logic, cloud API integration, license management, export functionality

import os
import sys
import asyncio
import tempfile
import time
import hmac
import hashlib
import json
import re
import threading
import collections
from datetime import datetime
from io import BytesIO

import httpx
import requests
import markdown
from pypdf import PdfReader
from openai import AsyncOpenAI
from docx import Document as DocxDocument

from kivy.app import App
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.gridlayout import GridLayout
from kivy.uix.scrollview import ScrollView
from kivy.uix.label import Label
from kivy.uix.button import Button
from kivy.uix.textinput import TextInput
from kivy.uix.spinner import Spinner
from kivy.uix.checkbox import CheckBox
from kivy.uix.progressbar import ProgressBar
from kivy.uix.popup import Popup
from kivy.uix.filechooser import FileChooserListView
from kivy.uix.image import Image
from kivy.garden.matplotlib.backend_kivyagg import FigureCanvasKivyAgg
from kivy.core.window import Window
from kivy.uix.statusbar import StatusBar
from kivy.uix.spinner import Spinner
from kivy.uix.togglebutton import ToggleButton
from kivy.uix.slider import Slider
from kivy.uix.popup import Popup
from kivy.uix.label import Label
from kivy.uix.scrollview import ScrollView
from kivy.threading import thread_task
from kivy.clock import Clock, mainthread

from license_manager import LicenseManager, get_embedded_license_key

# ========== Configuration ==========
SIGNING_SECRET = b'\xe6\xc9\xc4!\xaf\xe5l\x98RY\xdf\xf9z\xa3\x1e\xef'
LICENSE_SERVER_URL = "https://mestu0930.pythonanywhere.com/api/activate"
LICENSE_CHECK_URL = "https://mestu0930.pythonanywhere.com/api/check_license"

SERVICE_DISPLAY = {
    'openai': 'OpenAI',
    'groq': 'Groq',
    'google': 'Google AI Studio',
    'openrouter': 'OpenRouter'
}

SERVICE_ENDPOINTS = {
    'openai': 'https://api.openai.com/v1',
    'groq': 'https://api.groq.com/openai/v1',
    'google': 'https://generativelanguage.googleapis.com/v1beta/openai/',
    'openrouter': 'https://openrouter.ai/api/v1'
}

# ========== Utility Functions ==========

def sign_request(data):
    """Sign request data for license server validation."""
    secret = SIGNING_SECRET
    timestamp = str(int(time.time()))
    data_json = json.dumps(data)
    payload = data_json + timestamp
    signature = hmac.new(secret, payload.encode('utf-8'), hashlib.sha256).hexdigest()
    return {'data': data_json, 'timestamp': timestamp, 'signature': signature}

def get_android_storage_path():
    """Get appropriate storage path for Android app."""
    try:
        from kivy.garden.android.permissions import request_permissions, Permission
        from android.storage import primary_external_storage_path
        return primary_external_storage_path()
    except:
        return os.path.expanduser("~")

def log_error(msg):
    """Log errors to file."""
    log_dir = os.path.join(get_android_storage_path(), ".pdf_notes_maker")
    os.makedirs(log_dir, exist_ok=True)
    log_path = os.path.join(log_dir, "error.log")
    try:
        with open(log_path, 'a', encoding='utf-8') as f:
            f.write(f"{datetime.now().isoformat()}: {msg}\n")
    except:
        pass

def extract_text_from_docx(docx_path):
    """Extract text from DOCX file and divide into pseudo-pages."""
    doc = DocxDocument(docx_path)
    paragraphs = [para.text for para in doc.paragraphs]
    pseudo_pages = []
    current_page = ""
    for para in paragraphs:
        if len(current_page) + len(para) > 3000 and current_page:
            pseudo_pages.append(current_page)
            current_page = para
        else:
            current_page += "\n" + para if current_page else para
    if current_page:
        pseudo_pages.append(current_page)
    return pseudo_pages

# ========== Markdown Cleaning Functions ==========

def clean_google_meta(md_text):
    """Remove Google's <thought> tags from response."""
    tag = '</thought>'
    idx = md_text.rfind(tag)
    if idx != -1:
        return md_text[idx + len(tag):].strip()
    return md_text

def normalize_headings(markdown_text, level=3):
    """Normalize all headings to specified level."""
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
    """Ensure proper spacing before list items."""
    lines = text.splitlines()
    new_lines = []
    for i, line in enumerate(lines):
        stripped = line.lstrip()
        if '$' in stripped:
            new_lines.append(line)
            continue
        if (stripped.startswith('- ') or stripped.startswith('* ') or re.match(r'\d+\. ', stripped)) and i > 0:
            prev = lines[i-1].strip()
            if prev != '' and not prev.startswith('-') and not prev.startswith('*') and not re.match(r'\d+\.', prev):
                new_lines.append('')
        new_lines.append(line)
    return '\n'.join(new_lines)

def sanitize_math_delimiters(markdown_text):
    """Convert math delimiters to consistent $...$ and $$...$$ format."""
    text = re.sub(r'`(\$[^`]+\$)`', r'\1', markdown_text)
    text = re.sub(r'`(\$\$[^`]+\$\$)`', r'\1', text)
    text = re.sub(r'\\\((.*?)\\\)', r'$\1$', text, flags=re.DOTALL)
    text = re.sub(r'\\\[(.*?)\\\]', r'$$\1$$', text, flags=re.DOTALL)
    return text

def clean_markdown_output(md_text):
    """Apply all markdown cleaning passes."""
    md_text = clean_google_meta(md_text)
    md_text = sanitize_math_delimiters(md_text)
    md_text = normalize_headings(md_text, level=3)
    md_text = fix_markdown_lists(md_text)
    return md_text

# ========== Token Bucket Rate Limiter ==========

class TokenBucket:
    """Rate limiter using token bucket algorithm."""
    def __init__(self, tokens_per_minute):
        self.capacity = tokens_per_minute
        self.tokens = tokens_per_minute
        self.rate = tokens_per_minute / 60.0
        self.last_refill = time.monotonic()

    def _refill(self):
        now = time.monotonic()
        elapsed = now - self.last_refill
        self.tokens = min(self.capacity, self.tokens + elapsed * self.rate)
        self.last_refill = now

    def consume(self, tokens):
        self._refill()
        if tokens > self.tokens:
            deficit = tokens - self.tokens
            sleep_time = deficit / self.rate
            time.sleep(sleep_time)
            self._refill()
        self.tokens -= tokens

class RequestRateLimiter:
    """Sliding‑window rate limiter for requests per minute (RPM)."""

    def __init__(self, rpm: int):
        self.rpm = rpm
        self.window = 60.0          # seconds
        self.timestamps = collections.deque()

    async def acquire(self):
        """Wait until a request can be made without exceeding the RPM limit."""
        now = time.monotonic()
        # Remove timestamps older than the window
        while self.timestamps and now - self.timestamps[0] > self.window:
            self.timestamps.popleft()

        if len(self.timestamps) >= self.rpm:
            # Calculate how long to wait until the oldest request expires
            wait_time = self.timestamps[0] + self.window - now + 0.1
            if wait_time > 0:
                await asyncio.sleep(wait_time)
            # After waiting, clean up again
            now = time.monotonic()
            while self.timestamps and now - self.timestamps[0] > self.window:
                self.timestamps.popleft()

        self.timestamps.append(time.monotonic())

# ========== AI Generation Worker ==========

class AIGenerationWorker:
    """Handles async AI generation for document chunks."""
    
    def __init__(self, api_key, service, model, callback_progress, callback_complete, request_rate_limiter=None):
        self.api_key = api_key
        self.service = service.lower()
        self.model = model
        self.callback_progress = callback_progress
        self.callback_complete = callback_complete
        self.rate_limiter = None
        self.request_rate_limiter = request_rate_limiter
        
        if self.service in ['groq', 'openai', 'google']:
            self.rate_limiter = TokenBucket(tokens_per_minute=6000)
    
    def _create_client(self):
        """Create AsyncOpenAI client with appropriate endpoint."""
        endpoint = SERVICE_ENDPOINTS.get(self.service, SERVICE_ENDPOINTS['openai'])
        return AsyncOpenAI(api_key=self.api_key, base_url=endpoint)
    
    async def generate_notes_for_chunk(self, start_page, end_page, text, system_prompt, max_tokens, temperature):
        """Generate notes for a single chunk with retry logic."""
        client = self._create_client()
        
        for attempt in range(3):
            try:
                if self.rate_limiter:
                    self.rate_limiter.consume(1)
                    
                # ---- Wait for RPM limiter (Google AI Studio) ----
                if self.request_rate_limiter:
                    await self.request_rate_limiter.acquire()
                # ------------------------------------------------
                
                response = await client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": text}
                    ],
                    temperature=temperature / 100.0,
                    max_tokens=max_tokens,
                    top_p=0.9
                )
                
                generated_text = response.choices[0].message.content
                return {
                    'start_page': start_page,
                    'end_page': end_page,
                    'notes': clean_markdown_output(generated_text)
                }
            
            except Exception as e:
                if attempt == 2:
                    log_error(f"Failed to generate notes for pages {start_page}-{end_page}: {str(e)}")
                    return {
                        'start_page': start_page,
                        'end_page': end_page,
                        'notes': f"⚠️ Error generating notes: {str(e)}"
                    }
                await asyncio.sleep(2 ** attempt)
    
    async def process_all_chunks(self, chunks, system_prompt, max_tokens, temperature, concurrent_calls):
        """Process all chunks concurrently."""
        semaphore = asyncio.Semaphore(concurrent_calls)
        
        async def bounded_generate(chunk):
            async with semaphore:
                result = await self.generate_notes_for_chunk(
                    chunk[0], chunk[1], chunk[2], system_prompt, max_tokens, temperature
                )
                self.callback_progress((len(chunks) - len([c for c in chunks if c not in [chunk]])) / len(chunks))
                return result
        
        results = await asyncio.gather(*[bounded_generate(chunk) for chunk in chunks])
        return results

# ========== Main Android App ==========

class PDFNotesMakerAndroid(App):
    """Main Kivy application for PDF Notes Maker on Android."""
    
    def __init__(self):
        super().__init__()
        self.title = 'PDF Notes Maker'
        Window.size = (400, 800)
        
        # State
        self.temp_input_path = None
        self.license_status = 'invalid'
        self.api_config = None
        self.custom_cloud_models = {}
        self.generated_html = None
        self.exported_pdf_path = None
        self.exported_docx_path = None
        
        # Initialize license manager
        self.lm = LicenseManager()
    
    def build(self):
        """Build the main UI."""
        # Check license on startup
        lic = self.lm.load_license()
        if not lic or lic.get('status') != 'active':
            self.license_status = 'invalid'
            self.show_license_error_screen()
            return BoxLayout(orientation='vertical')
        
        self.license_status = 'active'
        
        # Load settings
        self.load_settings()
        
        # Build main layout
        main_layout = BoxLayout(orientation='vertical', padding=10, spacing=10)
        
        # ===== TOP SECTION: File Input =====
        file_section = BoxLayout(orientation='vertical', size_hint_y=0.12, spacing=5)
        file_section.add_widget(Label(text='Document Input', size_hint_y=0.3, bold=True))
        
        file_button = Button(text='Select PDF or DOCX', size_hint_y=0.7)
        file_button.bind(on_press=self.open_file_chooser)
        file_section.add_widget(file_button)
        
        self.file_label = Label(text='No file selected', size_hint_y=0.3)
        main_layout.add_widget(self.file_label)
        main_layout.add_widget(file_section)
        
        # ===== SCROLLABLE SETTINGS SECTION =====
        scroll = ScrollView(size_hint_y=0.7)
        settings_layout = GridLayout(cols=1, spacing=10, size_hint_y=None, padding=10)
        settings_layout.bind(minimum_height=settings_layout.setter('height'))
        
        # Prompt section
        settings_layout.add_widget(Label(text='Custom Prompt', size_hint_y=None, height=30, bold=True))
        self.prompt_edit = TextInput(
            text='Generate clear, concise study notes in Markdown format.',
            multiline=True,
            size_hint_y=None,
            height=80
        )
        settings_layout.add_widget(self.prompt_edit)
        
        # Chunk size
        settings_layout.add_widget(Label(text='Chunk Size (pages)', size_hint_y=None, height=30))
        chunk_layout = BoxLayout(size_hint_y=None, height=40, spacing=5)
        self.chunk_size_spin = Spinner(
            text='2',
            values=('1', '2', '3', '4', '5'),
            size_hint_x=0.3
        )
        chunk_layout.add_widget(Label(text='Pages per chunk:', size_hint_x=0.7))
        chunk_layout.add_widget(self.chunk_size_spin)
        settings_layout.add_widget(chunk_layout)
        
        # Max tokens
        settings_layout.add_widget(Label(text='Max Tokens', size_hint_y=None, height=30))
        self.max_tokens_slider = Slider(min=256, max=16384, value=4096, size_hint_y=None, height=40)
        self.max_tokens_label = Label(text='4096', size_hint_y=None, height=30)
        self.max_tokens_slider.bind(value=self._on_max_tokens_changed)
        settings_layout.add_widget(self.max_tokens_slider)
        settings_layout.add_widget(self.max_tokens_label)
        
        # Temperature
        settings_layout.add_widget(Label(text='Temperature', size_hint_y=None, height=30))
        self.temp_slider = Slider(min=0, max=100, value=20, size_hint_y=None, height=40)
        self.temp_label = Label(text='0.20', size_hint_y=None, height=30)
        self.temp_slider.bind(value=self._on_temp_changed)
        settings_layout.add_widget(self.temp_slider)
        settings_layout.add_widget(self.temp_label)
        
        # Concurrent calls
        settings_layout.add_widget(Label(text='Concurrent API Calls', size_hint_y=None, height=30))
        concurrent_layout = BoxLayout(size_hint_y=None, height=40, spacing=5)
        self.concurrent_spin = Spinner(
            text='2',
            values=('1', '2', '3', '4', '5'),
            size_hint_x=0.3
        )
        concurrent_layout.add_widget(Label(text='Parallel requests:', size_hint_x=0.7))
        concurrent_layout.add_widget(self.concurrent_spin)
        settings_layout.add_widget(concurrent_layout)
        
        # Cloud API Section
        settings_layout.add_widget(Label(text='Cloud API Settings', size_hint_y=None, height=30, bold=True))
        
        settings_layout.add_widget(Label(text='Service', size_hint_y=None, height=30))
        self.service_combo = Spinner(
            text='OpenAI',
            values=('OpenAI', 'Groq', 'Google AI Studio', 'OpenRouter'),
            size_hint_y=None,
            height=40
        )
        self.service_combo.bind(text=self.on_service_changed)
        settings_layout.add_widget(self.service_combo)
        
        settings_layout.add_widget(Label(text='Model', size_hint_y=None, height=30))
        self.cloud_model_combo = Spinner(
            text='gpt-4-turbo',
            values=('gpt-4-turbo', 'gpt-3.5-turbo', 'groq-llama2', 'gemini-pro'),
            size_hint_y=None,
            height=40
        )
        settings_layout.add_widget(self.cloud_model_combo)
        
        settings_layout.add_widget(Label(text='API Key', size_hint_y=None, height=30))
        api_key_layout = BoxLayout(orientation='vertical', size_hint_y=None, height=80, spacing=5)
        
        self.api_key_combo = Spinner(
            text='Default',
            values=('Default',),
            size_hint_y=None,
            height=40
        )
        self.api_key_combo.bind(text=self.on_api_key_selected)
        api_key_layout.add_widget(self.api_key_combo)
        
        self.show_key_check = CheckBox(active=False, size_hint_x=0.1)
        key_show_layout = BoxLayout(size_hint_y=None, height=40, spacing=5)
        key_show_layout.add_widget(self.show_key_check)
        key_show_layout.add_widget(Label(text='Show API Key', size_hint_x=0.9))
        api_key_layout.add_widget(key_show_layout)
        
        add_key_button = Button(text='Add New API Key', size_hint_y=None, height=40)
        add_key_button.bind(on_press=self.add_api_key_dialog)
        api_key_layout.add_widget(add_key_button)
        
        settings_layout.add_widget(api_key_layout)
        
        scroll.add_widget(settings_layout)
        main_layout.add_widget(scroll)
        
        # ===== BOTTOM ACTION BUTTONS =====
        action_layout = BoxLayout(orientation='horizontal', size_hint_y=0.12, spacing=10)
        
        generate_btn = Button(text='Generate Notes')
        generate_btn.bind(on_press=self.generate_notes)
        action_layout.add_widget(generate_btn)
        
        save_pdf_btn = Button(text='Save PDF')
        save_pdf_btn.bind(on_press=self.save_pdf)
        action_layout.add_widget(save_pdf_btn)
        
        save_docx_btn = Button(text='Save DOCX')
        save_docx_btn.bind(on_press=self.save_docx)
        action_layout.add_widget(save_docx_btn)
        
        main_layout.add_widget(action_layout)
        
        # Status bar
        self.status_label = Label(text='✅ Ready', size_hint_y=0.05)
        main_layout.add_widget(self.status_label)
        
        # Start license check timer
        self.check_license_periodically()
        
        return main_layout
    
    def show_license_error_screen(self):
        """Show error screen if license is invalid."""
        layout = BoxLayout(orientation='vertical', padding=20, spacing=20)
        layout.add_widget(Label(text='License Required', bold=True, size_hint_y=0.2))
        layout.add_widget(Label(
            text='Your license is invalid or pending approval.\nPlease contact support or reactivate.',
            size_hint_y=0.6
        ))
        close_btn = Button(text='Close App', size_hint_y=0.2)
        close_btn.bind(on_press=lambda x: App.get_running_app().stop())
        layout.add_widget(close_btn)
        return layout
    
    def _on_max_tokens_changed(self, instance, value):
        """Update max tokens label."""
        self.max_tokens_label.text = str(int(value))
    
    def _on_temp_changed(self, instance, value):
        """Update temperature label."""
        self.temp_label.text = f"{value / 100:.2f}"
    
    def on_service_changed(self, instance, value):
        """Handle service selection change."""
        # Update model options based on service
        service_models = {
            'OpenAI': ['gpt-4-turbo', 'gpt-3.5-turbo', 'gpt-4', 'gpt-4-32k'],
            'Groq': ['mixtral-8x7b-32768', 'llama2-70b-4096'],
            'Google AI Studio': ['gemini-pro', 'gemini-1.5-pro'],
            'OpenRouter': ['openai/gpt-4-turbo', 'anthropic/claude-3-opus']
        }
        models = service_models.get(value, [])
        self.cloud_model_combo.values = tuple(models)
        if models:
            self.cloud_model_combo.text = models[0]
    
    def on_api_key_selected(self, instance, value):
        """Handle API key selection."""
        # Load API key from storage
        lm = LicenseManager()
        api_key_data = lm.get_api_key_by_name(value)
        if api_key_data:
            self.api_config = {'name': value, 'api_key': api_key_data['api_key'], 'service': api_key_data.get('service')}
    
    def add_api_key_dialog(self, instance):
        """Show dialog to add new API key."""
        content = BoxLayout(orientation='vertical', spacing=10, padding=10)
        content.add_widget(Label(text='API Key Name', size_hint_y=0.2))
        name_input = TextInput(hint_text='e.g., My OpenAI Key', size_hint_y=0.2)
        content.add_widget(name_input)
        
        content.add_widget(Label(text='API Key Value', size_hint_y=0.2))
        key_input = TextInput(hint_text='Paste your API key', size_hint_y=0.2, password=True)
        content.add_widget(key_input)
        
        btn_layout = BoxLayout(size_hint_y=0.2, spacing=10)
        save_btn = Button(text='Save')
        cancel_btn = Button(text='Cancel')
        btn_layout.add_widget(save_btn)
        btn_layout.add_widget(cancel_btn)
        content.add_widget(btn_layout)
        
        popup = Popup(title='Add API Key', content=content, size_hint=(0.9, 0.6))
        
        def on_save(btn):
            if name_input.text.strip() and key_input.text.strip():
                service_key = self.service_combo.text.lower().replace(' ', '_')
                lm = LicenseManager()
                lm.save_named_api_key(name_input.text.strip(), key_input.text.strip(), service_key)
                self.status_label.text = '✅ API key saved'
                popup.dismiss()
        
        save_btn.bind(on_press=on_save)
        cancel_btn.bind(on_press=popup.dismiss)
        popup.open()
    
    def open_file_chooser(self, instance):
        """Open file chooser to select PDF or DOCX."""
        content = BoxLayout(orientation='vertical')
        filechooser = FileChooserListView(filters=['*.pdf', '*.docx'])
        content.add_widget(filechooser)
        
        btn_layout = BoxLayout(size_hint_y=0.1, spacing=10)
        select_btn = Button(text='Select')
        cancel_btn = Button(text='Cancel')
        btn_layout.add_widget(select_btn)
        btn_layout.add_widget(cancel_btn)
        content.add_widget(btn_layout)
        
        popup = Popup(title='Select Document', content=content, size_hint=(0.9, 0.9))
        
        def on_select(btn):
            if filechooser.selection:
                self.temp_input_path = filechooser.selection[0]
                self.file_label.text = os.path.basename(self.temp_input_path)
                self.status_label.text = f'✅ Loaded: {os.path.basename(self.temp_input_path)}'
                popup.dismiss()
        
        select_btn.bind(on_press=on_select)
        cancel_btn.bind(on_press=popup.dismiss)
        popup.open()
    
    def extract_text_from_pdf(self, pdf_path):
        """Extract text from PDF file."""
        try:
            reader = PdfReader(pdf_path)
            return [page.extract_text() or "" for page in reader.pages]
        except Exception as e:
            log_error(f"PDF extraction failed: {e}")
            self.status_label.text = f'❌ Error reading PDF: {e}'
            return []
    
    def chunk_pages(self, page_texts, chunk_size):
        """Divide pages into chunks."""
        chunks = []
        for i in range(0, len(page_texts), chunk_size):
            chunk_pages = page_texts[i:i+chunk_size]
            start_page = i + 1
            end_page = min(i + chunk_size, len(page_texts))
            combined = "\n\n".join(chunk_pages)
            chunks.append((start_page, end_page, combined))
        return chunks
    
    def generate_notes(self, instance):
        """Generate notes from selected document."""
        if not self.temp_input_path:
            self.status_label.text = '⚠️ Please select a document first'
            return
        
        if self.license_status != 'active':
            self.status_label.text = '⚠️ License not active'
            return
        
        if not self.api_config or not self.api_config.get('api_key'):
            self.status_label.text = '⚠️ Please configure an API key'
            return
        
        self.status_label.text = '⏳ Extracting text...'
        
        # Run generation in background thread
        thread_task(self._generate_notes_thread)
    
    def _generate_notes_thread(self):
        """Background thread for note generation."""
        try:
            # Extract text
            if self.temp_input_path.endswith('.pdf'):
                page_texts = self.extract_text_from_pdf(self.temp_input_path)
            else:
                page_texts = extract_text_from_docx(self.temp_input_path)
            
            if not page_texts:
                Clock.schedule_once(lambda dt: setattr(self.status_label, 'text', '❌ No text extracted'), 0)
                return
            
            # Create chunks
            chunk_size = int(self.chunk_size_spin.text)
            chunks = self.chunk_pages(page_texts, chunk_size)
            
            Clock.schedule_once(lambda dt: setattr(self.status_label, 'text', f'⏳ Generating {len(chunks)} chunks...'), 0)
            
            # Get AI parameters
            system_prompt = self.prompt_edit.text.strip() or "Generate clear, concise study notes in Markdown format."
            max_tokens = int(self.max_tokens_slider.value)
            temperature = self.temp_slider.value
            concurrent_calls = int(self.concurrent_spin.text)
            
            # Create worker
            service_key = self.service_combo.text.lower().replace(' ', '_')
            if service_key == 'google_ai_studio':
                service_key = 'google'
            
            worker = AIGenerationWorker(
                api_key=self.api_config['api_key'],
                service=service_key,
                model=self.cloud_model_combo.text,
                callback_progress=self._on_generation_progress,
                callback_complete=self._on_generation_complete,
                request_rate_limiter=rpm_limiter
            )
            
            # Run async generation
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            results = loop.run_until_complete(
                worker.process_all_chunks(chunks, system_prompt, max_tokens, temperature, concurrent_calls)
            )
            loop.close()
            
            # Combine results
            combined_markdown = "\n\n---\n\n".join([r['notes'] for r in results])
            self.generated_html = self._markdown_to_html(combined_markdown)
            
            Clock.schedule_once(
                lambda dt: setattr(self.status_label, 'text', '✅ Notes generated successfully'),
                0
            )
        
        except Exception as e:
            log_error(f"Generation error: {e}")
            Clock.schedule_once(
                lambda dt: setattr(self.status_label, 'text', f'❌ Error: {str(e)[:50]}'),
                0
            )
    
    def _on_generation_progress(self, progress):
        """Update progress during generation."""
        Clock.schedule_once(
            lambda dt: setattr(self.status_label, 'text', f'⏳ Progress: {int(progress * 100)}%'),
            0
        )
    
    def _on_generation_complete(self, result):
        """Called when generation completes."""
        pass
    
    def _markdown_to_html(self, markdown_text):
        """Convert Markdown to HTML with MathJax support."""
        html_body = markdown.markdown(markdown_text, extensions=['tables', 'fenced_code'])
        
        html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <style>
                body {{
                    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
                    line-height: 1.6;
                    color: #333;
                    margin: 1em;
                    padding: 1em;
                    background: white;
                }}
                h1, h2, h3 {{ color: #1a1a2e; margin-top: 1em; }}
                table {{ border-collapse: collapse; margin: 1em 0; width: 100%; }}
                th, td {{ border: 1px solid #ddd; padding: 8px; text-align: left; }}
                th {{ background-color: #f2f2f2; }}
                code {{ background-color: #f4f4f4; padding: 2px 4px; border-radius: 3px; }}
                pre {{ background-color: #f4f4f4; padding: 1em; overflow-x: auto; }}
            </style>
            <script id="MathJax-script" async src="https://cdn.jsdelivr.net/npm/mathjax@3/es5/tex-mml-chtml.js"></script>
        </head>
        <body>
            {html_body}
        </body>
        </html>
        """
        return html
    
    def save_pdf(self, instance):
        """Save generated notes as PDF."""
        if not self.generated_html:
            self.status_label.text = '⚠️ Generate notes first'
            return
        
        try:
            from kivy.garden.webbrowser import webbrowser
            
            # Save HTML to temp file
            pdf_path = os.path.join(tempfile.gettempdir(), 'pdf_notes_output.pdf')
            
            # For Android, we'll use a simple approach: convert HTML to PDF
            # In production, use a library like reportlab or pdfkit
            try:
                import pdfkit
                pdfkit.from_string(self.generated_html, pdf_path)
                self.exported_pdf_path = pdf_path
                self.status_label.text = f'✅ PDF saved to {pdf_path}'
            except:
                # Fallback: just save the HTML
                html_path = os.path.join(tempfile.gettempdir(), 'pdf_notes_output.html')
                with open(html_path, 'w', encoding='utf-8') as f:
                    f.write(self.generated_html)
                self.status_label.text = f'✅ HTML saved (install pdfkit for PDF)'
        
        except Exception as e:
            log_error(f"PDF save error: {e}")
            self.status_label.text = f'❌ Save failed: {str(e)[:50]}'
    
    def save_docx(self, instance):
        """Save generated notes as DOCX."""
        if not self.generated_html:
            self.status_label.text = '⚠️ Generate notes first'
            return
        
        try:
            from html2docx import html_to_docx
            
            docx_path = os.path.join(tempfile.gettempdir(), 'pdf_notes_output.docx')
            html_to_docx(self.generated_html, docx_path)
            self.exported_docx_path = docx_path
            self.status_label.text = f'✅ DOCX saved to {docx_path}'
        
        except Exception as e:
            # Fallback: create basic DOCX manually
            try:
                from docx import Document
                from docx.shared import Pt, RGBColor
                
                doc = Document()
                
                # Parse HTML and add to document
                from html.parser import HTMLParser
                
                class DocxHTMLParser(HTMLParser):
                    def __init__(self, doc):
                        super().__init__()
                        self.doc = doc
                        self.current_style = {}
                    
                    def handle_starttag(self, tag, attrs):
                        if tag in ['h1', 'h2', 'h3']:
                            self.current_style['heading'] = int(tag[1])
                        elif tag == 'strong' or tag == 'b':
                            self.current_style['bold'] = True
                        elif tag == 'em' or tag == 'i':
                            self.current_style['italic'] = True
                    
                    def handle_data(self, data):
                        if data.strip():
                            if 'heading' in self.current_style:
                                self.doc.add_heading(data, level=self.current_style['heading'])
                                del self.current_style['heading']
                            else:
                                p = self.doc.add_paragraph(data)
                
                parser = DocxHTMLParser(doc)
                parser.feed(self.generated_html)
                
                docx_path = os.path.join(tempfile.gettempdir(), 'pdf_notes_output.docx')
                doc.save(docx_path)
                self.exported_docx_path = docx_path
                self.status_label.text = f'✅ DOCX saved to {docx_path}'
            
            except Exception as e2:
                log_error(f"DOCX save error: {e2}")
                self.status_label.text = f'❌ DOCX save failed: {str(e2)[:50]}'
    
    def check_license_periodically(self):
        """Check license status periodically."""
        def check_license():
            try:
                lm = LicenseManager()
                lic = lm.load_license()
                if not lic:
                    return
                
                key, hwid = lic.get('key'), lm.get_hwid()
                signed = sign_request({"license_key": key, "hwid": hwid})
                response = requests.post(LICENSE_CHECK_URL, json=signed, timeout=5)
                
                if response.status_code == 200:
                    data = response.json()
                    if not data.get('valid'):
                        Clock.schedule_once(
                            lambda dt: App.get_running_app().stop(),
                            0
                        )
            except Exception as e:
                log_error(f"License check error: {e}")
        
        # Check every 4 hours
        Clock.schedule_interval(lambda dt: thread_task(check_license), 14400)
    
    def load_settings(self):
        """Load user settings from storage."""
        settings_path = os.path.join(get_android_storage_path(), ".pdf_notes_maker", "user_settings.json")
        if not os.path.exists(settings_path):
            return
        
        try:
            with open(settings_path, 'r', encoding='utf-8') as f:
                settings = json.load(f)
            
            self.prompt_edit.text = settings.get('prompt', self.prompt_edit.text)
            self.chunk_size_spin.text = str(settings.get('chunk_size', 2))
            self.max_tokens_slider.value = settings.get('max_tokens', 1024)
            self.temp_slider.value = settings.get('temperature', 20)
            self.concurrent_spin.text = str(settings.get('concurrent_calls', 2))
            self.service_combo.text = settings.get('service', 'OpenAI')
            self.cloud_model_combo.text = settings.get('cloud_model', 'gpt-4-turbo')
            self.custom_cloud_models = settings.get('custom_cloud_models', {})
        
        except Exception as e:
            log_error(f"Settings load error: {e}")
    
    def save_settings(self):
        """Save user settings to storage."""
        try:
            settings = {
                'prompt': self.prompt_edit.text,
                'chunk_size': int(self.chunk_size_spin.text),
                'max_tokens': int(self.max_tokens_slider.value),
                'temperature': self.temp_slider.value,
                'concurrent_calls': int(self.concurrent_spin.text),
                'service': self.service_combo.text,
                'cloud_model': self.cloud_model_combo.text,
                'custom_cloud_models': self.custom_cloud_models
            }
            
            settings_dir = os.path.join(get_android_storage_path(), ".pdf_notes_maker")
            os.makedirs(settings_dir, exist_ok=True)
            
            settings_path = os.path.join(settings_dir, "user_settings.json")
            with open(settings_path, 'w', encoding='utf-8') as f:
                json.dump(settings, f, indent=2)
        
        except Exception as e:
            log_error(f"Settings save error: {e}")
    
    def on_stop(self):
        """Clean up when app closes."""
        self.save_settings()
        return True

# ========== App Entry Point ==========

if __name__ == '__main__':
    PDFNotesMakerAndroid().run()
