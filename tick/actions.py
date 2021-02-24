"""
To facilitate complex actions based on commands create a
hierarchy of actions that can be recombined in any order.
All actions have async execute methods.
"""
import asyncio
import logging
import os
import re
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

REQUEST_TIMEOUT = tick.util.get_config('ticket', 'request_timeout')
RESPONSE_TIMEOUT = tick.util.get_config('ticket', 'response_timeout')
PIN_EMOJI = tick.util.get_config('emojis', 'pin')
YES_EMOJI = tick.util.get_config('emojis', '_yes')
NO_EMOJI = tick.util.get_config('emojis', '_no')
U18_EMOJI = tick.util.get_config('emojis', 'u18')
ADMIN_ROLE = tick.util.get_config('ticket', 'admin_role')

QUESTIONS = (
    "Could you briefly describe the topic? If you wish it to remain private, type no.",
    "What type of support you would like? For example: sympathy, distraction, advice, personal venting, etc ...",
    "How long you would like to be supported for?",
)
NAME_TEMPLATE = "{id}-{user:.5}-{taker:.5}"

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
TICKET_PIN_MSG = """
To request a ticket react with {emoji} below.

A ticket is a private support session with a supporter who will try their best to help you.
You will be asked some questions to help narrow things down, respond as best you can.
Please be patient once a ping is made, response time varies depending on availability.
"""
PREAMBLE = """Hello. I understand you'd like support.
Please answer my questions one at a time and then we'll get you some help.
When answering my questions by text, type **Cancel** in response to terminate the request.

Do you need NSFW support? This would be for any adult topics or triggers as described in {chan} .
Please react below with {u18} for NSFW, {yes} for regular support or {no} to cancel this request.
"""
REQUEST_PING = """Requesting support for "**{user}**", please respond {role}.
{q_text}

React with {yes} to take this ticket.
Requesting user or "{admin_role}" may react with {no} to cancel request.

Note: If nobody responds, please reping roles at most every 10 minutes or cancel request.
"""
TICKET_WELCOME = """{mention}
This is a __private__ ticket. Please follow all server and support guidelines.
It is logged and the log will be made available to user if requested.
If there are any issues please ping staff.

To close the ticket: `{prefix}ticket close A reason goes here.`
To rename the ticket: `{prefix}ticket A new name for ticket`
    Names of tickets should be < 100 characters and stick to spaces, letters, numbers and '-'.
To get a new supporter (if they must go): `{prefix}ticket swap`
"""
PRACTICE_TICKET_WELCOME = """{mention}
This is a **PRACTICE** ticket. Practice responding to an issue.
At end please manually request a second responder to review and provide feedback.

This is a __private__ ticket. Please follow all server and support guidelines.
It is logged and the log will be made available to user if requested.
If there are any issues please ping staff.

To close the ticket: `{prefix}ticket close A reason goes here.`
To rename the ticket: `{prefix}ticket A new name for ticket`
    Names of tickets should be < 100 characters and stick to spaces, letters, numbers and '-'.
To get a new supporter (if they must go): `{prefix}ticket swap`
To start review of practice: `{prefix}ticket review`
"""
PRACTICE_REQUEST = """Requesting practice support for "**{user}**", please respond {role}.

The responder to this ticket will practice a support of the kind requested by the user.
At the end, initial user will have the session reviewed by a second responder for feedback.

React with {yes} to take this ticket.
Requesting user or "{admin_role}" may react with {no} to cancel request.

Note: If nobody responds, please reping roles at most every 10 minutes or cancel request.
"""
PRACTICE_REVIEW = """{mention} please react to this message to review a practice session.

You should have experience responding to tickets and free time to read session.
Please provide feedback directly to the requesting user.
"""
SUPPORT_PIN_NOTICE = """
Tickets can now be started by reacting to the above pin.
If it is ever deleted simply rerun this command.
I hope all goes well.
"""

