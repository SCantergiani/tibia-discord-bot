import asyncio

from tibiabot.commands_guide import SECTIONS, guide_embed, same_channel_name


def test_every_registered_command_is_explained():
    from tibiabot.bot import EXTENSIONS, TibiaBot
    from tibiabot.config import Settings

    async def registered():
        bot = TibiaBot(Settings(token="x", postgres_host="x", postgres_password="x"))
        bot.db._cache = object()  # some cogs keep a handle to it; nothing is queried here
        for ext in EXTENSIONS:
            await bot.load_extension(ext)
        names = {c.name for c in bot.tree.get_commands()}
        await bot.tibiadata.close()
        return names

    explained = {name for _, entries in SECTIONS for name, _ in entries}
    missing = asyncio.run(registered()) - explained
    assert not missing, f"commands missing from the guide: {missing}"


def test_guide_fits_discord_embed_limits():
    embed = guide_embed()
    assert len(embed) <= 6000 and all(len(f.value) <= 1024 for f in embed.fields)


def test_channel_names_match_how_discord_stores_them():
    assert same_channel_name("🖥️・ᴄᴏᴍᴍᴀɴᴅ-ʟᴏɢ", "🖥️・ᴄᴏᴍᴍᴀɴᴅ ʟᴏɢ")
    assert same_channel_name("📖・ᴄᴏᴍᴍᴀɴᴅs", "📖・ᴄᴏᴍᴍᴀɴᴅs")
    assert not same_channel_name("general", "📖・ᴄᴏᴍᴍᴀɴᴅs")
