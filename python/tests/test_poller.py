from tibiabot.poller import WorldPoller
from tibiabot.tibiadata.client import NotFound, TibiaDataError
from tibiabot.tibiadata.models import Character, OnlinePlayer, World


def world(*names: str) -> World:
    return World("Antica", "online", len(names), "Open PvP", True,
                 [OnlinePlayer(n, 100, "Knight") for n in names])


def sheet(name: str) -> Character:
    return Character(name=name, level=100, vocation="Knight", world="Antica", sex="male", guild_name=None,
                     guild_rank=None, former_names=[], former_worlds=[], last_login=None, account_status="",
                     traded=False, deletion_date=None, comment="")


class FakeClient:
    def __init__(self):
        self.online: World | Exception = world()

    async def world(self, name: str) -> World:
        if isinstance(self.online, Exception):
            raise self.online
        return self.online


class FakeSheets:
    def __init__(self, missing=()):
        self.missing = set(missing)
        self.asked: list[str] = []

    async def get(self, name: str) -> Character:
        self.asked.append(name)
        if name in self.missing:
            raise NotFound(name)
        return sheet(name)


async def test_tick_fetches_sheets_for_everyone_online_and_notifies_listeners():
    client, sheets, seen = FakeClient(), FakeSheets(), []
    client.online = world("A", "B")

    async def listener(snapshot):
        seen.append(snapshot)

    poller = WorldPoller("Antica", client, sheets, [listener])
    snap = await poller.tick()
    assert set(snap.characters) == {"A", "B"}
    assert snap.first_tick is True
    assert seen == [snap]


async def test_someone_who_just_logged_out_is_still_fetched():
    client, sheets = FakeClient(), FakeSheets()
    poller = WorldPoller("Antica", client, sheets, [])
    client.online = world("A", "B")
    await poller.tick()
    client.online = world("A")
    snap = await poller.tick()
    assert snap.recently_offline == ["B"]
    assert "B" in snap.characters
    assert snap.first_tick is False


async def test_a_name_that_no_longer_exists_stops_being_followed():
    client, sheets = FakeClient(), FakeSheets(missing={"B"})
    poller = WorldPoller("Antica", client, sheets, [])
    client.online = world("A", "B")
    await poller.tick()
    client.online = world("A")
    snap = await poller.tick()
    assert snap.recently_offline == []


async def test_an_unavailable_world_skips_the_tick():
    client, sheets, seen = FakeClient(), FakeSheets(), []
    client.online = TibiaDataError("down")

    async def listener(snapshot):
        seen.append(snapshot)

    assert await WorldPoller("Antica", client, sheets, [listener]).tick() is None
    assert seen == []


async def test_a_failing_listener_does_not_stop_the_others():
    client, sheets, seen = FakeClient(), FakeSheets(), []
    client.online = world("A")

    async def broken(snapshot):
        raise RuntimeError("boom")

    async def listener(snapshot):
        seen.append(snapshot)

    await WorldPoller("Antica", client, sheets, [broken, listener]).tick()
    assert len(seen) == 1
