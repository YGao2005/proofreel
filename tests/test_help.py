from proofreel import cli


def test_short_help_is_short_and_names_real_commands(capsys):
    cli.command(["help"])
    short = capsys.readouterr().out
    assert len(short) < 1400
    commands = cli.parser()._subparsers._group_actions[0].choices
    for line in short.splitlines():
        if line.startswith("  "):
            assert line.split()[0] in commands, line


def test_help_all_is_the_full_help(capsys):
    cli.command(["help", "all"])
    assert capsys.readouterr().out.strip() == cli.__doc__.strip()
    assert len(cli.__doc__) > 6000
