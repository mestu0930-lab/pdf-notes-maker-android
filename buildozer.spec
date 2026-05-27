[app]

# (str) Title of your application
title = PDF Notes Maker

# (str) Package name
package.name = pdfnotesmaker

# (str) Package domain (needed for android/ios packaging)
package.domain = org.pdfnotesmaker

# (source.dir) Source code directory where the main.py live
source.dir = .

# (source.include_exts) Source include extensions (let empty to include all the files)
source.include_exts = py,png,jpg,kv,atlas,json,html

# (source.include_patterns) Patterns to include from source directory
source.include_patterns = assets/*,data/*,*.html,*.json,*.txt

# (source.exclude_exts) Source exclude extensions
source.exclude_exts = spec

# (source.exclude_patterns) Patterns to exclude from source directory
source.exclude_patterns = tests/*,docs/*,build/*,*.pyc,__pycache__

# (version) Application versioning (method 1)
version = 1.0.0

# (version.regex) Regex string to find the version from buildozer.spec file
# version.regex = __version__ = ['"](.*)['"]   ← REMOVED (conflict with 'version')

# (version.filename) File where the version is stored
version.filename = %(source.dir)s/main.py

# (requirements) comma separated list of requirements android/ios
# The format is "library (optional version)"
requirements = 
    python3,
    kivy==2.3.0,
    requests==2.31.0,
    httpx==0.25.2,
    aiohttp==3.9.1,
    openai==1.3.9,
    pydantic==2.5.0,
    pydantic-core==2.14.5,
    typing-extensions==4.8.0,
    pypdf==3.17.1,
    python-docx==0.8.11,
    markdown==3.5.1,
    python-dateutil==2.8.2,
    cryptography==41.0.7,
    cffi==1.16.0,
    pycparser==2.21,
    aiofiles==23.2.1,
    pyjnius==1.7.0,
    plyer==2.1.0

# (garden_requirements) Comma separated list of garden requirements
garden_requirements = 

# (permissions) Needed permissions on android
android.permissions = 
    INTERNET,
    READ_EXTERNAL_STORAGE,
    WRITE_EXTERNAL_STORAGE,
    ACCESS_NETWORK_STATE,
    ACCESS_FINE_LOCATION

# (android.api_target) Highest API level the app targets
android.api_target = 34

# (android.minapi) Minimum API level required
android.minapi = 21

# (android.ndk) NDK version
android.ndk = 25c

# (android.ndk_api) API level for NDK
android.ndk_api = 21

# (android.accept_sdk_license) Accept Android SDK license
android.accept_sdk_license = True

# (android.arch) Target architecture
android.archs = arm64-v8a,armeabi-v7a

# (android.features) Required device features
android.features = android.hardware.usb.host

# (android.release_artifact) Release artifact type
android.release_artifact = apk

# (android.logcat_filters) Logcat filter strings
android.logcat_filters = *:S python:D

# (android.private_storage) Use private storage
android.private_storage = True

# ========== Icons & Branding ==========

# (android.icon) Icon location (192x192 PNG recommended)
android.icon = ./assets/icon.png

# (android.presplash) Presplash image (512x512 PNG recommended)
android.presplash = ./assets/presplash.png

# (android.presplash_lottie) Lottie animation for presplash
# android.presplash_lottie = ./assets/presplash.json

# (android.orientation) App orientation
android.orientation = portrait

# (android.fullscreen) Fullscreen mode
android.fullscreen = False

# (android.immersive_mode) Immersive mode (hides system UI)
android.immersive_mode = True

# ========== Manifest Configuration ==========

# (android.uses_internet) Uses internet permission
android.uses_internet = True

# (android.bootstrap) Bootstrap to use   ← CHANGED to p4a.bootstrap
p4a.bootstrap = sdl2

# (android.app_theme) Application theme
# android.app_theme = @android:style/Theme.Material.Light.DarkActionBar

# (android.meta_data) Additional metadata
android.meta_data = 
    android.max_aspect = 2.5

# ========== Gradle Configuration ==========

# (android.gradle_dependencies) Gradle dependencies
android.gradle_dependencies = 

# (android.add_src) Additional source files to add
# android.add_src = 

# (android.entrypoint) Java entry point (leave as is for standard Kivy)
android.entrypoint = org.kivy.android.PythonActivity

# ========== Build Configuration ==========

[buildozer]

# (log_level) {0, 1, 2} or {quiet, info, debug}
log_level = 2

# (warn_on_root) Warn if buildozer is run as root
warn_on_root = 1

# (android.skip_update) Skip update of android/gradle
android.skip_update = False

# (android.gradle_options) Gradle options to pass
# android.gradle_options = org.gradle.jvmargs=-Xmx4096m

# ========== Optional: Signing Configuration ==========

# (android.keystore) Keystore file path
# android.keystore = /path/to/your/keystore.jks

# (android.keystore_alias) Keystore alias
# android.keystore_alias = my_key

# (android.keystore_passwd) Keystore password (NOT recommended - use environment variable)
# android.keystore_passwd = your_keystore_password

# ========== iOS Configuration (Optional) ==========

[app:ios]

# (ios.requirements) iOS specific requirements
ios.requirements = pyobjc,lxml,requests,httpx,openai,pydantic,cryptography

# (ios.codesign_identity) Codesign identity
# ios.codesign_identity = iPhone Developer

# (ios.provisioning_profile_specifier) Provisioning profile
# ios.provisioning_profile_specifier = 

# (ios.entitlements_plist_content) Entitlements
# ios.entitlements_plist_content = 
