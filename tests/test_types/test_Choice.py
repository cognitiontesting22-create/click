import click


def test_choice_get_invalid_choice_message():
    choice = click.Choice(["a", "b", "c"])
    message = choice.get_invalid_choice_message("d", ctx=None)
    assert message == "'d' is not one of 'a', 'b', 'c'."


def test_choice_strip():
    choice = click.Choice(["a", "b"], strip=True)
    assert choice.convert("  a ", None, None) == "a"
    assert choice.convert("b\t", None, None) == "b"
    assert choice.to_info_dict()["strip"] is True


def test_choice_strip_default_off(runner):
    @click.command()
    @click.option("--mode", type=click.Choice(["fast", "slow"]))
    def cli(mode):
        click.echo(mode)

    result = runner.invoke(cli, ["--mode", " fast"])
    assert result.exit_code == 2
    assert "' fast' is not one of 'fast', 'slow'." in result.output
    assert click.Choice(["fast"]).to_info_dict()["strip"] is False
