"""ListService against a real Postgres and a fake TibiaData; skipped without one."""

import os
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from tibiabot.config import Settings
from tibiabot.db.database import Database
from tibiabot.db.repos import WorldConfig
from tibiabot.lists import repo
from tibiabot.lists.service import ListService
from tibiabot.poller import WorldSnapshot
from tibiabot.state import BotState
from tibiabot.tibiadata.client import NotFound, TibiaDataError
from tibiabot.tibiadata.models import Character, Guild, GuildMember

pytestmark = pytest.mark.skipif(not (os.getenv("POSTGRES_HOST") and os.getenv("POSTGRES_PASSWORD")),
                                reason="needs a Postgres (POSTGRES_HOST, POSTGRES_PASSWORD)")

GUILD_ID = 999000111222444


def char(name, world="Antica", traded=False, deletion=None):
    return Character(name=name, level=200, vocation="Elite Knight", world=world, sex="male", guild_name="Wrath",
                     guild_rank="Member", former_names=[], former_worlds=[], last_login=None, account_status="",
                     traded=traded, deletion_date=deletion, comment="")


class FakeSheets:
    def __init__(self):
        self.known: dict[str, Character] = {"bubble": char("Bubble"), "charm": char("Charm")}
        self.down: set[str] = set()

    async def get(self, name):
        if name.lower() in self.down:
            raise TibiaDataError("down")
        if name.lower() not in self.known:
            raise NotFound(name)
        return self.known[name.lower()]


class FakeTibiaData:
    async def guild(self, name):
        if name.lower() != "wrath":
            raise NotFound(name)
        return Guild("Wrath", "Antica", [GuildMember("Member One", "Member", "Knight", 100, "online"),
                                         GuildMember("Member Two", "Member", "Druid", 90, "offline")])


class FakeGuild:
    id = GUILD_ID
    name = "Test"

    def get_member(self, _):
        return None

    def get_channel(self, _):
        return None


@pytest.fixture
async def service():
    settings = Settings(token="x", postgres_host=os.environ["POSTGRES_HOST"],
                        postgres_password=os.environ["POSTGRES_PASSWORD"],
                        postgres_port=int(os.getenv("POSTGRES_PORT", "5432")))
    db = Database(settings)
    await db.start()
    await db.init_guild(GUILD_ID)
    await db.cache.execute("DELETE FROM list")
    state = BotState()
    state.set_world(GUILD_ID, WorldConfig("Antica", "1", "0", "0", "2", "3", "4", "5", "6", "7"))
    bot = SimpleNamespace(db=db, state=state, sheets=FakeSheets(), tibiadata=FakeTibiaData(),
                          get_guild=lambda _: None)
    svc = ListService(bot)
    yield svc
    await db.drop_guild(GUILD_ID)
    await db.close()


async def test_add_sorts_names_into_outcomes(service):
    service.bot.sheets.down.add("laggy")
    out = await service.add_many(FakeGuild(), True, "player", ["Bubble", "Nobody", "Laggy"], "ks", "42", "rat")
    assert (out.added, out.not_found, out.unavailable) == (["Bubble"], ["Nobody"], ["Laggy"])
    entry = service.of(GUILD_ID).hunted_players["bubble"]
    assert (entry.reason, entry.reason_text, entry.added_by, entry.tag) == ("true", "ks", "42", "rat")


async def test_adds_survive_a_restart(service):
    await service.add_many(FakeGuild(), True, "player", ["Bubble"], "", "42")
    await service.add_many(FakeGuild(), False, "guild", ["Wrath"], "", "42")
    await service.load(GUILD_ID)
    lists = service.of(GUILD_ID)
    assert set(lists.hunted_players) == {"bubble"} and set(lists.allied_guilds) == {"wrath"}


async def test_readding_counts_as_already_and_retags(service):
    await service.add_many(FakeGuild(), True, "player", ["Bubble"], "", "42")
    out = await service.add_many(FakeGuild(), True, "player", ["bubble"], "", "42", "bot")
    assert out.already == ["bubble"] and out.added == []
    assert service.of(GUILD_ID).hunted_players["bubble"].tag == "bot"


