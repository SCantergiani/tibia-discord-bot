import json
from pathlib import Path

import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer

from tibiabot.tibiadata.client import NotFound, TibiaDataClient, TibiaDataError
from tibiabot.tibiadata.models import Character, Guild, KillStatistics, World, worlds_from_json

FIXTURES = Path(__file__).parent / "fixtures"


def fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


def test_character_parses_sheet_deaths_and_origin_timestamp():
    c = Character.from_json(fixture("character.json"))
    assert (c.name, c.level, c.vocation, c.world) == ("Abu Shusha", 131, "Exalted Monk", "Antica")
    assert c.origin_timestamp.isoformat() == "2026-05-30T14:57:58+00:00"
    assert c.deaths[0].level == 130
    assert c.deaths[0].killers[0].name == "mammoth"
    assert c.deaths[0].killers[0].player is False


def test_character_with_empty_guild_object_has_no_guild():
    c = Character.from_json(fixture("character.json"))
    assert c.guild_name is None


def test_absent_optional_fields_default_to_empty():
    c = Character.from_json(fixture("character.json"))
    assert (c.former_names, c.former_worlds, c.traded, c.comment) == ([], [], False, "")


def test_world_lists_online_players():
    w = World.from_json(fixture("world_antica.json"))
    assert w.name == "Antica"
    assert len(w.online_players) == 541
    assert w.online_players[0].name == "Abu Shusha"


def test_guild_members():
    g = Guild.from_json(fixture("guild.json"))
    assert g.name == "Wrath"
    assert len(g.members) == 585


def test_kill_statistics_entries():
    k = KillStatistics.from_json(fixture("killstatistics.json"))
    assert k.world == "Antica"
    assert k.entries[0].race == "(elemental forces)"
    assert k.entries[0].last_day_players_killed == 15


def test_world_list():
    assert len(worlds_from_json(fixture("worlds.json"))) == 93


class FakeTibiaData:
    """A real local HTTP server answering from a queue of (status, body) per path."""

    def __init__(self):
        self.replies: dict[str, list[tuple[int, dict | None]]] = {}
        self.hits: list[str] = []

    def reply(self, path: str, status: int = 200, body: dict | None = None) -> None:
        self.replies.setdefault(path, []).append((status, body))

    async def handle(self, request: web.Request) -> web.Response:
        self.hits.append(request.path)
        queue = self.replies.get(request.path) or [(404, None)]
        status, body = queue.pop(0) if len(queue) > 1 else queue[0]
        return web.json_response(body, status=status) if body is not None else web.Response(status=status)


@pytest.fixture
async def tibiadata():
    fake = FakeTibiaData()
    app = web.Application()
    app.router.add_get("/{tail:.*}", fake.handle)
    server = TestServer(app)
    await server.start_server()
    async with TibiaDataClient(str(server.make_url(""))) as client:
        yield fake, client
    await server.close()


async def test_client_retries_a_transient_failure(tibiadata):
    fake, client = tibiadata
    fake.reply("/v4/world/Antica", 503)
    fake.reply("/v4/world/Antica", body=fixture("world_antica.json"))
    world = await client.world("Antica")
    assert world.name == "Antica"
    assert len(fake.hits) == 2


async def test_client_does_not_retry_rate_limiting(tibiadata):
    fake, client = tibiadata
    fake.reply("/v4/world/Antica", 429)
    with pytest.raises(TibiaDataError):
        await client.world("Antica")
    assert len(fake.hits) == 1


async def test_unknown_character_is_not_found(tibiadata):
    fake, client = tibiadata
    fake.reply("/v4/character/Nobody Here", body={"character": {"character": {"name": ""}}, "information": {}})
    with pytest.raises(NotFound):
        await client.character("Nobody Here")


async def test_character_with_a_space_in_the_name(tibiadata):
    fake, client = tibiadata
    fake.reply("/v4/character/Abu Shusha", body=fixture("character.json"))
    assert (await client.character("Abu Shusha")).name == "Abu Shusha"
