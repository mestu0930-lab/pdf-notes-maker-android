[app]

title = PDF Notes Maker
package.name = pdfnotesmaker
package.domain = org.pdfnotesmaker

source.dir = .
source.include_exts = py,png,jpg,kv,atlas,json,html
source.include_patterns = assets/*,data/*,*.html,*.json,*.txt
source.exclude_exts = spec
source.exclude_patterns = tests/*,docs/*,build/*,*.pyc,__pycache__

version = 1.0.0

# -----------------------------------------------------------------------
# REQUIREMENTS — p4a recipes only
# Verified compatible with python-for-android==2024.1.21 + kivy==2.4.0
#
# Removed:
#   cffi        — conflicts with cryptography's bundled libffi (autoreconf crash)
#   pycparser   — only needed as a cffi dep, not standalone
#   openai      — no p4a recipe
#   pydantic    — no p4a recipe
#   httpx       — no p4a recipe
#   aiohttp     — no p4a recipe
# -----------------------------------------------------------------------
requirements =
    python3,
    kivy==2.4.0,
    requests==2.31.0,
    urllib3,
    certifi,
    charset-normalizer,
    idna,
    pypdf==3.17.1,
    markdown==3.5.1,
    python-dateutil==2.8.2,
    six==1.16.0,
    cryptography,
    aiofiles==23.2.1,
    pyjnius,
    plyer==2.1.0

garden_requirements =

android.permissions =
    INTERNET,
    READ_EXTERNAL_STORAGE,
    WRITE_EXTERNAL_STORAGE,
    ACCESS_NETWORK_STATE

android.api = 34
android.minapi = 21
android.ndk = 25c
android.ndk_api = 21
android.accept_sdk_license = True
android.archs = arm64-v8a,armeabi-v7a
android.release_artifact = apk
android.logcat_filters = *:S python:D
android.private_storage = True

android.icon = ./assets/icon.png
android.presplash = ./assets/presplash.png
android.orientation = portrait
android.fullscreen = False
android.immersive_mode = True

android.uses_internet = True
p4a.bootstrap = sdl2

android.meta_data =
    android.max_aspect = 2.5

android.entrypoint = org.kivy.android.PythonActivity

[buildozer]

log_level = 2
warn_on_root = 1
android.skip_update = False

[app:ios]
ios.requirements = pyobjc,lxml,requests,cryptography
