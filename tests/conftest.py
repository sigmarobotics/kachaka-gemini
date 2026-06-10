import os
import sys

# Backend modules import each other by bare name (flat layout in Docker),
# so put src/backend on sys.path.
BACKEND_DIR = os.path.join(os.path.dirname(__file__), "..", "src", "backend")
sys.path.insert(0, os.path.abspath(BACKEND_DIR))