async def test_guild_add_records_its_roster(service):
    out = await service.add_many(FakeGuild(), True, "guild", ["wrath", "Nope Guild"], "", "42")
    assert out.added == ["Wrath"] and out.not_found == ["Nope Guild"]
    assert await repo.activity_counts(await service.bot.db.guild(GUILD_ID)) == {"wrath": 2}


async def test_remove_and_clear(service):
    await service.add_many(FakeGuild(), True, "player", ["Bubble", "Charm"], "", "42")
    out = await service.remove_many(FakeGuild(), True, "player", ["bubble", "Ghost"])
    assert out.added == ["bubble"] and out.not_found == ["Ghost"]
    assert await service.clear(FakeGuild(), True) == (1, 0)
    await service.load(GUILD_ID)
    assert service.of(GUILD_ID).hunted_players == {}


async def test_list_is_drawn_from_the_cached_sheet(service):
    await service.add_many(FakeGuild(), True, "player", ["Bubble"], "", "42")
    page = (await service.embeds(FakeGuild(), True))[1].description
    assert "## Antica" in page and "**200**" in page and "Bubble" in page


async def test_poll_flags_a_listed_player_who_got_traded(service):
    await service.add_many(FakeGuild(), True, "player", ["Bubble"], "", "42")
    snapshot = WorldSnapshot("Antica", 0, [], characters={"Bubble": char("Bubble", traded=True)})
    await service.on_snapshot(snapshot)
    assert service.of(GUILD_ID).hunted_players["bubble"].flagged_reason == "traded"


async def test_prune_removes_after_grace_if_still_true_and_spares_otherwise(service):
    await service.add_many(FakeGuild(), True, "player", ["Bubble", "Charm"], "", "42")
    lists = service.of(GUILD_ID)
    long_ago = (datetime.now(timezone.utc) - timedelta(days=8)).isoformat()
    lists.hunted_players["bubble"] = lists.hunted_players["bubble"].with_(flagged_reason="traded", flagged_at=long_ago)
    lists.hunted_players["charm"] = lists.hunted_players["charm"].with_(flagged_reason="world", flagged_at=long_ago)
    service.bot.sheets.known["bubble"] = char("Bubble", traded=True)
    await service._prune_flagged(GUILD_ID)
    assert "bubble" not in lists.hunted_players
    assert lists.hunted_players["charm"].flagged_reason == ""


async def test_prune_never_removes_on_a_failed_lookup(service):
    await service.add_many(FakeGuild(), True, "player", ["Bubble"], "", "42")
    lists = service.of(GUILD_ID)
    long_ago = (datetime.now(timezone.utc) - timedelta(days=8)).isoformat()
    lists.hunted_players["bubble"] = lists.hunted_players["bubble"].with_(flagged_reason="gone", flagged_at=long_ago)
    service.bot.sheets.down.add("bubble")
    await service._prune_flagged(GUILD_ID)
    assert "bubble" in lists.hunted_players


async def test_rosters_load_and_refresh(service):
    await service.add_many(FakeGuild(), True, "guild", ["Wrath"], "", "42")
    assert service.of(GUILD_ID).listed("Member One")
    await service.load(GUILD_ID)
    assert service.of(GUILD_ID).rosters["wrath"] == {"member one", "member two"}
    real_guild = service.bot.tibiadata.guild

    async def recruited(name):
        g = await real_guild(name)
        return Guild(g.name, g.world, [*g.members, GuildMember("New Recruit", "Member", "Knight", 10, "online")])

    service.bot.tibiadata.guild = recruited
    await service.refresh_rosters()
    assert service.of(GUILD_ID).listed("New Recruit")
    await service.load(GUILD_ID)
    assert "new recruit" in service.of(GUILD_ID).rosters["wrath"]


async def test_removing_a_guild_forgets_its_roster(service):
    await service.add_many(FakeGuild(), True, "guild", ["Wrath"], "", "42")
    await service.remove_many(FakeGuild(), True, "guild", ["wrath"])
    assert not service.of(GUILD_ID).listed("Member One")
