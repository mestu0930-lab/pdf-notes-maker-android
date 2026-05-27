# launcher.py - Android Version
# Entry point for PDF Notes Maker on Android
# Removed: PyQt6, Ollama checking/starting, single-instance lock, splash screen
# Kept: Secrets loading, license manager initialization, signing secret setup

import sys
import os
import json
import traceback
from datetime import datetime

# Android-specific imports
try:
    from android.app import activity
    from android.permissions import request_permissions, Permission
    ANDROID_ENV = True
except ImportError:
    ANDROID_ENV = False

from license_manager import LicenseManager, get_embedded_license_key


def get_android_storage_path():
    """Get appropriate storage path for Android app."""
    if ANDROID_ENV:
        try:
            from android.storage import primary_external_storage_path
            return primary_external_storage_path()
        except:
            return os.path.expanduser("~")
    else:
        return os.path.expanduser("~")


def request_android_permissions():
    """Request necessary permissions on Android."""
    if not ANDROID_ENV:
        return True
    
    try:
        permissions = [
            Permission.READ_EXTERNAL_STORAGE,
            Permission.WRITE_EXTERNAL_STORAGE,
            Permission.INTERNET
        ]
        request_permissions(permissions)
        return True
    except Exception as e:
        log_error(f"Permission request failed: {e}")
        return False


def log_error(msg):
    """Log errors to file."""
    log_dir = os.path.join(get_android_storage_path(), ".pdf_notes_maker")
    os.makedirs(log_dir, exist_ok=True)
    log_path = os.path.join(log_dir, "launcher_error.log")
    try:
        with open(log_path, 'a', encoding='utf-8') as f:
            f.write(f"{datetime.now().isoformat()}: {msg}\n")
    except:
        pass


def show_error(message):
    """Show error message (Android-specific)."""
    log_error(message)
    if ANDROID_ENV:
        try:
            from jnius import autoclass
            PythonActivity = autoclass('org.kivy.android.PythonActivity')
            Toast = autoclass('android.widget.Toast')
            activity = PythonActivity.mActivity
            Toast.makeText(activity, message, Toast.LENGTH_LONG).show()
        except:
            print(f"ERROR: {message}")
    else:
        print(f"ERROR: {message}")


def load_signing_secret():
    """Load signing secret from external config file."""
    SIGNING_SECRET = b''
    
    try:
        if ANDROID_ENV:
            from android.storage import primary_external_storage_path
            base_path = primary_external_storage_path()
        else:
            base_path = os.path.dirname(os.path.abspath(__file__))
        
        config_path = os.path.join(base_path, "secrets_config.json")
        
        if os.path.exists(config_path):
            try:
                with open(config_path, 'r') as f:
                    config = json.load(f)
                if 'signing_secret' in config:
                    SIGNING_SECRET = config['signing_secret'].encode('utf-8')
                    print("[Launcher] Signing secret loaded from config file")
            except Exception as e:
                log_error(f"Failed to load secrets config: {e}")
                print(f"[Launcher] Warning: Could not load secrets config: {e}")
        else:
            print("[Launcher] No secrets config file found - signing secret is empty")
    
    except Exception as e:
        log_error(f"Exception in load_signing_secret: {e}")
    
    return SIGNING_SECRET


def check_license():
    """Check if license is available."""
    try:
        lm = LicenseManager()
        lic = lm.load_license()
        if not lic:
            print("[Launcher] No license found")
            return False
        
        if lic.get('status') != 'active':
            print(f"[Launcher] License status: {lic.get('status')}")
            return False
        
        print("[Launcher] License check passed")
        return True
    
    except Exception as e:
        log_error(f"License check error: {e}")
        print(f"[Launcher] License check error: {e}")
        return False


def initialize_app():
    """Initialize and run the Kivy app."""
    try:
        # Load signing secret
        SIGNING_SECRET = load_signing_secret()
        
        # Import and setup the main app
        from pdf_notes_app_android import PDFNotesMakerAndroid
        
        # Pass signing secret to the app module
        import pdf_notes_app_android
        pdf_notes_app_android.SIGNING_SECRET = SIGNING_SECRET
        
        print("[Launcher] Starting PDF Notes Maker app...")
        
        # Create and run the Kivy app
        app = PDFNotesMakerAndroid()
        app.run()
        
    except ImportError as e:
        msg = f"Failed to import app module: {e}"
        log_error(msg)
        show_error(msg)
        sys.exit(1)
    
    except Exception as e:
        tb = traceback.format_exc()
        log_error(f"Unexpected error: {tb}")
        show_error(f"Unexpected error: {str(e)}")
        sys.exit(1)


def main():
    """Main launcher entry point."""
    try:
        print("[Launcher] PDF Notes Maker starting...")
        
        # Request Android permissions
        if ANDROID_ENV:
            print("[Launcher] Requesting Android permissions...")
            if not request_android_permissions():
                print("[Launcher] Warning: Permission request may have failed")
        
        # Create config directory
        config_dir = os.path.join(get_android_storage_path(), ".pdf_notes_maker")
        os.makedirs(config_dir, exist_ok=True)
        print(f"[Launcher] Config directory: {config_dir}")
        
        # Check license
        if not check_license():
            print("[Launcher] License check failed - app will show license error screen")
        
        # Initialize and run app
        initialize_app()
    
    except Exception as e:
        tb = traceback.format_exc()
        log_error(f"Launcher exception: {tb}")
        show_error(f"Launcher failed: {str(e)}")
        sys.exit(1)


if __name__ == "__main__":
    main()
