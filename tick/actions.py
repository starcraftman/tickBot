"""
To facilitate complex actions based on commands create a
hierarchy of actions that can be recombined in any order.
All actions have async execute methods.
"""
import asyncio
import logging
import os
import shutil
import tempfile

import aiofiles
import aiomock
import discord
import sqlalchemy.orm.exc as sqla_oexc

import tick.exc
import tick.tbl
import tick.util
import tickdb
import tickdb.query
import tickdb.schema


TICKET_TIMEOUT = tick.util.get_config('ticket', 'timeout')
PIN_EMOJI = tick.util.get_config('emojis', 'pin')
YES_EMOJI = tick.util.get_config('emojis', '_yes')
NO_EMOJI = tick.util.get_config('emojis', '_no')
ADMIN_ROLE = tick.util.get_config('ticket', 'admin_role')

LOG_PERMS = discord.Permissions(read_messages=True, send_messages=True, attach_files=True)
SUPPORT_PERMS = discord.Permissions(read_messages=True, send_messages=True, manage_messages=True, add_reactions=True)
TICKET_PERMS = discord.Permissions(read_messages=True, manage_channels=True, add_reactions=True)

QUESTIONS = (
    "Could you briefly describe the topic? If you wish it to remain private, type no.",
    "What type of support you would like? For example: sympathy, distraction, advice, personal venting, etc ...",
    "How long you would like to be supported for?",
)
NAME_TEMPLATE = "{id}-{user:.10}-{taker:.10}"

PERMS_TEMPLATE = """This bot requires following perms for {}:
{}

Please correct permissions or choose another channel.
"""
TRANSCRIPT_HEADER = """Transcript of ticket {name} opened by {author}.
Opened on: {start}
Closed on: {end}
-----------------------------
"""
TRANSCRIPT_ENTRY = """{date} {author} ({id})
{msg}
-----------------------------
"""
LOG_TEMPLATE = """__Action__: {action}
__User__: {user}
{msg}
"""
TICKET_REQUEST_INFO = """
To request a ticket click on the existing reaction below.

A ticket is a private support session with a supporter who will try their best to help you.
You will be asked some questions to help narrow things down, please respond as best you can.
"""
PREAMBLE = """Hello. I understand you'd like support.
Please answer my questions one at a time and then we'll get you some help.

Do you need NSFW support? This would be for any adult topics or triggers as described in {chan} .
Please react below with {check} for NSFW or {cross} for regular support.
"""
REQUEST_PING = """Requesting support for '{user}', please respond {role}.
{q_text}

Please react to this message to take this ticket.
"""
TICKET_WELCOME = """{mention}
This is a __private__ ticket. Please follow all server and support guidelines.
It is logged and the log will be made available to user if requested.
If there are any issues please ping staff.

To close the ticket: `{prefix}ticket close A reason goes here.`
To rename the ticket: `{prefix}ticket A new name for ticket`
    Names of tickets should be < 100 characters and stick to spaces, letters, numbers and '-'.
"""

class Action():
    """
    Top level action, contains shared logic.
    """
    def __init__(self, **kwargs):
        self.args = kwargs['args']
        self.bot = kwargs['bot']
        self.msg = kwargs['msg']
        self.session = tickdb.Session()
        self.log = logging.getLogger(__name__)

    async def execute(self):
        """
        Take steps to accomplish requested action, including possibly
        invoking and scheduling other actions.
        """
        raise NotImplementedError


