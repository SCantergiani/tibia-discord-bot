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
        self.fresh: list[str] = []

    def peek(self, name: str) -> Character | None:
        return None

    async def get(self, name: str, fresh: bool = False) -> Character:
        self.asked.append(name)
        if fresh:
            self.fresh.append(name)
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


async def test_priority_characters_are_fetched_fresh_every_tick():
    client, sheets = FakeClient(), FakeSheets()
    client.online = world("Enemy", "Neutral")
    poller = WorldPoller("Antica", client, sheets, [], priority=lambda w, name, sheet: name == "Enemy")
    await poller.tick()
    assert sheets.fresh == ["Enemy"]


from tibiabot.poller import FastLane  # noqa: E402


def enemies_only(world, name, sheet):
    return name.startswith("Enemy")


async def test_fast_lane_waits_for_the_first_full_poll():
    client, sheets = FakeClient(), FakeSheets()
    poller = WorldPoller("Antica", client, sheets, [], priority=enemies_only, fast_lane=FastLane(5, 1))
    assert await poller.fast_tick() is None


async def test_fast_lane_refreshes_only_priority_names_freshly_as_a_partial_snapshot():
    client, sheets, seen = FakeClient(), FakeSheets(), []

    async def listener(snapshot):
        seen.append(snapshot)

    client.online = world("Enemy A", "Neutral")
    poller = WorldPoller("Antica", client, sheets, [listener], priority=enemies_only, fast_lane=FastLane(5, 1))
    await poller.tick()
    assert sheets.fresh == []  # the full poll leaves prioritised names to the fast lane
    snap = await poller.fast_tick()
    assert snap.partial and set(snap.characters) == {"Enemy A"} and sheets.fresh == ["Enemy A"]
    assert seen[-1] is snap


async def test_fast_lane_puts_the_just_logged_out_first_and_rotates_within_budget():
    client, sheets = FakeClient(), FakeSheets()
    client.online = world("Enemy A", "Enemy B", "Enemy C", "Enemy D")
    poller = WorldPoller("Antica", client, sheets, [], priority=enemies_only, fast_lane=FastLane(1, 2))
    await poller.tick()
    client.online = world("Enemy A", "Enemy B", "Enemy C")  # Enemy D logged out
    await poller.tick()
    assert poller.fast_candidates() == ["Enemy D", "Enemy A"]
    assert poller.fast_candidates() == ["Enemy D", "Enemy B"]
    assert poller.fast_candidates() == ["Enemy D", "Enemy C"]


def test_budget_is_requests_per_interval():
    assert FastLane(5, 2).budget == 10 and FastLane(1, 0.1).budget == 1


async def test_neutral_sheets_are_skipped_when_nobody_wants_them():
    client, sheets = FakeClient(), FakeSheets()
    client.online = world("Enemy A", "Neutral")
    poller = WorldPoller("Antica", client, sheets, [], relevant=enemies_only, wants_neutrals=lambda w: False)
    snap = await poller.tick()
    assert set(snap.characters) == {"Enemy A"}


async def test_neutral_sheets_are_fetched_when_someone_wants_them():
    client, sheets = FakeClient(), FakeSheets()
    client.online = world("Enemy A", "Neutral")
    poller = WorldPoller("Antica", client, sheets, [], relevant=enemies_only, wants_neutrals=lambda w: True)
    assert set((await poller.tick()).characters) == {"Enemy A", "Neutral"}


class CountingClient(FakeClient):
    def __init__(self):
        super().__init__()
        self.calls = 0

    async def world(self, name):
        self.calls += 1
        return await super().world(name)


async def test_watch_spots_a_changed_online_list_and_the_poll_reuses_it():
    client, sheets = CountingClient(), FakeSheets()
    client.online = world("A")
    poller = WorldPoller("Antica", client, sheets, [], priority=enemies_only, fast_lane=FastLane(5, 1))
    await poller.tick()
    assert await poller.watch() is False  # unchanged
    client.online = world("A", "Enemy New")
    assert await poller.watch() is True
    calls = client.calls
    snap = await poller.tick()
    assert client.calls == calls  # the watched list was handed over, not fetched again
    assert {p.name for p in snap.online} == {"A", "Enemy New"}
