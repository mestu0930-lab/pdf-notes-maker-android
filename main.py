# main.py – Android entry point for PDF Notes Maker
# No changes needed vs original; included here for completeness.
# ---------------------------------------------------------------------------
import os
import sys

# Ensure all sibling modules are importable regardless of CWD
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Load embedded license key once at startup (makes it available for the app)
from license_manager import get_embedded_license_key
_ = get_embedded_license_key()

# Start the Kivy application
from pdf_notes_app_kivy import PDFNotesMakerApp

if __name__ == '__main__':
    PDFNotesMakerApp().run()
