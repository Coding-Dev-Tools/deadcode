"""pytest configuration — add project src to Python path."""

import site
import sys
from pathlib import Path

# Add user site-packages (contains pathspec, rich, click for Python 3.12)
user_site = site.getusersitepackages()
if user_site and user_site not in sys.path:
    sys.path.insert(0, user_site)

# Add src directory to Python path so tests can import deadcode package
src_dir = Path(__file__).parent / "src"
if str(src_dir) not in sys.path:
    sys.path.insert(0, str(src_dir))