# Permissions for various users involved
DISCORD_PERMS = {
    'bot': discord.PermissionOverwrite(read_messages=True,
                                       send_messages=True,
                                       manage_messages=True,
                                       manage_channels=True,
                                       manage_permissions=True,
                                       read_message_history=True,
                                       add_reactions=True),
    'none': discord.PermissionOverwrite(read_messages=False,
                                        send_messages=False,
                                        read_message_history=False,
                                        add_reactions=False),
    'user': discord.PermissionOverwrite(read_messages=True,
                                        send_messages=True,
                                        read_message_history=True,
                                        add_reactions=True),
    'overseer': discord.PermissionOverwrite(read_messages=True,
                                            send_messages=True,
                                            manage_messages=True,
                                            read_message_history=True),
    'log_required': discord.Permissions(read_messages=True,
                                        send_messages=True,
                                        attach_files=True),
    'support_required': discord.Permissions(read_messages=True,
                                            send_messages=True,
                                            manage_messages=True,
                                            add_reactions=True),
    'ticket_required': discord.Permissions(read_messages=True,
                                           manage_channels=True,
                                           add_reactions=True),
}
# *_required are used to validate existing perms needed by bot


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
        substr = ' '.join(self.args.name).lower()
        matches = [x for x in self.msg.guild.categories if substr in x.name.lower()]
        if not matches or len(matches) != 1:
            raise tick.exc.InvalidCommandArgs("Could not match exactly 1 category. Try again!")
        cat = matches[0]

        if not DISCORD_PERMS['ticket_required'].is_subset(cat.permissions_for(cat.guild.me)):
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
        if not DISCORD_PERMS['log_required'].is_subset(channel.permissions_for(channel.guild.me)):
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

        if not DISCORD_PERMS['support_required'].is_subset(channel.permissions_for(channel.guild.me)):
            perms = """
        Read Messages
        Send Messages
        Manage Messages
        Add Reactions"""
            raise tick.exc.InvalidPerms(PERMS_TEMPLATE.format("Support Channel", perms))

        sent = await channel.send(TICKET_PIN_MSG.format(emoji=PIN_EMOJI))
        await sent.pin()
        await sent.add_reaction(PIN_EMOJI)

        guild_config.support_channel_id = sent.channel.id
        guild_config.support_pin_id = sent.id

        await asyncio.sleep(2)
        to_delete = []
        async for msg in channel.history(limit=10):
            if msg.type == discord.MessageType.pins_add:
                to_delete += [msg]
        try:
            await channel.delete_messages(to_delete)
        except discord.NotFound:
            pass

        await self.bot.send_ttl_message(channel, SUPPORT_PIN_NOTICE, ttl=5)

    async def practice_support(self, guild_config):
        """
        Set the practice pinned message to react to for support practice sessions.

        Args:
            guild_config: The guild configuration to update.
        """
        channel = self.msg.channel_mentions[0]

        if not DISCORD_PERMS['support_required'].is_subset(channel.permissions_for(channel.guild.me)):
            perms = """
        Read Messages
        Send Messages
        Manage Messages
        Add Reactions"""
            raise tick.exc.InvalidPerms(PERMS_TEMPLATE.format("Support Channel", perms))

        sent = await channel.send(TICKET_PIN_MSG.format(emoji=PIN_EMOJI))
        await sent.pin()
        await sent.add_reaction(PIN_EMOJI)

        guild_config.practice_channel_id = sent.channel.id
        guild_config.practice_pin_id = sent.id

        await asyncio.sleep(2)
        to_delete = []
        async for msg in channel.history(limit=10):
            if msg.type == discord.MessageType.pins_add:
                to_delete += [msg]
        try:
            await channel.delete_messages(to_delete)
        except discord.NotFound:
            pass

        await self.bot.send_ttl_message(channel, SUPPORT_PIN_NOTICE, ttl=5)

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

    async def practice_role(self, guild_config):
        """
        Set the role to ping for practice tickets.

        Args:
            guild_config: The guild configuration to update.
        """
        role = self.msg.role_mentions[0]

        guild_config.practice_role_id = role.id
        self.session.add(guild_config)

        return "Setting practice tickets to ping:\n\n**%s**" % role.name

    async def overseer_roles(self, guild_config):
        """
        Set the role(s) that can oversee active tickets.

        Args:
            guild_config: The guild configuration to update.
        """
        role_ids = ",".join([str(x.id) for x in self.msg.role_mentions])
        if len(role_ids) > tickdb.schema.LEN_OVERSEER:
            raise tick.exc.InvalidCommandArgs("Choose less roles or see admin for more storage.")

        guild_config.oversee_role_ids = role_ids
        self.session.add(guild_config)

        role_names = "\n".join([str(x.name) for x in self.msg.role_mentions])
        return "Setting overseer roles to:\n\n**%s**" % role_names

    async def summary(self, guild_config):
        """
        Summarize the current settings for the bot.

        Args:
            guild_config: The guild configuration to update.
        """
        guild = self.msg.guild
        default = '**Not set**'

        overseer_roles = default
        if guild_config.overseer_role_ids:
            for r_id in guild_config.overseer_role_ids.split(','):
                overseer_roles += getattr(guild.get_role(int(r_id)), 'name', default) + "\n"

        kwargs = {
            'adult_role': getattr(guild.get_role(guild_config.adult_role_id), 'name', default),
            'regular_role': getattr(guild.get_role(guild_config.role_id), 'name', default),
            'logs': getattr(self.msg.guild.get_channel(guild_config.log_channel_id), 'mention', default),
            'support': getattr(self.msg.guild.get_channel(guild_config.support_channel_id), 'mention', default),
            'overseer_roles': overseer_roles,
            'category': getattr(self.msg.guild.get_channel(guild_config.category_channel_id), 'mention', default),
            'practice_role': getattr(guild.get_role(guild_config.practice_role_id), 'name', default),
            'practice': getattr(self.msg.guild.get_channel(guild_config.practice_channel_id), 'mention', default),
        }

        return """
__Live__
Ticket Category: {category}
Support Channel: {support}
Log Channel: {logs}
Adult Role: {adult_role}
Regular Role: {regular_role}
Overseer Role(s): {overseer_roles}

__Practice__
Practice Channel: {practice}
Practice Role: {practice_role}
        """.format(**kwargs)

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

        try:
            func = getattr(self, self.args.subcmd)
            resp = await func(guild_config)
            self.session.commit()
        except TypeError:
            resp = "Please see --help for command. Invalid selection."

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
            raise tick.exc.InvalidCommandArgs("I can only rename within ticket channels.") from e

        new_name = tick.util.clean_input(" ".join(self.args.name)).lower()[:100]
        new_name = re.sub(r'(p-)?({}-)?'.format(ticket.id), '', new_name)
        fmt = '{id}-{name}'
        if ticket.is_practice:
            fmt = 'p-' + fmt
        new_name = fmt.format(id=ticket.id, name=new_name)
        old_name = self.msg.channel.name
        await self.msg.channel.edit(reason='New name was requested.', name=new_name)
        await log_channel.send(
            LOG_TEMPLATE.format(action="Rename", user=self.msg.author.name,
                                msg="__Old Name:__ {}\n__New Name:__ {}".format(old_name, new_name)),
        )

        return 'Rename completed.'

    async def swap(self, guild_config, log_channel):
        """
        Swap the supporter for a ticket.
        """
        try:
            ticket = tickdb.query.get_ticket(self.session, self.msg.guild.id, channel_id=self.msg.channel.id)
        except (sqla_oexc.NoResultFound, sqla_oexc.MultipleResultsFound) as e:
            raise tick.exc.InvalidCommandArgs("I can only swap supporters in ticket channels.") from e
        guild = self.msg.guild
        roles = (guild.get_role(guild_config.adult_role_id), guild.get_role(guild_config.role_id))
        support_channel = guild.get_channel(guild_config.support_channel_id)
        user = self.bot.get_user(ticket.user_id)

        try:
            sent = await support_channel.send(ticket.request_msg)
            await sent.add_reaction(YES_EMOJI)
            await sent.add_reaction(NO_EMOJI)
            reaction, responder = await self.bot.wait_for(
                'reaction_add',
                check=request_check_roles(client=self.bot, sent=sent, user=user, roles=roles),
                timeout=RESPONSE_TIMEOUT
            )
            if str(reaction) == NO_EMOJI:
                raise asyncio.CancelledError
        except (asyncio.TimeoutError, asyncio.CancelledError):
            # Cannot continue with request, clean up
            return
        finally:
            try:
                await sent.delete()
            except discord.NotFound:
                pass

        old_responder = self.bot.get_user(ticket.supporter_id)
        overwrites = self.msg.channel.overwrites
        overwrites[old_responder] = DISCORD_PERMS['none']
        overwrites[responder] = DISCORD_PERMS['user']
        ticket.supporter_id = responder.id
        await self.msg.channel.edit(reason="New responder was requested.", overwrites=overwrites)

        await log_channel.send(
            LOG_TEMPLATE.format(action="Swap", user=self.msg.author.name,
                                msg="__Old Responder:__ {}\n__New Responder:__ {}".format(old_responder.name, responder.name)),
        )

        return 'Hope your new responder {} can help. Take care!'.format(responder.mention)

    async def review(self, guild_config, log_channel):
        """
        Review the events of a ticket by another responder.
        """
        try:
            ticket = tickdb.query.get_ticket(self.session, self.msg.guild.id, channel_id=self.msg.channel.id)
            if not ticket.is_practice:
                raise sqla_oexc.NoResultFound
        except (sqla_oexc.NoResultFound, sqla_oexc.MultipleResultsFound) as e:
            raise tick.exc.InvalidCommandArgs("I can only review in **practice** ticket channels.") from e

        guild = self.msg.guild
        roles = (guild.get_role(guild_config.practice_role_id),)
        support_channel = guild.get_channel(guild_config.practice_channel_id)
        user = self.bot.get_user(ticket.user_id)

        try:
            sent = await support_channel.send(PRACTICE_REVIEW.format(mention=roles[-1].mention))
            await sent.add_reaction(YES_EMOJI)
            await sent.add_reaction(NO_EMOJI)
            reaction, reviewer = await self.bot.wait_for(
                'reaction_add',
                check=request_check_roles(client=self.bot, sent=sent, user=user, roles=roles),
                timeout=RESPONSE_TIMEOUT
            )
            if str(reaction) == NO_EMOJI:
                raise asyncio.CancelledError
        except (asyncio.TimeoutError, asyncio.CancelledError):
            # Cannot continue with request, clean up
            return
        finally:
            try:
                await sent.delete()
            except discord.NotFound:
                pass

        overwrites = self.msg.channel.overwrites
        overwrites[reviewer] = DISCORD_PERMS['user']
        await self.msg.channel.edit(reason="Reviewer added to ticket.", overwrites=overwrites)

        await log_channel.send(
            LOG_TEMPLATE.format(action="Reivew", user=self.msg.author.name,
                                msg="__New Reviewer:__ {}".format(reviewer.name))
        )

        return """Hello reviewer {}!. Above is a practice ticket session.
Please read it over and provide feedback to requester who initiated the practice.

Thank you very much.""".format(reviewer.mention)

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

        try:
            func = getattr(self, self.args.subcmd)
            resp = await func(guild_config, log_channel)
            self.session.commit()
        except TypeError:
            resp = "Please see --help for command. Invalid selection."

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
        self.sent = []
        self.adult_needed = False

    def __repr__(self):
        keys = ['chan', 'author', 'questions', 'responses']
        kwargs = ['{}={!r}'.format(key, getattr(self, key)) for key in keys]

        return "{}({})".format(self.__class__.__name__, ', '.join(kwargs))

    async def needs_adult(self):
        """
        Check if adult needed.

        Returns:
            adult_needed: A boolean. If None then user opted to cancel request.

        Raises:
            asyncio.CancelledError - User opted to cancel the request early.
            asyncio.TimeoutError - Timeout from user to respond to prompt.
        """
        server_rules = discord.utils.get(self.chan.guild.channels, name='server-rules')
        text = PREAMBLE.format(chan=server_rules.mention, yes=YES_EMOJI, no=NO_EMOJI, u18=U18_EMOJI)

        msg = await self.chan.send(text)
        await msg.add_reaction(U18_EMOJI)
        await msg.add_reaction(YES_EMOJI)
        await msg.add_reaction(NO_EMOJI)
        self.sent += [msg]

        def check(c_react, c_user):
            return c_user == self.author and str(c_react) in (YES_EMOJI, NO_EMOJI, U18_EMOJI)

        react, _ = await self.bot.wait_for('reaction_add', check=check, timeout=RESPONSE_TIMEOUT)
        self.adult_needed = str(react) == U18_EMOJI
        if str(react) == NO_EMOJI:
            raise asyncio.CancelledError("User used no emoji.")

        return self.adult_needed

    async def ask_questions(self):
        """
        Allow the user to answer questions and keep the responses.

        Returns: True iff user needs an adult. Default False.

        Raises:
            InvalidCommandArgs: User opted to cancel before finishing.
        """
        try:
            adult_needed = await self.needs_adult()

            for ind, question in enumerate(self.questions, start=1):
                self.sent += [await self.chan.send("{}) {}".format(ind, question))]
                resp = await self.bot.wait_for(
                    'message',
                    check=lambda m: m.author == self.author and m.channel == self.chan,
                    timeout=RESPONSE_TIMEOUT,
                )
                self.sent += [resp]
                self.responses += [resp.content]
                if resp.content == "Cancel":
                    raise asyncio.CancelledError
        except asyncio.CancelledError as e:
            raise tick.exc.InvalidCommandArgs("Request cancelled by user.") from e
        except asyncio.TimeoutError as e:
            raise tick.exc.InvalidCommandArgs("User didn't respond to questions in time. Cancelling request.") from e
        finally:
            if self.sent:
                try:
                    await self.chan.delete_messages(self.sent)
                except discord.NotFound:
                    pass

        return adult_needed

    def format(self, roles):
        """
        Returns a formatted message to summarize request.

        Args:
            roles: The roles to mention in the message.
        """
        role_msg = " ".join([x.mention for x in roles])
        q_text = ''
        for ind, (question, response) in enumerate(zip(self.questions, self.responses), start=1):
            q_text += "\n**{}) {}**\n    {}".format(ind, question, response)

        return REQUEST_PING.format(user=self.author.name, role=role_msg,
                                   prefix=self.bot.prefix, q_text=q_text,
                                   admin_role=ADMIN_ROLE, yes=YES_EMOJI, no=NO_EMOJI)


