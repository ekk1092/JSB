import sys
import os

print(f"Python Executable: {sys.executable}")
print(f"Python Version: {sys.version}")

try:
    import docx
    print("Successfully imported docx")
    print(f"docx file: {docx.__file__}")
except ImportError as e:
    print(f"Failed to import docx: {e}")

try:
    import pypdf
    print("Successfully imported pypdf")
except ImportError as e:
    print(f"Failed to import pypdf: {e}")