class Admin(Action):
    """
    Provide the ticket command.
    """
    async def active(self, guild_config):
        """
        Set the target category to create new tickets under.
        Cannot mention categories so pass a substring that is unique.

        Args:
            guild_config: The guild configuration to update.
        """
        _, three_ago, seven_ago = tickdb.query.get_active_tickets(self.session, guild_config.id)

        msg = "__Tickets No Activity 7 Days__\n"
        lines = [['Ticket Channel', 'Date']] + \
            [[tick.channel_name, tick.last_msg] for tick in seven_ago]
        msg += tick.tbl.wrap_markdown(tick.tbl.format_table(lines, header=True))
        await self.msg.channel.send(msg)

        msg = "\n\n__Tickets No Activity 3 Days__\n"
        lines = [['Ticket Channel', 'Date']] + \
            [[tick.channel_name, tick.last_msg] for tick in three_ago]
        msg += tick.tbl.wrap_markdown(tick.tbl.format_table(lines, header=True))
        await self.msg.channel.send(msg)

    async def category(self, guild_config):
        """
        Set the target category to create new tickets under.
        Cannot mention categories so pass a substring that is unique.

        Args:
            guild_config: The guild configuration to update.
        """
        logging.getLogger(__name__).info("Hello")
        substr = ' '.join(self.args.name).lower()
        matches = [x for x in self.msg.guild.categories if substr in x.name.lower()]
        if not matches or len(matches) != 1:
            raise tick.exc.InvalidCommandArgs("Could not match exactly 1 category. Try again!")
        logging.getLogger(__name__).info("Hello")
        cat = matches[0]
        logging.getLogger(__name__).info("Hello")

        if not TICKET_PERMS.is_subset(cat.permissions_for(cat.guild.me)):
            perms = """
        Read Messages
        Manage Channels
        Add Reactions"""
            raise tick.exc.InvalidPerms(PERMS_TEMPLATE.format("Ticket Category Channel", perms))

        guild_config.category_channel_id = cat.id
        self.session.add(guild_config)
        self.log.debug("Matched Category '%s' for guild %s", cat.name, cat.guild)

        return "Setting new tickets to be created under category:\n\n**%s**" % cat.name

    async def logs(self, guild_config):
        """
        Set the target logging channel.

        Args:
            guild_config: The guild configuration to update.
        """
        channel = self.msg.channel_mentions[0]
        if not LOG_PERMS.is_subset(channel.permissions_for(channel.guild.me)):
            perms = """
        Read Messages
        Send Messages
        Attach Files"""
            raise tick.exc.InvalidPerms(PERMS_TEMPLATE.format("Log Channel", perms))

        guild_config.log_channel_id = channel.id
        self.session.add(guild_config)

        return "Setting the logging channel to:\n\n**%s**" % channel.name

    async def support(self, guild_config):
        """
        Set the support pinned message to react to for support.

        Args:
            guild_config: The guild configuration to update.
        """
        channel = self.msg.channel_mentions[0]

        if not SUPPORT_PERMS.is_subset(channel.permissions_for(channel.guild.me)):
            perms = """
        Read Messages
        Send Messages
        Manage Messages
        Add Reactions"""
            raise tick.exc.InvalidPerms(PERMS_TEMPLATE.format("Support Channel", perms))

        sent = await channel.send(TICKET_REQUEST_INFO)
        await sent.pin()
        await sent.add_reaction(PIN_EMOJI)

        guild_config.support_channel_id = sent.channel.id
        guild_config.support_pin_id = sent.id
        return "Tickets can now be started by reacting to pinned message.\nIf you delete it just run support command again."

    async def role(self, guild_config):
        """
        Set the role to ping for tickets.

        Args:
            guild_config: The guild configuration to update.
        """
        role = self.msg.role_mentions[0]

        guild_config.role_id = role.id
        self.session.add(guild_config)

        return "Setting tickets to ping:\n\n**%s**" % role.name

    async def adult_role(self, guild_config):
        """
        Set the role to ping for adult tickets.

        Args:
            guild_config: The guild configuration to update.
        """
        role = self.msg.role_mentions[0]

        guild_config.adult_role_id = role.id
        self.session.add(guild_config)

        return "Setting adult tickets to ping:\n\n**%s**" % role.name

    async def execute(self):
        """
        Execute all admin tasks here.
        """
        if not [x for x in self.msg.author.roles if x.name == ADMIN_ROLE]:
            raise tick.exc.InvalidPerms("You are not a `Ticket Supervisor`. Please see an admin.")

        guild = self.msg.guild
        try:
            guild_config = tickdb.query.get_guild_config(self.session, guild.id)
        except (sqla_oexc.NoResultFound, sqla_oexc.MultipleResultsFound):
            guild_config = tickdb.schema.GuildConfig(id=guild.id)
            self.session.add(guild_config)
            self.session.commit()
            self.log.debug("Creating config for server: %s with id %d", guild.name, guild.id)
        self.log.info("Requested config of: %d\nFound: %s", guild.id, guild_config)

        func = getattr(self, self.args.subcmd)
        resp = await func(guild_config)
        self.session.commit()

        if resp:
            await self.msg.channel.send(resp)


