"""
To facilitate complex actions based on commands create a
hierarchy of actions that can be recombined in any order.
All actions have async execute methods.
"""
import asyncio
import logging
import os

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


# TODO: Put some of this in config.yml?
ADMIN_ROLE = "Ticket Supervisor"
LOG_PERMS = discord.Permissions(read_messages=True, send_messages=True, attach_files=True)
SUPPORT_PERMS = discord.Permissions(read_messages=True, send_messages=True, manage_messages=True)
TICKET_PERMS = discord.Permissions(read_messages=True, manage_channels=True)
PERMS_TEMPLATE = """This bot requires following perms for {}:
{}

Please correct permissions or choose another channel.
"""
NAME_TEMPLATE = "{id}-{user:.10}-{taker:.10}"
TICKET_WELCOME = """This is a __private__ ticket. Please follow all server and support guidelines.
It is logged and the log will be made available to user if requested.
If there are any issues please ping staff.

To close the ticket: `{prefix}ticket close A reason goes here.`
To rename the ticket: `{prefix}ticket A new name for ticket`
    Names of tickets should be < 100 characters and stick to spaces, letters, numbers and '-'.
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
QUESTIONS = (
    "1) Are there any triggers involved or is the topic NSFW as detailed in #server-rules ?",
    "2) What type of support you would like (sympathy, distraction, advice, personal venting, etc) ?",
    "3) How long you would like to be supported for?",
)
PREAMBLE = """Hello. I understand you'd like support.
Please answer my questions one at a time and then we'll get you some help.

"""
REQUEST_PING = """Requesting support for '{user}', please respond {role}.
{q_text}

Please use command `{prefix}ticket take @{user}` to respond."
"""
LOG_TEMPLATE = """__Action__: {action}
__User__: {user}
{msg}
"""


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
        Manage Channels"""
            raise tick.exc.InvalidPerms(PERMS_TEMPLATE.format("Ticket Category Channel", perms))

        guild_config.category_channel_id = cat.id
        self.session.add(guild_config)
        self.log.debug("Matched Category '%s' for guild %s", cat.name, cat.guild)

        return "Setting new tickets to be created under category:\n\n__%s__" % cat.name

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

        return "Setting the logging channel to:\n\n__%s__" % channel.name

    async def support(self, guild_config):
        """
        Set the support channel to monitor.

        Args:
            guild_config: The guild configuration to update.
        """
        channel = self.msg.channel_mentions[0]

        if not SUPPORT_PERMS.is_subset(channel.permissions_for(channel.guild.me)):
            perms = """
        Read Messages
        Send Messages
        Manage Messages"""
            raise tick.exc.InvalidPerms(PERMS_TEMPLATE.format("SUpport Channel", perms))

        guild_config.support_channel_id = channel.id
        self.session.add(guild_config)

        return "Setting command monitoring to:\n\n__%s__" % channel.name

    async def role(self, guild_config):
        """
        Set the role to ping for tickets.

        Args:
            guild_config: The guild configuration to update.
        """
        role = self.msg.role_mentions[0]

        guild_config.role_id = role.id
        self.session.add(guild_config)

        return "Setting tickets to ping:\n\n__%s__" % role.name

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
            guild_config = tickdb.schema.GuildConfig(id=guild.id, name=guild.name)
            self.session.add(guild_config)
            self.session.commit()
            self.log.debug("Creating config for server: %s with id %d", guild.name, guild.id)
        self.log.info("Requested config of: %d\nFound: %s", guild.id, guild_config)

        func = getattr(self, self.args.subcmd)
        resp = await func(guild_config)
        self.session.commit()

        if resp:
            await self.msg.channel.send(resp)


class RequestGather():
    """
    A simple object to gather information from the user and reformat it.
    """
    def __init__(self, bot, orig_msg, role):
        self.bot = bot
        self.msg = orig_msg
        self.role = role
        self.questions = QUESTIONS
        self.responses = []

    @property
    def chan(self):
        return self.msg.channel

    @property
    def author(self):
        return self.msg.author

    async def get_info(self):
        """
        Allow the user to answer questions and keep the responses.
        """
        preamble, sent = PREAMBLE, []

        try:
            for question in self.questions:
                if preamble:
                    question = preamble + question
                    preamble = None

                sent += [await self.chan.send(question)]
                resp = await self.bot.wait_for(
                    'message',
                    check=lambda m: m.author == self.author and m.channel == self.chan,
                    timeout=30,
                )
                sent += [resp]
                self.responses += [resp.content]
        except asyncio.TimeoutError as e:
            raise tick.exc.InvalidCommandArgs("User failed to respond in time. Cancelling request.") from e
        finally:
            if sent:
                await self.chan.delete_messages(sent)

    def format(self):
        """
        Returns a formatted message to summarize request.
        """
        q_text = ''
        for question, response in zip(self.questions, self.responses):
            q_text += "\n{}\n    {}".format(question, response)

        return REQUEST_PING.format(user=self.author.name, role=self.role.mention,
                                   prefix=self.bot.prefix, q_text=q_text)


