from tibiabot.tibiadata.models import WorldSummary
from tibiabot.worlds import WorldList, formal


def test_formal_world_name():
    assert formal("  aNtIcA ") == "Antica"


class FakeClient:
    def __init__(self):
        self.calls = 0

    async def worlds(self):
        self.calls += 1
        return [WorldSummary("Antica", "Open PvP", 1), WorldSummary("Bona", "Optional PvP", 1)]


async def test_resolve_accepts_any_casing_and_rejects_unknown_worlds():
    worlds = WorldList(FakeClient())
    assert await worlds.resolve("antica") == "Antica"
    assert await worlds.resolve("Atlantis") is None


async def test_world_list_is_cached():
    client = FakeClient()
    worlds = WorldList(client)
    await worlds.names()
    await worlds.names()
    assert client.calls == 1
