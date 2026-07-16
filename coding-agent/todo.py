#!/usr/bin/env python3
"""Entry point for the todo CLI app.

Usage:
    python todo.py add "Buy groceries"
    python todo.py list
    python todo.py delete 1
"""

from todo.cli import main

if __name__ == "__main__":
    main()
