# license_manager.py (pure Python, no cryptography dependency)
# FIXES vs original:
#   1. [ANDROID] get_embedded_license_key(): use __file__-relative path as
#      primary lookup so the .txt is found inside the APK on Android.
#      sys._MEIPASS is PyInstaller-only; os.path.abspath(".") resolves to "/"
#      on Android, so the key file was never found on-device.
#   2. [COMPAT]  Added an explicit digestmod= kwarg to every hmac.new() call
#      so the code works without deprecation warnings on Python 3.8–3.13
#      (digestmod became required by strict-mode in 3.8+).
#   3. [COMPAT]  datetime.fromisoformat() guarded with ValueError/TypeError
#      so a malformed expiry string won't crash the license check on device.
# ---------------------------------------------------------------------------

import os
import json
import hashlib
import hmac as hmac_lib
import uuid
import platform
import sys
import base64
from datetime import datetime


class LicenseManager:
    def __init__(self):
        self.license_dir   = os.path.join(os.path.expanduser("~"), ".pdf_notes_maker")
        self.license_file  = os.path.join(self.license_dir, "license.dat")
        self.queue_file    = os.path.join(self.license_dir, "request_queue.json")
        self.api_keys_file = os.path.join(self.license_dir, "api_keys.dat")
        os.makedirs(self.license_dir, exist_ok=True)

    # ---------- Encryption helpers (Fernet-like, pure Python) ----------
    @staticmethod
    def _derive_key(password: bytes, salt: bytes) -> bytes:
        """PBKDF2 via hashlib – no external deps required."""
        return hashlib.pbkdf2_hmac('sha256', password, salt, 100_000, dklen=32)

    @staticmethod
    def _encrypt(plaintext: bytes, password: bytes) -> bytes:
        salt = os.urandom(16)
        iv   = os.urandom(16)
        key  = LicenseManager._derive_key(password, salt)
        # XOR stream cipher: keystream built from HMAC-SHA256 blocks.
        keystream = b''
        counter   = 0
        while len(keystream) < len(plaintext):
            # FIX #2: pass digestmod= explicitly (required on Python 3.8+)
            keystream += hmac_lib.new(
                key,
                salt + iv + counter.to_bytes(4, 'big'),
                digestmod=hashlib.sha256,
            ).digest()
            counter += 1
        ciphertext = bytes(a ^ b for a, b in zip(plaintext, keystream[:len(plaintext)]))
        # Layout: salt(16) | iv(16) | ciphertext
        return salt + iv + ciphertext

    @staticmethod
    def _decrypt(encrypted: bytes, password: bytes) -> bytes:
        salt       = encrypted[:16]
        iv         = encrypted[16:32]
        ciphertext = encrypted[32:]
        key        = LicenseManager._derive_key(password, salt)
        keystream  = b''
        counter    = 0
        while len(keystream) < len(ciphertext):
            # FIX #2: explicit digestmod
            keystream += hmac_lib.new(
                key,
                salt + iv + counter.to_bytes(4, 'big'),
                digestmod=hashlib.sha256,
            ).digest()
            counter += 1
        plaintext = bytes(a ^ b for a, b in zip(ciphertext, keystream[:len(ciphertext)]))
        return plaintext

    # ---------- Hardware ID ----------
    def get_hwid(self) -> str:
        # 1. Try Android ANDROID_ID
        try:
            from jnius import autoclass
            SettingsSecure = autoclass('android.provider.Settings$Secure')
            PythonActivity = autoclass('org.kivy.android.PythonActivity')
            context        = PythonActivity.mActivity
            android_id     = SettingsSecure.getString(
                context.getContentResolver(), SettingsSecure.ANDROID_ID
            )
            if android_id:
                return hashlib.sha256(android_id.encode()).hexdigest()[:16]
        except Exception:
            pass

        # 2. Desktop fallback: MAC address + platform info
        try:
            node        = uuid.getnode()
            system_info = f"{platform.node()}-{platform.machine()}-{platform.processor()}"
            combined    = f"{node}-{system_info}"
            return hashlib.sha256(combined.encode()).hexdigest()[:16]
        except Exception:
            pass

        # 3. Last resort: persist a random ID to disk
        hwid_file = os.path.join(self.license_dir, ".hwid")
        if os.path.exists(hwid_file):
            with open(hwid_file, 'r') as f:
                return f.read().strip()
        new_hwid = str(uuid.uuid4()).replace('-', '')[:16]
        with open(hwid_file, 'w') as f:
            f.write(new_hwid)
        return new_hwid

    # ---------- License ----------
    def save_license(self, license_data: dict) -> None:
        license_data['hwid'] = self.get_hwid()
        data_str  = json.dumps(license_data)
        password  = self.get_hwid().encode()
        encrypted = self._encrypt(data_str.encode(), password)
        with open(self.license_file, 'wb') as f:
            f.write(encrypted)

    def load_license(self):
        if not os.path.exists(self.license_file):
            return None
        try:
            with open(self.license_file, 'rb') as f:
                encrypted = f.read()
            password = self.get_hwid().encode()
            data_str = self._decrypt(encrypted, password).decode()
            return json.loads(data_str)
        except Exception:
            return None

    def is_license_valid(self) -> bool:
        lic = self.load_license()
        if not lic:
            return False
        if lic.get('hwid') != self.get_hwid():
            return False
        if lic.get('status') != 'active':
            return False
        if 'expiry' in lic and lic['expiry']:
            # FIX #3: guard against malformed ISO date strings
            try:
                expiry = datetime.fromisoformat(lic['expiry'])
                if datetime.now() > expiry:
                    return False
            except (ValueError, TypeError):
                pass
        return True

    def get_license_info(self):
        lic = self.load_license()
        if not lic:
            return None
        return {
            'email':   lic.get('email', 'N/A'),
            'key':     lic.get('key', 'N/A')[-8:],
            'status':  lic.get('status', 'unknown'),
            'expires': lic.get('expiry', 'Never'),
        }

    # ---------- Pending Activation Requests ----------
    def save_pending_activation(self, email: str, hwid: str,
                                receipt_path: str, app_id: str) -> None:
        queue        = self._load_queue()
        request_data = {
            'app_id':       app_id,
            'email':        email,
            'hwid':         hwid,
            'receipt_path': receipt_path,
            'timestamp':    datetime.now().isoformat(),
            'retry_count':  0,
        }
        queue.append(request_data)
        self._save_queue(queue)

    def get_pending_requests(self):
        return self._load_queue()

    def delete_pending_request(self, index_or_request) -> None:
        queue = self._load_queue()
        if isinstance(index_or_request, int):
            if 0 <= index_or_request < len(queue):
                queue.pop(index_or_request)
        else:
            queue = [r for r in queue if r != index_or_request]
        self._save_queue(queue)

    def _load_queue(self):
        if not os.path.exists(self.queue_file):
            return []
        try:
            with open(self.queue_file, 'rb') as f:
                encrypted = f.read()
            password = self.get_hwid().encode()
            data_str = self._decrypt(encrypted, password).decode()
            return json.loads(data_str)
        except Exception:
            return []

    def _save_queue(self, queue) -> None:
        data_str  = json.dumps(queue)
        password  = self.get_hwid().encode()
        encrypted = self._encrypt(data_str.encode(), password)
        with open(self.queue_file, 'wb') as f:
            f.write(encrypted)

    # ---------- Named API Keys ----------
    def save_named_api_key(self, name: str, api_key: str,
                           service: str = 'openai') -> None:
        keys       = self._load_named_api_keys()
        keys[name] = {'api_key': api_key, 'service': service}
        self._save_named_api_keys(keys)

    def list_named_api_keys(self):
        return self._load_named_api_keys()

    def get_api_key_by_name(self, name: str):
        keys = self._load_named_api_keys()
        return keys.get(name)

    def delete_named_api_key(self, name: str) -> None:
        keys = self._load_named_api_keys()
        if name in keys:
            del keys[name]
            self._save_named_api_keys(keys)

    def delete_all_api_keys(self) -> None:
        self._save_named_api_keys({})

    def _load_named_api_keys(self):
        if not os.path.exists(self.api_keys_file):
            return {}
        try:
            with open(self.api_keys_file, 'rb') as f:
                encrypted = f.read()
            password = self.get_hwid().encode()
            data_str = self._decrypt(encrypted, password).decode()
            return json.loads(data_str)
        except Exception:
            return {}

    def _save_named_api_keys(self, keys_dict: dict) -> None:
        data_str  = json.dumps(keys_dict)
        password  = self.get_hwid().encode()
        encrypted = self._encrypt(data_str.encode(), password)
        with open(self.api_keys_file, 'wb') as f:
            f.write(encrypted)

    # ---------- Legacy single-key shims (backward-compat) ----------
    def save_api_key(self, api_key: str, service: str = 'openai') -> None:
        self.save_named_api_key('default', api_key, service)

    def load_api_key(self):
        keys = self._load_named_api_keys()
        if keys:
            return next(iter(keys.values()))
        return None

    def delete_api_key(self) -> None:
        self.delete_all_api_keys()


