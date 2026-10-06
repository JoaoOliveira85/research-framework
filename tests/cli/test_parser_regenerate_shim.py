from research_framework.cli._parser import build_parser


def test_parser_registers_regenerate_shim_subcommand() -> None:
    p = build_parser()
    args = p.parse_args(["regenerate-shim", "--vault", "/tmp/v", "--force"])
    assert args.command == "regenerate-shim"
    assert args.func.__module__.endswith("regenerate_shim")
