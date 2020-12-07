"""
This is the main bot. Everything is started upon main() execution. To invoke from root:
    python -m tick.bot

Some useful docs on libraries
-----------------------------
Python 3.5 async tutorial:
    https://snarky.ca/how-the-heck-does-async-await-work-in-python-3-5/

asyncio (builtin package):
    https://docs.python.org/3/library/asyncio.html

discord.py: The main discord library, hooks events.
    https://discordpy.readthedocs.io/en/latest/api.html

aiozmq: Async python bindings for zmq. (depends on pyzmq)
    https://aiozmq.readthedocs.io/en/v0.8.0/

ZeroMQ: Listed mainly as a reference for core concepts.
    http://zguide.zeromq.org/py:all
"""
import asyncio
import datetime
import logging
import os
import pprint
import re

import discord
import sqlalchemy
import websockets.exceptions
try:
    import uvloop
    asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())
    asyncio.get_event_loop().set_debug(True)
except ImportError:
    print("Falling back to default python loop.")
finally:
    print("Default event loop:", asyncio.get_event_loop())

import tick.actions
import tick.exc
import tick.parse
import tick.util
import tickdb.query


SYNC_NOTICE = """Synchronizing sheet changes.

Your command will resume after a short delay of about {} seconds. Thank you for waiting."""
SYNC_RESUME = """{} Resuming your command:
    **{}**"""


class EmojiResolver():
    """
    Map emoji embeds onto the text required to make them appear.
    """
    def __init__(self):
        # For each guild, store a dict of emojis on that guild
        self.emojis = {}

    def __str__(self):
        """ Just dump the emoji db. """
        return pprint.pformat(self.emojis, indent=2)

    def update(self, guilds):
        """
        Update the emoji dictionary. Call this in on_ready.
        """
        for guild in guilds:
            emoji_names = [emoji.name for emoji in guild.emojis]
            self.emojis[guild.name] = dict(zip(emoji_names, guild.emojis))

    def fix(self, content, guild):
        """
        Expand any emojis for bot before sending, based on guild emojis.

        Embed emojis into the content just like on guild surrounded by ':'. Example:
            Status :Fortifying:
        """
        emojis = self.emojis[guild.name]
        for embed in list(set(re.findall(r':\S+:', content))):
            try:
                emoji = emojis[embed[1:-1]]
                content = content.replace(embed, str(emoji))
            except KeyError:
                logging.getLogger(__name__).warning(
                    'EMOJI: Could not find emoji %s for guild %s', embed, guild.name)

        return content