# ---------------------------------------------------------------------------
# Standalone helper – imported by both main.py and pdf_notes_app_kivy.py
# ---------------------------------------------------------------------------
def get_embedded_license_key():
    """
    Return the content of embedded_license_key.txt, or None if not found.

    Search order (FIX #1 – Android path resolution):
      1. PyInstaller bundle  (sys._MEIPASS)                  – desktop .exe builds
      2. Directory of this .py / compiled module (__file__)  – APK assets / source tree
      3. Current working directory                           – last-resort fallback

    The original code used only os.path.abspath(".") as its non-PyInstaller
    fallback; on Android that resolves to "/" so the .txt file inside the
    APK was never found.  Using __file__-relative lookup fixes this.
    """
    candidates = []

    # 1. PyInstaller bundle
    try:
        candidates.append(sys._MEIPASS)          # type: ignore[attr-defined]
    except AttributeError:
        pass

    # 2. Directory of this source / compiled file (correct for Android APK)
    try:
        candidates.append(os.path.dirname(os.path.abspath(__file__)))
    except Exception:
        pass

    # 3. CWD fallback
    candidates.append(os.path.abspath('.'))

    for base in candidates:
        key_file = os.path.join(base, 'embedded_license_key.txt')
        if os.path.exists(key_file):
            try:
                with open(key_file, 'r') as f:
                    return f.read().strip()
            except Exception:
                continue

    return None
