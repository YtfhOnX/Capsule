import sys
from .app import main

if len(sys.argv) == 1:
    from .launcher import main as gui
    gui()
else:
    sys.exit(main())
