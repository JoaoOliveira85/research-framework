from research_framework.cli._parser import build_parser


def test_parser_registers_refresh_sources_subcommand() -> None:
    p = build_parser()
    args = p.parse_args(["refresh-sources", "--vault", "/tmp/v"])
    assert args.command == "refresh-sources"
    assert args.func.__module__.endswith("refresh_sources")