class TickBot(discord.Client):
    """
    The main bot, hooks onto on_message primarily and waits for commands.
    """
    def __init__(self, prefix, **kwargs):
        super().__init__(**kwargs)
        self.prefix = prefix
        self.emoji = EmojiResolver()
        self.parser = tick.parse.make_parser(prefix)
        self.start_date = datetime.datetime.utcnow().replace(microsecond=0)

    @property
    def uptime(self):  # pragma: no cover
        """
        Return the uptime since bot was started.
        """
        return str(datetime.datetime.utcnow().replace(microsecond=0) - self.start_date)

    def get_member_by_substr(self, name):
        """
        Given a (substring of a) member name, find the first member that has a similar name.
        Not case sensitive.

        Returns: The discord.Member object or None if nothing found.
        """
        name = name.lower()
        for member in self.get_all_members():
            if name in member.display_name.lower():
                return member

        return None

    def get_channel_by_name(self, name):
        """
        Given channel name, get the Channel object requested.
        There shouldn't be any collisions.

        Returns: The discord.Channel object or None if nothing found.
        """
        return discord.utils.get(self.get_all_channels(), name=name)

    # Events hooked by bot.
    async def on_member_join(self, member):
        """ Called when member joins guild (login). """
        log = logging.getLogger(__name__)
        log.info('Member has joined: %s', member.display_name)

    async def on_member_leave(self, member):
        """ Called when member leaves guild (logout). """
        log = logging.getLogger(__name__)
        log.info('Member has left: %s', member.display_name)

    async def on_guild_emojis_update(self, *_):
        """ Called when emojis change, just update all emojis. """
        self.emoji.update(self.guilds)

    async def on_raw_reaction_add(self, payload):
        """
        Monitor reactions on pinned messages for support.
        When reactions are added, initiate a new request for support.
        """
        try:
            chan = self.get_channel(payload.channel_id)
            if isinstance(chan, discord.DMChannel) or payload.member == self.user:
                return

            config = tickdb.query.get_guild_config(tickdb.Session(), chan.guild.id)
            coro = None
            msg = await chan.fetch_message(payload.message_id)

            if ((config.support_pin_id and msg.id == config.support_pin_id)
                    or (config.practice_pin_id and msg.id == config.practice_pin_id)):
                for reaction in msg.reactions:
                    if str(reaction) == tick.actions.PIN_EMOJI and reaction.count > 1:
                        await reaction.remove(payload.member)
                        if msg.id == config.support_pin_id:
                            coro = tick.actions.ticket_request(self, chan, payload.member, config)
                        elif msg.id == config.practice_pin_id:
                            coro = tick.actions.practice_ticket_request(self, chan, payload.member, config)
                    elif str(reaction) != tick.actions.PIN_EMOJI:
                        await reaction.clear()
            if coro:
                await coro
        except (sqlalchemy.orm.exc.NoResultFound, discord.errors.NotFound):
            pass
        except tick.exc.UserException as exc:
            await self.send_ttl_message(chan, exc.reply(), ttl=10)

    async def on_ready(self):
        """
        Event triggered when connection established to discord and bot ready.
        """
        log = logging.getLogger(__name__)
        log.info('Logged in as: %s', self.user.name)
        log.info('Available on following guilds:')
        for guild in self.guilds:
            log.info('  "%s" with id %s', guild.name, guild.id)

        self.emoji.update(self.guilds)
        print('Bot Ready!')

    async def ignore_message(self, message):
        """
        Determine whether the message should be ignored.

        Ignore messages not directed at bot and any commands that aren't
        from an admin during deny_commands == True.
        """
        # Ignore lines not directed at bot
        if message.author.bot or not message.content.startswith(self.prefix):
            return True

        if isinstance(message.channel, discord.abc.PrivateChannel):
            await message.channel.send("Bot will not respond to private commands.")
            return True

        return False

    async def on_message_edit(self, before, after):
        """
        Only process commands that were different from before.
        """
        if before.content != after.content and after.content.startswith(self.prefix):
            await self.on_message(after)

    async def on_message(self, message):
        """
        Intercepts every message sent to guild!

        Notes:
            message.author - Returns member object
                roles -> List of Role objects. First always @everyone.
                    roles[0].name -> String name of role.
            message.channel - Channel object.
                name -> Name of channel
                guild -> guild of channel
                    members -> Iterable of all members
                    channels -> Iterable of all channels
                    get_member_by_name -> Search for user by nick
            message.content - The text
        """
        content = message.content
        author = message.author
        channel = message.channel

        # TODO: Better filtering, use a loop and filter funcs.
        if await self.ignore_message(message):
            return

        log = logging.getLogger(__name__)
        log.info("guild: '%s' Channel: '%s' User: '%s' | %s",
                 channel.guild, channel.name, author.name, content)

        try:
            edit_time = message.edited_at
            content = re.sub(r'<[#@]\S+>', '', content).strip()  # Strip mentions from text
            args = self.parser.parse_args(re.split(r'\s+', content))
            await self.dispatch_command(args=args, bot=self, msg=message)

        except tick.exc.ArgumentParseError as exc:
            log.exception("Failed to parse command. '%s' | %s", author.name, content)
            exc.write_log(log, content=content, author=author, channel=channel)
            if 'invalid choice' not in exc.message:
                try:
                    self.parser.parse_args(content.split(' ')[0:1] + ['--help'])
                except tick.exc.ArgumentHelpError as exc2:
                    exc.message = 'Invalid command use. Check the command help.'
                    exc.message += '\n{}\n{}'.format(len(exc.message) * '-', exc2.message)

            await self.send_ttl_message(channel, exc.reply())
            try:
                if edit_time == message.edited_at:
                    await message.delete()
            except discord.DiscordException:
                pass

        except tick.exc.UserException as exc:
            exc.write_log(log, content=content, author=author, channel=channel)

            await self.send_ttl_message(channel, exc.reply())
            try:
                if edit_time == message.edited_at:
                    await message.delete()
            except discord.DiscordException:
                pass

    async def dispatch_command(self, **kwargs):
        """
        Simply inspect class and dispatch command. Guaranteed to be valid.
        """
        args = kwargs.get('args')
        cls = getattr(tick.actions, args.cmd)
        await cls(**kwargs).execute()

    async def send_ttl_message(self, destination, content, **kwargs):
        """
        Behaves excactly like Client.send_message except:
            After sending message wait 'ttl' seconds then delete message.

        Extra Kwargs:
            ttl: The time message lives before deletion (default 30s)
        """
        try:
            ttl = kwargs.pop('ttl')
        except KeyError:
            ttl = tick.util.get_config('ttl')

        content += '\n\n__This message will be deleted in {} seconds__'.format(ttl)
        message = await destination.send(content, **kwargs)

        await asyncio.sleep(ttl)
        try:
            await message.delete()
        except discord.NotFound:
            pass


async def presence_task(bot, delay=180):
    """
    Manage the ultra important task of bot's played game.
    """
    print('Presence task started')
    lines = [
        "Chilling'",
        "Moving those bits around.",
        "Pondering the meaning of the virtual universe.",
    ]
    ind = 0
    while True:
        try:
            await bot.change_presence(activity=discord.Game(name=lines[ind]))
        except websockets.exceptions.ConnectionClosed:
            pass

        ind = (ind + 1) % len(lines)
        await asyncio.sleep(delay)


def main():  # pragma: no cover
    """ Entry here! """
    tick.util.init_logging()
    intents = discord.Intents.default()
    intents.members = True
    tick.util.BOT = TickBot(tick.util.get_config('prefix', default='!'), intents=intents)

    token = tick.util.get_config('discord', os.environ.get('TOKEN', 'dev'))
    print("Waiting on connection to Discord ...")
    try:
        loop = asyncio.get_event_loop()
        # BLOCKING: N.o. e.s.c.a.p.e.
        loop.run_until_complete(tick.util.BOT.start(token))
    except KeyboardInterrupt:
        loop.run_until_complete(tick.util.BOT.logout())
    finally:
        loop.close()


if __name__ == "__main__":  # pragma: no cover
    main()