class Ticket(Action):
    """
    Provide the ticket command.
    """
    async def close(self, _, log_channel):
        """
        Close a ticket.
        """
        try:
            ticket = tickdb.query.get_ticket(self.session, self.msg.guild.id, channel_id=self.msg.channel.id)
            user = self.msg.guild.get_member(ticket.user_id)
        except (sqla_oexc.NoResultFound, sqla_oexc.MultipleResultsFound) as e:
            raise tick.exc.InvalidCommandArgs("I can only close within ticket channels.") from e

        reason = ' '.join(self.args.reason)
        resp, fname = '', ''
        try:
            resp, msg = await wait_for_user_reaction(
                self.bot, self.msg.channel, self.msg.author,
                "Please confirm that you want to close ticket by reacting below.")
            if not resp:
                raise asyncio.TimeoutError

            fname = await create_log(msg, os.path.join(tempfile.mkdtemp(), self.msg.channel.name + ".txt"))
            await log_channel.send(
                LOG_TEMPLATE.format(action="Close", user=user.name,
                                    msg="__Reason:__ {}.".format(reason)),
                files=[discord.File(fp=fname, filename=os.path.basename(fname))]
            )

            resp, _ = await wait_for_user_reaction(
                self.bot, self.msg.channel, self.msg.author,
                "Closing ticket. Do you want a log of this ticket DMed??")
            if resp:
                await user.send("The log of your support session. Take care.",
                                files=[discord.File(fp=fname, filename=os.path.basename(fname))])
            await self.msg.channel.delete(reason=reason)
            self.session.delete(ticket)
        except asyncio.TimeoutError:
            await self.msg.channel.send("Cancelling request to close ticket.")
        except (sqla_oexc.NoResultFound, sqla_oexc.MultipleResultsFound):
            await self.msg.channel.send("A critical error found, database record could not be retrieved.")
        finally:
            try:
                shutil.rmtree(os.path.dirname(fname))
            except (FileNotFoundError, OSError):
                pass

    async def rename(self, _, log_channel):
        """
        Rename a ticket.
        """
        try:
            ticket = tickdb.query.get_ticket(self.session, self.msg.guild.id, channel_id=self.msg.channel.id)
        except (sqla_oexc.NoResultFound, sqla_oexc.MultipleResultsFound) as e:
            raise tick.exc.InvalidCommandArgs("I can only rename within ticket channels.")

        new_name = tick.util.clean_input(" ".join(self.args.name)).lower()[:100]
        if not new_name.startswith("{}-".format(ticket.id)):
            new_name = "{}-".format(ticket.id) + new_name
        old_name = self.msg.channel.name
        await self.msg.channel.edit(reason='New name was requested.', name=new_name)
        await log_channel.send(
            LOG_TEMPLATE.format(action="Rename", user=self.msg.author.name,
                                msg="__Old Name:__ {}\n__New Name:__ {}".format(old_name, new_name)),
        )

        return 'Rename completed.'

    async def execute(self):
        try:
            guild_config = tickdb.query.get_guild_config(self.session, self.msg.guild.id)
            log_channel = self.msg.guild.get_channel(guild_config.log_channel_id)
            # If log channel not configured, dev null log messages
            if not log_channel:
                log_channel = aiomock.AIOMock()
                log_channel.send.async_return_value = True
        except (sqla_oexc.NoResultFound, sqla_oexc.MultipleResultsFound) as e:
            raise tick.exc.InvalidCommandArgs("Tickets not configured. See `{prefix}admin`".format(prefix=self.bot.prefix)) from e

        func = getattr(self, self.args.subcmd)
        resp = await func(guild_config, log_channel)

        self.session.commit()
        if resp:
            await self.msg.channel.send(resp)


