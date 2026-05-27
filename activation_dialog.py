# activation_dialog.py - Android Version
# License activation dialog for PDF Notes Maker on Android
# Converts PyQt6 dialogs to Kivy Popups with touch-friendly UI

import os
import uuid
import requests
import threading
from datetime import datetime

from kivy.uix.popup import Popup
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.gridlayout import GridLayout
from kivy.uix.label import Label
from kivy.uix.button import Button
from kivy.uix.textinput import TextInput
from kivy.uix.progressbar import ProgressBar
from kivy.uix.scrollview import ScrollView
from kivy.uix.filechooser import FileChooserListView
from kivy.uix.image import Image
from kivy.clock import mainthread
from kivy.core.window import Window

from license_manager import LicenseManager, get_embedded_license_key


# ========== Configuration ==========
LICENSE_SERVER_URL = "https://mestu0930.pythonanywhere.com/api/activate"
MAX_RECEIPT_SIZE = 10 * 1024 * 1024  # 10 MB limit


def log_error(msg):
    """Log errors to file."""
    from launcher import log_error as launcher_log_error
    launcher_log_error(msg)


class ActivationDialog:
    """
    License activation dialog for Android.
    
    Features:
    - Email input
    - Payment details display (CBE bank + Telebirr mobile money)
    - Receipt file upload
    - License server communication
    - Pending request queuing
    - Progress indication
    """
    
    def __init__(self, callback_accepted=None, callback_rejected=None):
        """
        Initialize activation dialog.
        
        Args:
            callback_accepted: Function to call if activation successful
            callback_rejected: Function to call if user cancels
        """
        self.callback_accepted = callback_accepted
        self.callback_rejected = callback_rejected
        self.receipt_path = None
        self.popup = None
        self.email_input = None
        self.receipt_status = None
        self.progress_bar = None
        self.status_label = None
        self.upload_btn = None
        self.activate_btn = None
        self.cancel_btn = None
    
    def open(self):
        """Open the activation dialog."""
        self.popup = Popup(
            title='🔑 Activate Your License',
            size_hint=(0.95, 0.95),
            pos_hint={'center_x': 0.5, 'center_y': 0.5}
        )
        
        # Main container
        main_layout = BoxLayout(orientation='vertical', padding=15, spacing=10)
        
        # ===== Scroll area for content =====
        scroll = ScrollView()
        content_layout = GridLayout(cols=1, spacing=10, size_hint_y=None, padding=10)
        content_layout.bind(minimum_height=content_layout.setter('height'))
        
        # Title
        title_label = Label(
            text='🔑 Activate Your License',
            size_hint_y=None,
            height=50,
            bold=True,
            font_size='18sp'
        )
        content_layout.add_widget(title_label)
        
        # Instructions
        instr_label = Label(
            text='Please enter the email address used for your purchase,\n'
                 'make payment using the details below, and upload your receipt.',
            size_hint_y=None,
            height=60,
            text_size=(Window.width - 60, None),
            halign='center'
        )
        content_layout.add_widget(instr_label)
        
        # ===== Email Input Section =====
        email_label = Label(text='📧 Your Email Address', size_hint_y=None, height=30, bold=True)
        content_layout.add_widget(email_label)
        
        self.email_input = TextInput(
            hint_text='you@example.com',
            multiline=False,
            size_hint_y=None,
            height=45,
            padding=[10, 5]
        )
        content_layout.add_widget(self.email_input)
        
        # ===== Payment Details Section =====
        payment_title = Label(
            text='💳 Payment Details',
            size_hint_y=None,
            height=30,
            bold=True
        )
        content_layout.add_widget(payment_title)
        
        price_label = Label(
            text='💰 Price: 200 ETB (Ethiopian Birr)',
            size_hint_y=None,
            height=40,
            bold=True,
            color=(0.6, 1, 0.6, 1)  # Green
        )
        content_layout.add_widget(price_label)
        
        cbe_label = Label(
            text='🏦 CBE Account:\n1000713428462\n(Mengistu Zelalem Amare)',
            size_hint_y=None,
            height=70,
            markup=True,
            font_size='11sp'
        )
        content_layout.add_widget(cbe_label)
        
        telebirr_label = Label(
            text='📱 Telebirr:\n0974883807\n(Selamawit)',
            size_hint_y=None,
            height=70,
            markup=True,
            font_size='11sp'
        )
        content_layout.add_widget(telebirr_label)
        
        # ===== Receipt Upload Section =====
        receipt_title = Label(
            text='📸 Upload Payment Receipt',
            size_hint_y=None,
            height=30,
            bold=True
        )
        content_layout.add_widget(receipt_title)
        
        receipt_instruction = Label(
            text='Take a screenshot or photo of your payment confirmation\nand upload it below.',
            size_hint_y=None,
            height=50,
            text_size=(Window.width - 60, None),
            halign='center',
            font_size='10sp'
        )
        content_layout.add_widget(receipt_instruction)
        
        # Receipt file selection layout
        receipt_btn_layout = BoxLayout(size_hint_y=None, height=45, spacing=10)
        
        self.upload_btn = Button(
            text='📁 Select Receipt',
            size_hint_x=0.4,
            background_color=(0.2, 0.6, 1, 1)  # Blue
        )
        self.upload_btn.bind(on_press=self.upload_receipt)
        receipt_btn_layout.add_widget(self.upload_btn)
        
        self.receipt_status = Label(
            text='No file selected',
            size_hint_x=0.6,
            color=(0.8, 0.8, 0.8, 1)  # Gray
        )
        receipt_btn_layout.add_widget(self.receipt_status)
        
        content_layout.add_widget(receipt_btn_layout)
        
        # ===== Progress & Status =====
        self.progress_bar = ProgressBar(
            value=0,
            size_hint_y=None,
            height=30
        )
        self.progress_bar.visible = False
        content_layout.add_widget(self.progress_bar)
        
        self.status_label = Label(
            text='',
            size_hint_y=None,
            height=40,
            text_size=(Window.width - 60, None),
            halign='center',
            color=(1, 0.7, 0.7, 1)  # Light red
        )
        content_layout.add_widget(self.status_label)
        
        scroll.add_widget(content_layout)
        main_layout.add_widget(scroll)
        
        # ===== Action Buttons =====
        button_layout = BoxLayout(
            orientation='horizontal',
            size_hint_y=0.1,
            spacing=10,
            padding=[0, 10, 0, 0]
        )
        
        self.cancel_btn = Button(
            text='Cancel',
            background_color=(0.5, 0.5, 0.5, 1)  # Gray
        )
        self.cancel_btn.bind(on_press=self.on_cancel)
        button_layout.add_widget(self.cancel_btn)
        
        self.activate_btn = Button(
            text='Submit Request',
            background_color=(0.2, 0.8, 0.3, 1)  # Green
        )
        self.activate_btn.bind(on_press=self.activate)
        button_layout.add_widget(self.activate_btn)
        
        main_layout.add_widget(button_layout)
        
        # Set popup content and open
        self.popup.content = main_layout
        self.popup.open()
    
    def upload_receipt(self, instance):
        """Open file chooser to select receipt."""
        content = BoxLayout(orientation='vertical', padding=10, spacing=10)
        
        # File chooser
        filechooser = FileChooserListView(
            filters=['*.png', '*.jpg', '*.jpeg', '*.pdf']
        )
        content.add_widget(filechooser)
        
        # Button layout
        btn_layout = BoxLayout(size_hint_y=0.15, spacing=10, padding=[0, 10, 0, 0])
        
        select_btn = Button(text='Select', background_color=(0.2, 0.8, 0.3, 1))
        cancel_btn = Button(text='Cancel', background_color=(0.5, 0.5, 0.5, 1))
        
        btn_layout.add_widget(select_btn)
        btn_layout.add_widget(cancel_btn)
        content.add_widget(btn_layout)
        
        # Create popup
        file_popup = Popup(
            title='Select Payment Receipt',
            content=content,
            size_hint=(0.95, 0.95),
            pos_hint={'center_x': 0.5, 'center_y': 0.5}
        )
        
        def on_select(btn):
            if filechooser.selection:
                file_path = filechooser.selection[0]
                
                # Validate file size
                try:
                    file_size = os.path.getsize(file_path)
                    if file_size > MAX_RECEIPT_SIZE:
                        self._show_error(
                            'File Too Large',
                            f'The file ({file_size / (1024*1024):.1f} MB) exceeds the 10 MB limit.\n'
                            'Please select a smaller file.'
                        )
                        return
                except Exception as e:
                    self._show_error('Error', f'Could not read file: {str(e)}')
                    return
                
                # Set receipt
                self.receipt_path = file_path
                self.receipt_status.text = os.path.basename(file_path)
                self.receipt_status.color = (0.6, 1, 0.6, 1)  # Green
                file_popup.dismiss()
        
        select_btn.bind(on_press=on_select)
        cancel_btn.bind(on_press=file_popup.dismiss)
        
        file_popup.open()
    
    def activate(self, instance):
        """Submit activation request."""
        # Validate inputs
        email = self.email_input.text.strip()
        if not email:
            self._show_error('Missing Information', 'Please enter your email address.')
            return
        
        if not self.receipt_path:
            self._show_error('Missing Receipt', 'Please upload your payment receipt.')
            return
        
        if not os.path.exists(self.receipt_path):
            self._show_error('Error', 'Receipt file not found.')
            self.receipt_path = None
            self.receipt_status.text = 'File not found'
            return
        
        # Get app ID and HWID
        app_id = get_embedded_license_key()
        if not app_id:
            self._show_error('Error', 'No embedded app ID found. Please contact support.')
            return
        
        lm = LicenseManager()
        hwid = lm.get_hwid()
        
        # Show progress
        self._set_progress_visible(True)
        self._set_status('⏳ Submitting activation request...')
        self._disable_controls(True)
        
        # Submit in background thread
        thread = threading.Thread(
            target=self._submit_activation_thread,
            args=(email, hwid, app_id, lm)
        )
        thread.daemon = True
        thread.start()
    
    def _submit_activation_thread(self, email, hwid, app_id, lm):
        """Background thread for submission."""
        try:
            # 1. Queue the pending request
            lm.save_pending_activation(email, hwid, self.receipt_path, app_id)
            
            # 2. Save a temporary pending license with placeholder key
            placeholder_key = f"pending_{uuid.uuid4().hex[:8]}"
            lm.save_license({
                'key': placeholder_key,
                'email': email,
                'status': 'pending',
                'requested_at': datetime.now().isoformat()
            })
            
            # 3. Try to send to server immediately
            self._update_status_mainthread('⏳ Sending to server...')
            
            data = {
                'app_id': app_id,
                'email': email,
                'hwid': hwid
            }
            
            files = {}
            try:
                files['receipt'] = (
                    os.path.basename(self.receipt_path),
                    open(self.receipt_path, 'rb'),
                    'application/octet-stream'
                )
                
                # Send request (without signing - can add signing if needed)
                response = requests.post(
                    LICENSE_SERVER_URL,
                    data=data,
                    files=files,
                    timeout=10
                )
                
                # Close file
                if files and 'receipt' in files:
                    try:
                        files['receipt'][1].close()
                    except:
                        pass
                
                if response.status_code == 200:
                    result = response.json()
                    if result.get('success') and result.get('license_key'):
                        # License key received immediately
                        lm.save_license({
                            'key': result['license_key'],
                            'email': email,
                            'status': 'pending',
                            'requested_at': datetime.now().isoformat()
                        })
                        self._update_status_mainthread('✅ Sent to server')
                    else:
                        self._update_status_mainthread('✅ Request queued (will retry)')
                else:
                    self._update_status_mainthread('✅ Request queued (will retry)')
            
            except requests.exceptions.Timeout:
                self._update_status_mainthread('⚠️ Server timeout (will retry)')
            except requests.exceptions.ConnectionError:
                self._update_status_mainthread('⚠️ No internet (will retry when online)')
            except Exception as e:
                log_error(f"Activation send error: {e}")
                self._update_status_mainthread('⚠️ Error (will retry)')
            
            # Show success dialog
            self._show_success_mainthread()
        
        except Exception as e:
            log_error(f"Activation error: {e}")
            self._update_status_mainthread(f'❌ Error: {str(e)[:50]}')
            self._show_error_mainthread('Activation Failed', str(e))
        
        finally:
            self._set_progress_visible(False)
            self._disable_controls(False)
    
    def _show_success_mainthread(self):
        """Show success message (thread-safe)."""
        def show():
            self._show_info(
                'Request Submitted',
                'Your activation request has been saved.\n\n'
                'It will be sent automatically when the license server is available.\n'
                'You may close and reopen the app; it will continue trying in the background.\n\n'
                'Once approved by the admin, you\'ll be able to use the app.'
            )
            self.on_accept()
        
        from kivy.clock import mainthread
        mainthread(show)()
    
    def _show_error_mainthread(self, title, message):
        """Show error dialog (thread-safe)."""
        def show():
            self._show_error(title, message)
        
        from kivy.clock import mainthread
        mainthread(show)()
    
    def _update_status_mainthread(self, message):
        """Update status label (thread-safe)."""
        def update():
            self._set_status(message)
        
        from kivy.clock import mainthread
        mainthread(update)()
    
    def _set_status(self, message):
        """Update status label."""
        if self.status_label:
            self.status_label.text = message
    
    def _set_progress_visible(self, visible):
        """Show/hide progress bar."""
        if self.progress_bar:
            self.progress_bar.visible = visible
    
    def _disable_controls(self, disabled):
        """Disable/enable form controls."""
        if self.email_input:
            self.email_input.disabled = disabled
        if self.upload_btn:
            self.upload_btn.disabled = disabled
        if self.activate_btn:
            self.activate_btn.disabled = disabled
    
    def _show_info(self, title, message):
        """Show info dialog."""
        content = BoxLayout(orientation='vertical', padding=15, spacing=10)
        
        label = Label(
            text=message,
            size_hint_y=0.8,
            text_size=(Window.width - 60, None),
            halign='center'
        )
        content.add_widget(label)
        
        btn = Button(
            text='OK',
            size_hint_y=0.2,
            background_color=(0.2, 0.8, 0.3, 1)
        )
        content.add_widget(btn)
        
        popup = Popup(
            title=title,
            content=content,
            size_hint=(0.9, 0.6),
            pos_hint={'center_x': 0.5, 'center_y': 0.5}
        )
        
        btn.bind(on_press=popup.dismiss)
        popup.open()
    
    def _show_error(self, title, message):
        """Show error dialog."""
        content = BoxLayout(orientation='vertical', padding=15, spacing=10)
        
        label = Label(
            text=message,
            size_hint_y=0.8,
            text_size=(Window.width - 60, None),
            halign='center',
            color=(1, 0.7, 0.7, 1)
        )
        content.add_widget(label)
        
        btn = Button(
            text='OK',
            size_hint_y=0.2,
            background_color=(1, 0.4, 0.3, 1)
        )
        content.add_widget(btn)
        
        popup = Popup(
            title=title,
            content=content,
            size_hint=(0.9, 0.6),
            pos_hint={'center_x': 0.5, 'center_y': 0.5}
        )
        
        btn.bind(on_press=popup.dismiss)
        popup.open()
    
    def on_accept(self):
        """Handle acceptance of activation dialog."""
        if self.popup:
            self.popup.dismiss()
        if self.callback_accepted:
            self.callback_accepted()
    
    def on_cancel(self, instance):
        """Handle cancellation of activation dialog."""
        if self.popup:
            self.popup.dismiss()
        if self.callback_rejected:
            self.callback_rejected()


# ========== Backward Compatibility ==========

class ActivationDialogCompat:
    """
    Compatibility wrapper for PyQt6-style dialog usage.
    
    Usage:
        dialog = ActivationDialogCompat()
        result = dialog.exec()  # Shows dialog, returns True/False
    """
    
    def __init__(self):
        self.result = None
        self.dialog = None
    
    def exec(self):
        """Show dialog and return result (blocking-style)."""
        # Note: Kivy dialogs are non-blocking
        # This is a simplified version that returns True for accepted
        self.dialog = ActivationDialog(
            callback_accepted=self._on_accepted,
            callback_rejected=self._on_rejected
        )
        self.dialog.open()
        return True  # Assuming accepted (Kivy doesn't block)
    
    def _on_accepted(self):
        self.result = True
    
    def _on_rejected(self):
        self.result = False
