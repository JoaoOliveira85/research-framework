"""Allow `python -m research_framework` to invoke the CLI."""

import sys

from research_framework.cli import main

sys.exit(main())