def request_check_roles(*, client, sent, user, roles):
    """
    Generate a check function for a response to a request for help by a user.
    Use this function to check on a reaction to a message.

    Kwargs:
        client: A reference to the client.
        sent: The request message sent to user.
        user: The user sending the request.
        roles: Roles that are allowed to respond.

    Returns:
        A function that takes a (reaction, user) and performs the boolean check.kj:w
    """
    def request_check(c_react, c_user):
        """
        A ticket can be cancelled by original user or ADMIN_ROLE.
        A ticket can only be taken by one of the selected roles.
        """
        if c_user == client.user or c_react.message.id != sent.id:
            return False

        can_respond, can_cancel = False, c_user == user
        for role in c_user.roles:
            if role in roles and c_user != user:
                can_respond = True
            if role.name == ADMIN_ROLE:
                can_cancel = True

        response = ((can_respond and str(c_react) == YES_EMOJI)
                    or (can_cancel and str(c_react) == NO_EMOJI))
        if not response:
            asyncio.ensure_future(c_react.remove(c_user))

        return response

    return request_check


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
    await gather.ask_questions()
    roles = [guild.get_role(config.role_id)]
    if gather.adult_needed and config.adult_role_id:
        roles = [guild.get_role(config.adult_role_id)]

    log_channel = guild.get_channel(config.log_channel_id)
    if log_channel:
        await log_channel.send(
            LOG_TEMPLATE.format(action="Request", user=user.name,
                                msg="Request issued, waiting for responder.")
        )

    sent = await chan.send(gather.format(roles))
    await sent.add_reaction(YES_EMOJI)
    await sent.add_reaction(NO_EMOJI)
    try:
        reaction, responder = await client.wait_for(
            'reaction_add',
            check=request_check_roles(client=client, sent=sent, user=user, roles=roles),
            timeout=REQUEST_TIMEOUT,
        )
        if str(reaction) == NO_EMOJI:
            raise asyncio.CancelledError
    except asyncio.CancelledError:
        msg = """User cancelled the ticket.
Request will be closed soon.

{} please consider making a new one if you still need help.""".format(user.mention)
        await client.send_ttl_message(chan, msg)
        return
    except asyncio.TimeoutError:
        msg = """It took longer than {} hour(s) to get a responder.
Request will be closed soon.

{} please consider making a new one if you still need help.""".format(round(REQUEST_TIMEOUT / 3600.0, 2), user.mention)
        await client.send_ttl_message(chan, msg)
        return
    finally:
        try:
            await sent.delete()
        except discord.NotFound:
            pass

    ticket = tickdb.schema.Ticket(user_id=user.id, supporter_id=responder.id,
                                  guild_id=guild.id, request_msg=gather.format(roles))
    session = tickdb.Session()
    session.add(ticket)
    session.flush()

    overwrites = {
        guild.default_role: DISCORD_PERMS['none'],
        guild.me: DISCORD_PERMS['bot'],
        user: DISCORD_PERMS['user'],
        responder: DISCORD_PERMS['user'],
    }
    if config.overseer_role_ids:
        for r_id in config.overseer_role_ids.split(','):
            role = guild.get_role(int(r_id))
            overwrites[role] = DISCORD_PERMS['overseer']

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
    msg = await ticket_channel.send(TICKET_WELCOME.format(
        prefix=client.prefix, mention=" ".join((user.mention, responder.mention))))
    await msg.pin()


