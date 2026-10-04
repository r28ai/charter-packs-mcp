"""Families: every workflow names tools that ship, and the server offers them as prompts."""

from __future__ import annotations

import re

import pytest
from charter import schema_tokens

from charter_packs_mcp import FAMILIES, Workflow, resolve, tools_for, workflows_for

ALL = [workflow for family in FAMILIES.values() for workflow in family.workflows]

# The widest family, product, is 74,058 tokens of schema once
# `gsheets.spreadsheets_create` and `notion.pages_create` ship narrowed; ops was
# 108,918 before they did. A family over this line is carrying a tool that needs
# the same treatment, and is about to be the heaviest server a directory lists.
TOKEN_CEILING = 80_000


def test_every_step_names_a_tool_a_pack_ships():
    for family in FAMILIES.values():
        tools = family.tools()  # raises KeyError naming the step that is wrong
        assert len(tools) == len(family.steps)


def test_every_workflow_crosses_apps():
    """A family is sold on interoperability; a one-app workflow belongs to a pack."""
    single = [w.title for w in ALL if len(w.apps) < 2]
    assert not single, single


def test_prompt_names_are_unique_across_every_family():
    """Families combine on one server, so a name must not collide with another family's."""
    names = [w.name for w in ALL]
    assert len(names) == len(set(names))
    for name in names:
        assert re.fullmatch(r"[a-z0-9_]{1,64}", name), name


def test_a_prompt_names_tools_as_the_server_publishes_them():
    workflow = FAMILIES["engineering"].workflows[0]
    text = workflow.render()
    for step in workflow.steps:
        assert f"`{step.replace('.', '_', 1)}`" in text
    assert "Context from me" not in text
    assert workflow.render("repo r28ai/charter").endswith("Context from me: repo r28ai/charter")


def test_a_prompt_has_the_agent_connect_missing_apps_before_it_asks_for_anything():
    """Asked to run a workflow with nothing connected, Claude asked which repo first and
    only found out GitHub was missing on the call after. And told to name a credential
    error's variable, it led with GITHUB_TOKEN instead of the login command."""
    text = FAMILIES["engineering"].workflows[0].render()
    assert "Before anything else" in text and "not connected" in text
    assert "variable" not in text


def test_a_shared_tool_is_served_once():
    support, finance = FAMILIES["support"], FAMILIES["finance"]
    shared = set(support.steps) & set(finance.steps)
    assert shared, "the two families stopped sharing a tool; pick two that do"
    combined = tools_for([support, finance])
    assert len(combined) == len(set(support.steps) | set(finance.steps))


def test_resolve_takes_lists_and_refuses_what_it_does_not_know():
    assert [f.key for f in resolve(["support,finance", "support"])] == ["support", "finance"]
    with pytest.raises(ValueError, match="unknown family"):
        resolve(["support,nope"])
    with pytest.raises(ValueError, match="at least one"):
        resolve([""])


@pytest.mark.parametrize("key", sorted(FAMILIES))
def test_each_family_stays_under_the_token_ceiling(key):
    tokens = sum(schema_tokens(tool) for tool in FAMILIES[key].tools())
    assert tokens <= TOKEN_CEILING, f"{key} is {tokens:,} tokens of schema"


async def test_the_server_offers_workflows_as_prompts_beside_their_tools():
    pytest.importorskip("mcp", reason="needs the [mcp] extra")
    from charter.adapters.mcp import build_server

    families = resolve(["engineering"])
    server = build_server(tools_for(families), name="dev", prompts=workflows_for(families))

    prompts = await server.list_prompts()
    assert [p.name for p in prompts] == [w.name for w in families[0].workflows]
    assert [a.name for a in prompts[0].arguments] == ["details"]
    assert prompts[0].arguments[0].required is False

    result = await server.get_prompt(prompts[0].name, {"details": "repo r28ai/charter"})
    text = result.messages[0].content.text
    assert text == families[0].workflows[0].render("repo r28ai/charter")

    listed = {tool.name for tool in await server.list_tools()}
    assert listed == {f"{step.split('.')[0]}_{step.split('.')[1]}" for step in families[0].steps}


def test_a_workflow_is_a_plain_value():
    workflow = Workflow(
        "x", "A → B", ("gmail.messages_list", "slack.chat_post_message"), "y", "daily"
    )
    assert workflow.name == "a_to_b"
    assert workflow.apps == ("gmail", "slack")