class Help(Action):
    """
    Provide an overview of help.
    """
    async def execute(self):
        prefix = self.bot.prefix
        over = [
            'Here is an overview of my commands.',
            '',
            'For more information do: `{}Command -h`'.format(prefix),
            '       Example: `{}drop -h`'.format(prefix),
            '',
        ]
        lines = [
            ['Command', 'Effect'],
            ['{prefix}admin', 'Configure the tickets'],
            ['{prefix}ticket', 'Manage tickets'],
            ['{prefix}status', 'Info about this bot'],
            ['{prefix}help', 'This help message'],
        ]
        lines = [[line[0].format(prefix=prefix), line[1]] for line in lines]

        response = '\n'.join(over) + tick.tbl.wrap_markdown(tick.tbl.format_table(lines, header=True))
        await self.bot.send_ttl_message(self.msg.channel, response)
        try:
            await self.msg.delete()
        except discord.NotFound:
            pass


class Status(Action):
    """
    Display the status of this bot.
    """
    async def execute(self):
        lines = [
            ['Created By', 'GearsandCogs'],
            ['Uptime', self.bot.uptime],
            ['Version', '{}'.format(tick.__version__)],
        ]

        await self.msg.channel.send(tick.tbl.wrap_markdown(tick.tbl.format_table(lines)))


class RequestGather():
    """
    A simple object to gather information from the user and reformat it.
    """
    def __init__(self, bot, chan, author):
        self.bot = bot
        self.chan = chan
        self.author = author
        self.questions = QUESTIONS
        self.responses = []

    async def get_info(self):
        """
        Allow the user to answer questions and keep the responses.

        Returns: True iff user needs an adult. Default False.
        """
        sent = []
        server_rules = discord.utils.get(self.chan.guild.channels, name='server-rules')
        adult_needed, msg = await wait_for_user_reaction(
            self.bot, self.chan, self.author, PREAMBLE.format(chan=server_rules.mention, check=YES_EMOJI, cross=NO_EMOJI))
        sent += [msg]

        try:
            for ind, question in enumerate(self.questions, start=1):
                sent += [await self.chan.send("{}) {}".format(ind, question))]
                resp = await self.bot.wait_for(
                    'message',
                    check=lambda m: m.author == self.author and m.channel == self.chan,
                    timeout=TICKET_TIMEOUT,
                )
                sent += [resp]
                self.responses += [resp.content]
        except asyncio.TimeoutError as e:
            raise tick.exc.InvalidCommandArgs("User failed to respond in time. Cancelling request.") from e
        finally:
            if sent:
                await self.chan.delete_messages(sent)

        return adult_needed

    def format(self, roles):
        """
        Returns a formatted message to summarize request.

        Args:
            roles: The roles to mention in the message.
        """
        role_msg = " ".join([x.mention for x in roles])
        q_text = ''
        for question, response in zip(self.questions, self.responses):
            q_text += "\n{}\n    {}".format(question, response)

        return REQUEST_PING.format(user=self.author.name, role=role_msg,
                                   prefix=self.bot.prefix, q_text=q_text)


async def ticket_request(client, chan, user, config):
    """
    Request a private ticket on the server. Engages in several steps to complete.
        - Gather information from user.
        - Ping required roles to get a response.
        - Responder reacts to message and must have right roles.
        - Ticket is created in database and private channel added on server.
        - Issue welcome message to channel.

    Args:
        client: An instance of the bot.
        user: The original requesting user.
        chan: The original requesting channel.
        config: A configuration for the guild.
    """
    guild = chan.guild

    gather = RequestGather(client, chan, user)
    roles = [guild.get_role(config.adult_role_id)]
    if not await gather.get_info() and config.role_id:
        roles = [guild.get_role(config.role_id)]

    log_channel = guild.get_channel(config.log_channel_id)
    if log_channel:
        await log_channel.send(
            LOG_TEMPLATE.format(action="Request", user=user.name,
                                msg="Request issued, waiting for responder.")
        )
    sent = await chan.send(gather.format(roles))
    await sent.add_reaction(YES_EMOJI)

    def check(c_react, c_user):
        can_respond = False
        for role in c_user.roles:
            if role in roles:
                can_respond = True

        return can_respond and str(c_react) == YES_EMOJI
    _, responder = await client.wait_for('reaction_add', check=check, timeout=TICKET_TIMEOUT)
    await sent.delete()

    ticket = tickdb.schema.Ticket(user_id=user.id, supporter_id=responder.id, guild_id=guild.id)
    session = tickdb.Session()
    session.add(ticket)
    session.flush()

    overwrites = {
        guild.default_role: discord.PermissionOverwrite(read_messages=False),
        guild.me: discord.PermissionOverwrite(read_messages=True,
                                              send_messages=True,
                                              manage_messages=True,
                                              manage_channels=True,
                                              read_message_history=True,
                                              add_reactions=True),
        user: discord.PermissionOverwrite(read_messages=True,
                                          send_messages=True,
                                          read_message_history=True,
                                          add_reactions=True),
        responder: discord.PermissionOverwrite(read_messages=True,
                                               send_messages=True,
                                               read_message_history=True,
                                               add_reactions=True),
    }
    ticket_name = tick.util.clean_input(NAME_TEMPLATE.format(
        id=ticket.id, user=user.name, taker=responder.name))
    ticket_category = [x for x in guild.categories if x.id == config.category_channel_id][0]
    ticket_channel = await guild.create_text_channel(name=ticket_name,
                                                     topic="A private ticket for {}.".format(user.name),
                                                     overwrites=overwrites,
                                                     category=ticket_category)
    ticket.channel_id = ticket_channel.id
    session.commit()

    if log_channel:
        await log_channel.send(
            LOG_TEMPLATE.format(action="Created", user=user.name,
                                msg="__Responder:__ {}\n__Channel:__ {} | {}".format(responder.name, chan.name, chan.mention)),
        )
    await ticket_channel.send(TICKET_WELCOME.format(prefix=client.prefix, mention=" ".join((user.mention, responder.mention))))