class Ticket(Action):
    """
    Provide the ticket command.
    """
    async def request(self, guild_config, log_channel):
        """
        Request a private ticket with another user.
        """
        role = self.msg.guild.get_role(guild_config.role_id)

        gather = RequestGather(self.bot, self.msg, role)
        await gather.get_info()

        ticket = tickdb.schema.Ticket(user_id=self.msg.author.id, guild_id=self.msg.guild.id)
        self.session.add(ticket)

        await log_channel.send(
            LOG_TEMPLATE.format(action="Request", user=self.msg.author.name,
                                msg="Request issued, waiting for responder.")
        )
        await self.msg.channel.send(gather.format())

    async def take(self, _, log_channel):
        """
        Take a requested ticket.
        """
        guild = self.msg.guild
        user = self.msg.mentions[0]
        ticket = tickdb.query.get_ticket(self.session, user_id=user.id)
        ticket.supporter_id = self.msg.author.id

        overwrites = {
            guild.default_role: discord.PermissionOverwrite(read_messages=False),
            guild.me: discord.PermissionOverwrite(read_messages=True,
                                                  send_messages=True,
                                                  manage_messages=True,
                                                  manage_channels=True,
                                                  read_message_history=True),
            user: discord.PermissionOverwrite(read_messages=True,
                                              send_messages=True,
                                              read_message_history=True),
            self.msg.author: discord.PermissionOverwrite(read_messages=True,
                                                         send_messages=True,
                                                         read_message_history=True),
        }
        topic = "A private ticket for {}.".format(user.name)
        chan_name = tick.util.clean_input(NAME_TEMPLATE.format(
            id=ticket.id, user=user.name, taker=self.msg.author.name))
        chan = await guild.create_text_channel(name=chan_name, topic=topic,
                                               overwrites=overwrites,
                                               category=self.msg.channel.category)
        ticket.channel_id = chan.id
        self.session.add(ticket)

        await log_channel.send(
            LOG_TEMPLATE.format(action="Created", user=user.name,
                                msg="__Responder:__ {}\n__Channel:__ {} | {}".format(self.msg.author.name, chan.name, chan.mention)),
        )
        await chan.send(TICKET_WELCOME.format(prefix=self.bot.prefix))

    async def close(self, _, log_channel):
        """
        Close a ticket.
        """
        try:
            ticket = tickdb.query.get_ticket(self.session, channel_id=self.msg.channel.id)
            user = self.msg.guild.get_member(ticket.user_id)
        except (sqla_oexc.NoResultFound, sqla_oexc.MultipleResultsFound) as e:
            raise tick.exc.InvalidCommandArgs("I can only close within ticket channels.") from e

        reason = ' '.join(self.args.reason)
        resp, fname = '', ''
        try:
            await self.msg.channel.send("This will terminate the ticket. Do you want to confirm?\n\nYes/No")
            resp = await self.bot.wait_for(
                'message',
                check=lambda m: m.author == self.msg.author and m.channel == self.msg.channel,
                timeout=30
            )
            if not resp.content.strip().lower().startswith('y'):
                raise asyncio.TimeoutError

            await self.msg.channel.send("Closing ticket. Do you wish to get a log of this ticket DMed??\n\nYes/No")
            resp = await self.bot.wait_for(
                'message',
                check=lambda m: m.author == self.msg.author and m.channel == self.msg.channel,
                timeout=30
            )

            fname = await create_log(resp, self.msg.channel.name + ".txt")
            await log_channel.send(
                LOG_TEMPLATE.format(action="Close", user=user.name,
                                    msg="__Reason:__ {}.".format(reason)),
                files=[discord.File(fp=fname, filename=fname)]
            )
            if resp.content.strip().lower().startswith('y'):
                await user.send("The log of your support session. Take care.",
                                files=[discord.File(fp=fname, filename=fname)])
            await self.msg.channel.delete(reason=reason)
            self.session.delete(ticket)
        except asyncio.TimeoutError:
            await self.msg.channel.send("Cancelling request to close ticket.")
        except (sqla_oexc.NoResultFound, sqla_oexc.MultipleResultsFound):
            await self.msg.channel.send("A critical error found, database record could not be retrieved.")
        finally:
            try:
                os.remove(fname)
            except OSError:
                pass

    async def rename(self, _, log_channel):
        """
        Rename a ticket.
        """
        try:
            ticket = tickdb.query.get_ticket(self.session, channel_id=self.msg.channel.id)
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


async def create_log(last_msg, fname=None):
    """
    Log a whole channel's history to a file for preservation.

    Args:
        filename: The file to write to
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
