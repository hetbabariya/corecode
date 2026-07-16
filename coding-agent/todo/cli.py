"""Argparse CLI entry point for the todo app."""

from __future__ import annotations

import argparse
import sys

from todo.commands import add_todo, delete_todo, list_todos


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="todo",
        description="A simple command-line todo manager.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # --- add ---
    p_add = sub.add_parser("add", help="Add a new todo item")
    p_add.add_argument("title", help="Text for the new todo")

    # --- list ---
    sub.add_parser("list", help="List all todo items")

    # --- delete ---
    p_del = sub.add_parser("delete", help="Delete a todo item by its ID")
    p_del.add_argument("id", type=int, help="Numeric ID of the todo to delete")

    return parser


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "add":
        add_todo(args.title)
    elif args.command == "list":
        list_todos()
    elif args.command == "delete":
        delete_todo(args.id)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