async def practice_ticket_request(client, chan, user, config):
    """
    Request a practice only ticket, otherwise identical to normal ticket.

    Args:
        client: An instance of the bot.
        user: The original requesting user.
        chan: The original requesting channel.
        config: A configuration for the guild.
    """
    guild = chan.guild

    role = guild.get_role(config.practice_role_id)
    log_channel = guild.get_channel(config.log_channel_id)
    if log_channel:
        await log_channel.send(
            LOG_TEMPLATE.format(action="Practice Request", user=user.name,
                                msg="Request issued, waiting for responder.")
        )

    msg = PRACTICE_REQUEST.format(user=user.name, role=role.mention,
                                  admin_role=ADMIN_ROLE, yes=YES_EMOJI, no=NO_EMOJI)
    sent = await chan.send(msg)
    await sent.add_reaction(YES_EMOJI)
    await sent.add_reaction(NO_EMOJI)
    try:
        reaction, responder = await client.wait_for(
            'reaction_add',
            check=request_check_roles(client=client, sent=sent, user=user, roles=[role]),
        )
        if str(reaction) == NO_EMOJI:
            raise asyncio.CancelledError
    except asyncio.CancelledError:
        msg = """User cancelled the practice ticket.
Request will be closed soon.

{} please consider making a new one if you still need help.""".format(user.mention)
        await client.send_ttl_message(chan, msg)
        return
    finally:
        try:
            await sent.delete()
        except discord.NotFound:
            pass

    ticket = tickdb.schema.Ticket(user_id=user.id, supporter_id=responder.id,
                                  guild_id=guild.id, request_msg=msg, is_practice=True)
    session = tickdb.Session()
    session.add(ticket)
    session.flush()

    overwrites = {
        guild.default_role: DISCORD_PERMS['none'],
        guild.me: DISCORD_PERMS['bot'],
        user: DISCORD_PERMS['user'],
        responder: DISCORD_PERMS['user'],
    }
    if config.overseer_role_ids:
        for r_id in config.overseer_role_ids.split(','):
            role = guild.get_role(int(r_id))
            overwrites[role] = DISCORD_PERMS['overseer']

    ticket_name = tick.util.clean_input("P_" + NAME_TEMPLATE.format(
        id=ticket.id, user=user.name, taker=responder.name))
    ticket_category = [x for x in guild.categories if x.id == config.category_channel_id][0]
    ticket_channel = await guild.create_text_channel(name=ticket_name,
                                                     topic="A private practice ticket for {}.".format(user.name),
                                                     overwrites=overwrites,
                                                     category=ticket_category)
    ticket.channel_id = ticket_channel.id
    session.commit()

    if log_channel:
        await log_channel.send(
            LOG_TEMPLATE.format(action="Practice Created", user=user.name,
                                msg="__Responder:__ {}\n__Channel:__ {} | {}".format(responder.name, chan.name, chan.mention)),
        )
    msg = await ticket_channel.send(PRACTICE_TICKET_WELCOME.format(
        prefix=client.prefix, mention=" ".join((user.mention, responder.mention))))
    await msg.pin()


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

        # Log entire channel no matter how long.
        async for msg in last_msg.channel.history(limit=None, oldest_first=True):
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

    Raises:
        TimeoutError - User didn't react within the timeout.
    """
    msg = await chan.send(text)
    await msg.add_reaction(yes)
    await msg.add_reaction(no)

    def check(react, user):
        return user == author and str(react) in (yes, no)

    react, _ = await client.wait_for('reaction_add', check=check, timeout=RESPONSE_TIMEOUT)

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
