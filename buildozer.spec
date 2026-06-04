[app]

# ── Identity ──────────────────────────────────────────────────────────────────
title = PDF Notes Maker
package.name = pdfnotesmaker
package.domain = com.mestu0930.pdfnotes          # ← VERIFY: use your actual domain

# ── Versioning ─────────────────────────────────────────────────────────────────
version = 1.0.0

# ── Source files ───────────────────────────────────────────────────────────────
source.dir = .
source.include_exts = py,png,jpg,kv,atlas,txt,json,ttf,otf
# CRITICAL: txt must be here for embedded_license_key.txt to be bundled

source.exclude_dirs = tests,bin,.buildozer,__pycache__,.git,venv,.venv
source.exclude_exts = pyc,pyo,spec

# ── Entry point ────────────────────────────────────────────────────────────────
# Buildozer expects main.py — already correct in your project.

# ── Requirements ───────────────────────────────────────────────────────────────
# List every PyPI package your app imports.
# Pure-stdlib imports (os, json, hashlib, hmac, uuid, etc.) do NOT go here.
# pyjnius enables jnius imports on Android.
requirements = python3,kivy==2.3.1,kivymd,pyjnius,requests,Pillow,openai,httpx,pypdf,python-docx,lxml,markdown

# If pdf_notes_app_kivy.py uses the openai package, ADD one of these lines:
#   Option A (safest — old requests-based version):
#     requirements = ...,openai==0.28.1
#   Option B (skip openai package, call REST directly with requests):
#     (no change needed, just use requests in your code)

# ── Icon & presplash ───────────────────────────────────────────────────────────
icon.filename = %(source.dir)s/icon.png
presplash.filename = %(source.dir)s/icon.png

# ── Orientation ────────────────────────────────────────────────────────────────
orientation = all

# ── Android SDK / NDK ─────────────────────────────────────────────────────────
android.api = 33
android.minapi = 21
android.ndk = 25c
android.ndk_api = 21
android.accept_sdk_license = True

# ── Build type ─────────────────────────────────────────────────────────────────
android.archs = arm64-v8a,armeabi-v7a
# Use arm64-v8a only for faster debug builds:
#   android.archs = arm64-v8a

# ── Permissions ────────────────────────────────────────────────────────────────
android.permissions = \
    INTERNET,\
    READ_EXTERNAL_STORAGE,\
    WRITE_EXTERNAL_STORAGE,\
    READ_MEDIA_IMAGES,\
    READ_MEDIA_VIDEO

# ── p4a bootstrap ──────────────────────────────────────────────────────────────
p4a.bootstrap = sdl2

# ── Gradle ─────────────────────────────────────────────────────────────────────
android.gradle_dependencies =
android.enable_androidx = True

# ── App meta ───────────────────────────────────────────────────────────────────
fullscreen = 0

[buildozer]
log_level = 2
warn_on_root = 1
