# license_manager.py - Android Version
# Encrypted license and API key storage for Android
# Removed: Windows-specific file attributes (ctypes.windll)
# Kept: All encryption logic, HWID generation, license validation, API key management

import os
import json
import hashlib
import uuid
import platform
import sys
from datetime import datetime
from cryptography.fernet import Fernet


def get_android_storage_path():
    """Get appropriate storage path for Android app."""
    try:
        # Try to import Android storage path
        from android.storage import primary_external_storage_path
        return primary_external_storage_path()
    except ImportError:
        # Fallback for development/desktop testing
        return os.path.expanduser("~")


class LicenseManager:
    """
    Manages encrypted license storage, API keys, and pending activations.
    Uses Fernet symmetric encryption for sensitive data.
    
    Storage location (Android):
        - External storage: /storage/emulated/0/.pdf_notes_maker/
        - Or app-specific: context.getExternalFilesDir(null)
    
    Files:
        - license.dat: Encrypted license file
        - api_keys.dat: Encrypted API keys storage
        - request_queue.json: Encrypted pending activation queue
        - .key: Fernet encryption key (hidden)
        - .hwid: Fallback hardware ID (if platform detection fails)
    """
    
    def __init__(self):
        """Initialize license manager with storage paths."""
        storage_base = get_android_storage_path()
        self.license_dir = os.path.join(storage_base, ".pdf_notes_maker")
        self.license_file = os.path.join(self.license_dir, "license.dat")
        self.queue_file = os.path.join(self.license_dir, "request_queue.json")
        self.key_file = os.path.join(self.license_dir, ".key")
        self.api_keys_file = os.path.join(self.license_dir, "api_keys.dat")
        
        # Ensure directory exists
        os.makedirs(self.license_dir, exist_ok=True)
        
        # Get or create encryption key
        self.cipher_key = self._get_or_create_key()
        self.cipher = Fernet(self.cipher_key)
    
    # ========== Encryption Key Management ==========
    
    def _get_or_create_key(self):
        """
        Get existing Fernet key or create a new one.
        Key is stored in .key file in the license directory.
        """
        if os.path.exists(self.key_file):
            try:
                with open(self.key_file, 'rb') as f:
                    return f.read()
            except Exception as e:
                print(f"[LicenseManager] Warning: Could not read key file: {e}")
                return self._create_new_key()
        else:
            return self._create_new_key()
    
    def _create_new_key(self):
        """Create and save a new Fernet encryption key."""
        new_key = Fernet.generate_key()
        try:
            with open(self.key_file, 'wb') as f:
                f.write(new_key)
            print(f"[LicenseManager] New encryption key created at {self.key_file}")
        except Exception as e:
            print(f"[LicenseManager] Warning: Could not write key file: {e}")
        
        return new_key
    
    # ========== Hardware ID (HWID) ==========
    
    def get_hwid(self):
        """
        Generate or retrieve hardware ID for device-binding licenses.
        
        Priority:
        1. Generate from platform info (hostname, processor, machine)
        2. Fall back to stored HWID file
        3. Generate random UUID if all else fails
        
        Returns: 16-character hex string
        """
        try:
            # Try to get platform-based HWID
            system_info = platform.uname()
            base_str = f"{system_info.node}-{system_info.processor}-{platform.machine()}"
            hwid = hashlib.sha256(base_str.encode()).hexdigest()[:16]
            print(f"[LicenseManager] Generated HWID from platform: {hwid}")
            return hwid
        
        except Exception as e:
            print(f"[LicenseManager] Platform-based HWID failed: {e}")
            
            # Try to load from file
            hwid_file = os.path.join(self.license_dir, ".hwid")
            if os.path.exists(hwid_file):
                try:
                    with open(hwid_file, 'r') as f:
                        hwid = f.read().strip()
                    print(f"[LicenseManager] Loaded HWID from file: {hwid}")
                    return hwid
                except Exception as e2:
                    print(f"[LicenseManager] Could not read HWID file: {e2}")
            
            # Generate new random HWID
            new_hwid = str(uuid.uuid4()).replace('-', '')[:16]
            try:
                with open(hwid_file, 'w') as f:
                    f.write(new_hwid)
                print(f"[LicenseManager] Generated new random HWID: {new_hwid}")
            except Exception as e3:
                print(f"[LicenseManager] Could not save HWID file: {e3}")
            
            return new_hwid
    
    # ========== License Management ==========
    
    def save_license(self, license_data):
        """
        Save encrypted license data.
        
        Args:
            license_data (dict): License information
                - key: License key string
                - email: Associated email
                - status: 'active', 'pending', or 'invalid'
                - expiry: Optional expiration date (ISO format)
                - requested_at: When license was requested
        """
        try:
            # Add HWID to license data
            license_data['hwid'] = self.get_hwid()
            
            # Encrypt and save
            data_str = json.dumps(license_data)
            encrypted = self.cipher.encrypt(data_str.encode())
            
            with open(self.license_file, 'wb') as f:
                f.write(encrypted)
            
            print(f"[LicenseManager] License saved successfully")
        
        except Exception as e:
            print(f"[LicenseManager] Error saving license: {e}")
    
    def load_license(self):
        """
        Load and decrypt license data.
        
        Returns:
            dict: License data if valid, None otherwise
        """
        if not os.path.exists(self.license_file):
            print("[LicenseManager] No license file found")
            return None
        
        try:
            with open(self.license_file, 'rb') as f:
                encrypted = f.read()
            
            data_str = self.cipher.decrypt(encrypted).decode()
            license_data = json.loads(data_str)
            print(f"[LicenseManager] License loaded successfully")
            return license_data
        
        except Exception as e:
            print(f"[LicenseManager] Error loading license: {e}")
            return None
    
    def is_license_valid(self):
        """
        Validate the stored license.
        
        Checks:
        1. License exists
        2. HWID matches (device-binding)
        3. Status is 'active'
        4. Expiry date (if present) is in future
        
        Returns:
            bool: True if license is valid, False otherwise
        """
        lic = self.load_license()
        if not lic:
            print("[LicenseManager] License validation failed: no license found")
            return False
        
        # Check HWID match
        if lic.get('hwid') != self.get_hwid():
            print("[LicenseManager] License validation failed: HWID mismatch")
            return False
        
        # Check status
        if lic.get('status') != 'active':
            print(f"[LicenseManager] License validation failed: status is {lic.get('status')}")
            return False
        
        # Check expiry
        if 'expiry' in lic and lic['expiry']:
            try:
                expiry = datetime.fromisoformat(lic['expiry'])
                if datetime.now() > expiry:
                    print("[LicenseManager] License validation failed: license expired")
                    return False
            except Exception as e:
                print(f"[LicenseManager] Warning: could not parse expiry date: {e}")
        
        print("[LicenseManager] License validation passed")
        return True
    
    def get_license_info(self):
        """
        Get formatted license information for display.
        
        Returns:
            dict: Human-readable license info, None if no license
        """
        lic = self.load_license()
        if not lic:
            return None
        
        return {
            'email': lic.get('email', 'N/A'),
            'key': lic.get('key', 'N/A')[-8:],  # Last 8 chars only
            'status': lic.get('status', 'unknown'),
            'expires': lic.get('expiry', 'Never')
        }
    
    # ========== Pending Activation Requests ==========
    
    def save_pending_activation(self, email, hwid, receipt_path, app_id):
        """
        Save a pending activation request (before license key is approved).
        
        Args:
            email (str): User's email
            hwid (str): Hardware ID
            receipt_path (str): Path to payment receipt file
            app_id (str): Application ID
        """
        try:
            queue = self._load_queue()
            request_data = {
                'app_id': app_id,
                'email': email,
                'hwid': hwid,
                'receipt_path': receipt_path,
                'timestamp': datetime.now().isoformat(),
                'retry_count': 0
            }
            queue.append(request_data)
            self._save_queue(queue)
            print(f"[LicenseManager] Pending activation saved for {email}")
        except Exception as e:
            print(f"[LicenseManager] Error saving pending activation: {e}")
    
    def get_pending_requests(self):
        """Get list of pending activation requests."""
        return self._load_queue()
    
    def delete_pending_request(self, index_or_request):
        """
        Delete a pending request by index or by object.
        
        Args:
            index_or_request (int or dict): Index in queue or request dict
        """
        try:
            queue = self._load_queue()
            if isinstance(index_or_request, int):
                if 0 <= index_or_request < len(queue):
                    queue.pop(index_or_request)
                    print(f"[LicenseManager] Deleted pending request at index {index_or_request}")
            else:
                queue = [r for r in queue if r != index_or_request]
                print(f"[LicenseManager] Deleted pending request by object")
            self._save_queue(queue)
        except Exception as e:
            print(f"[LicenseManager] Error deleting pending request: {e}")
    
    def _load_queue(self):
        """Load and decrypt pending request queue."""
        if not os.path.exists(self.queue_file):
            return []
        
        try:
            with open(self.queue_file, 'rb') as f:
                encrypted = f.read()
            data_str = self.cipher.decrypt(encrypted).decode()
            queue = json.loads(data_str)
            print(f"[LicenseManager] Loaded {len(queue)} pending requests")
            return queue
        except Exception as e:
            print(f"[LicenseManager] Error loading queue: {e}")
            return []
    
    def _save_queue(self, queue):
        """Encrypt and save pending request queue."""
        try:
            data_str = json.dumps(queue)
            encrypted = self.cipher.encrypt(data_str.encode())
            with open(self.queue_file, 'wb') as f:
                f.write(encrypted)
            print(f"[LicenseManager] Saved {len(queue)} pending requests")
        except Exception as e:
            print(f"[LicenseManager] Error saving queue: {e}")
    
    # ========== Named API Keys (Multi-Key Support) ==========
    
    def save_named_api_key(self, name, api_key, service='openai'):
        """
        Save a named API key for a specific service.
        
        Args:
            name (str): User-friendly name for this key
            api_key (str): The actual API key
            service (str): Service name ('openai', 'groq', 'google', 'openrouter')
        """
        try:
            keys = self._load_named_api_keys()
            keys[name] = {'api_key': api_key, 'service': service}
            self._save_named_api_keys(keys)
            print(f"[LicenseManager] Saved API key: {name} ({service})")
        except Exception as e:
            print(f"[LicenseManager] Error saving API key: {e}")
    
    def list_named_api_keys(self):
        """
        List all stored API keys.
        
        Returns:
            dict: {name: {'api_key': ..., 'service': ...}}
        """
        return self._load_named_api_keys()
    
    def get_api_key_by_name(self, name):
        """
        Retrieve a specific API key by name.
        
        Args:
            name (str): API key name
        
        Returns:
            dict: {'api_key': ..., 'service': ...} or None
        """
        keys = self._load_named_api_keys()
        return keys.get(name)
    
    def delete_named_api_key(self, name):
        """Delete a named API key."""
        try:
            keys = self._load_named_api_keys()
            if name in keys:
                del keys[name]
                self._save_named_api_keys(keys)
                print(f"[LicenseManager] Deleted API key: {name}")
        except Exception as e:
            print(f"[LicenseManager] Error deleting API key: {e}")
    
    def delete_all_api_keys(self):
        """Delete all stored API keys."""
        try:
            self._save_named_api_keys({})
            print("[LicenseManager] Deleted all API keys")
        except Exception as e:
            print(f"[LicenseManager] Error deleting all API keys: {e}")
    
    def _load_named_api_keys(self):
        """Load and decrypt API keys storage."""
        if not os.path.exists(self.api_keys_file):
            return {}
        
        try:
            with open(self.api_keys_file, 'rb') as f:
                encrypted = f.read()
            data_str = self.cipher.decrypt(encrypted).decode()
            keys = json.loads(data_str)
            print(f"[LicenseManager] Loaded {len(keys)} API keys")
            return keys
        except Exception as e:
            print(f"[LicenseManager] Error loading API keys: {e}")
            return {}
    
    def _save_named_api_keys(self, keys_dict):
        """Encrypt and save API keys storage."""
        try:
            data_str = json.dumps(keys_dict)
            encrypted = self.cipher.encrypt(data_str.encode())
            with open(self.api_keys_file, 'wb') as f:
                f.write(encrypted)
            print(f"[LicenseManager] Saved {len(keys_dict)} API keys")
        except Exception as e:
            print(f"[LicenseManager] Error saving API keys: {e}")
    
    # ========== Legacy Single API Key Methods ==========
    # (For backward compatibility - internally use 'default' key name)
    
    def save_api_key(self, api_key, service='openai'):
        """Legacy: Save single API key as 'default'."""
        self.save_named_api_key('default', api_key, service)
    
    def load_api_key(self):
        """
        Legacy: Load single API key.
        
        Returns first API key if multiple exist.
        """
        keys = self._load_named_api_keys()
        if keys:
            first = next(iter(keys.values()))
            return first
        return None
    
    def delete_api_key(self):
        """Legacy: Delete single API key."""
        self.delete_all_api_keys()


def get_embedded_license_key():
    """
    Retrieve the static embedded app identifier.
    
    This is NOT a license key, but an app ID used to identify
    which application is requesting activation.
    
    Returns:
        str: Embedded app ID or None if not found
    """
    try:
        # Try to get from _MEIPASS (PyInstaller bundle)
        base_path = sys._MEIPASS
    except AttributeError:
        # Development mode
        base_path = os.path.abspath(".")
    
    key_file = os.path.join(base_path, 'embedded_license_key.txt')
    
    if os.path.exists(key_file):
        try:
            with open(key_file, 'r') as f:
                app_id = f.read().strip()
            print(f"[LicenseManager] Loaded embedded app ID: {app_id}")
            return app_id
        except Exception as e:
            print(f"[LicenseManager] Error reading embedded key file: {e}")
            return None
    else:
        print(f"[LicenseManager] Embedded key file not found at {key_file}")
        return None
