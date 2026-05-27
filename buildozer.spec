[app]

# (str) Title of your application
title = PDF Notes Maker

# (str) Package name
package.name = pdfnotesmaker

# (str) Package domain (needed for android/ios packaging)
package.domain = org.pdfnotesmaker

# (source.dir) Source code directory where the main.py live
source.dir = .

# (source.include_exts) Source files to include
source.include_exts = py,png,jpg,kv,atlas,json,html

# (source.include_patterns) Patterns to include
source.include_patterns = assets/*,data/*,*.html,*.json,*.txt

# (source.exclude_exts) Files to exclude
source.exclude_exts = spec

# (source.exclude_patterns) Patterns to exclude
source.exclude_patterns = tests/*,docs/*,build/*,*.pyc,__pycache__

# (version) Application version — only one versioning method allowed
version = 1.0.0

# (requirements) Only p4a-compatible packages go here.
# Heavy packages like openai, pydantic, httpx, aiohttp are NOT p4a recipes
# and cause HTTP 404 download errors during build — do NOT add them here.
requirements =
    python3,
    kivy==2.3.0,
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
    cffi,
    pycparser==2.21,
    aiofiles==23.2.1,
    pyjnius,
    plyer==2.1.0

# NOTE: openai, pydantic, pydantic-core, httpx, aiohttp, typing-extensions
# are NOT available as p4a recipes and will cause HTTP 404 build failures.
# Bundle them manually via a custom p4a recipe if your app needs them.

# (garden_requirements) Leave empty unless using Kivy Garden widgets
garden_requirements =

# (permissions) Android permissions
android.permissions =
    INTERNET,
    READ_EXTERNAL_STORAGE,
    WRITE_EXTERNAL_STORAGE,
    ACCESS_NETWORK_STATE

# (android.api) Target API level
android.api = 34

# (android.minapi) Minimum API level
android.minapi = 21

# (android.ndk) NDK version to use
android.ndk = 25c

# (android.ndk_api) NDK API level
android.ndk_api = 21

# (android.accept_sdk_license) Auto-accept SDK licenses
android.accept_sdk_license = True

# (android.archs) Target architectures
android.archs = arm64-v8a,armeabi-v7a

# (android.release_artifact) Output type
android.release_artifact = apk

# (android.logcat_filters) Logcat filter
android.logcat_filters = *:S python:D

# (android.private_storage) Use private app storage
android.private_storage = True

# ========== Icons & Branding ==========

android.icon = ./assets/icon.png
android.presplash = ./assets/presplash.png
android.orientation = portrait
android.fullscreen = False
android.immersive_mode = True

# ========== Manifest ==========

android.uses_internet = True

# FIX: renamed from deprecated android.bootstrap
p4a.bootstrap = sdl2

android.meta_data =
    android.max_aspect = 2.5

android.entrypoint = org.kivy.android.PythonActivity

# ========== Build Configuration ==========

[buildozer]

log_level = 2
warn_on_root = 1
android.skip_update = False

# ========== iOS (Optional) ==========

[app:ios]
ios.requirements = pyobjc,lxml,requests,cryptography
