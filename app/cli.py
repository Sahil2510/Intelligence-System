import argparse
import sys


def _run_playground(args: argparse.Namespace) -> None:
    import uvicorn

    uvicorn.run(
        "app.playground:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
    )


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="luvio",
        description="Luvio intelligence system CLI",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser(
        "run",
        help="Start the Luvio playground server",
    )
    run_parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Host to bind (default: 127.0.0.1)",
    )
    run_parser.add_argument(
        "--port",
        type=int,
        default=8000,
        help="Port to bind (default: 8000)",
    )
    run_parser.add_argument(
        "--reload",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Enable auto-reload for development (default: enabled)",
    )
    run_parser.set_defaults(func=_run_playground)

    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