async def create_log(last_msg, fname=None):
    """
    Log a whole channel's history to a file for preservation.

    Args:
        filename: The path of the file to write out.
        last_msg: The last message sent in channel to archive

    Returns: The file path.
    """
    if not fname:
        fname = "{:50}.txt".format(last_msg.channel.name)
    async for msg in last_msg.channel.history(limit=1, oldest_first=True):
        first_msg = msg

    to_flush = ""
    async with aiofiles.open(fname, 'w') as fout:
        await fout.write(TRANSCRIPT_HEADER.format(name=last_msg.channel.name,
                                                  author=last_msg.author.name,
                                                  start=str(first_msg.created_at),
                                                  end=str(last_msg.created_at)))

        async for msg in last_msg.channel.history(oldest_first=True):
            to_flush += TRANSCRIPT_ENTRY.format(date=msg.created_at, author=msg.author.name,
                                                id=msg.author.id, msg=msg.content)
            if len(to_flush) > 10000:
                await fout.write(to_flush)
                to_flush = ""

        if to_flush:
            await fout.write(to_flush)

    return fname


async def wait_for_user_reaction(client, chan, author, text, *, yes=YES_EMOJI, no=NO_EMOJI):
    """
    A simple reusable mechanism to present user with a choice and wait for reaction.

    Args:
        client: The bot client.
        orig_msg: A previous message in desired channel from author.
        text: The message to send to channel.
    Kwargs:
        yes: The yes emoji to use in unicode.
        no: The no emoji to use in unicode.

    Returns: (Boolean, msg_sent)
        True if user accepted otherwise False.
    """
    msg = await chan.send(text)

    await msg.add_reaction(yes)
    await msg.add_reaction(no)

    def check(react, user):
        return user == author and str(react) in (yes, no)

    react, _ = await client.wait_for('reaction_add', check=check, timeout=TICKET_TIMEOUT)

    return str(react) == yes, msg


async def bot_shutdown(bot):  # pragma: no cover
    """
    Shutdown the bot. Gives background jobs grace window to finish  unless empty.
    """
    logging.getLogger(__name__).error('FINAL SHUTDOWN REQUESTED')
    await bot.logout()


def user_info(user):  # pragma: no cover
    """
    Trivial message formatter based on user information.
    """
    lines = [
        ['Username', '{}#{}'.format(user.name, user.discriminator)],
        ['ID', str(user.id)],
        ['Status', str(user.status)],
        ['Join Date', str(user.joined_at)],
        ['All Roles:', str([str(role) for role in user.roles[1:]])],
        ['Top Role:', str(user.top_role).replace('@', '@ ')],
    ]
    return '**' + user.display_name + '**\n' + tick.tbl.wrap_markdown(tick.tbl.format_table(lines))
