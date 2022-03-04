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
import traceback

import aiofiles
import aiomock
import discord
import sqlalchemy
import sqlalchemy.orm.exc as sqla_oexc

import tick.exc
import tick.tbl
import tick.util
import tickdb
import tickdb.query
import tickdb.schema

REQUEST_TIMEOUT = tick.util.get_config('ticket', 'request_timeout')
RESPONSE_TIMEOUT = tick.util.get_config('ticket', 'response_timeout')
ADMIN_ROLE = tick.util.get_config('ticket', 'admin_role')
EMOJIS = tick.util.get_config('emojis')

MAX_QUESTION_LEN = 500  # characters
QUESTIONS_CANCEL = "cancel"
QUESTION_LENGTH_TOO_MUCH = """The response to the question was too long.
Please answer again with a message < {} characters long.

To cancel any time, just reply with: **{}**""".format(MAX_QUESTION_LEN, QUESTIONS_CANCEL)
NAME_TEMPLATE = "{id}-{user:.5}-{taker:.5}"

PERMS_TEMPLATE = """This bot requires following perms for requested channel:
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
To rename the ticket: `{prefix}ticket rename A new name for ticket`
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
TICKET_CLOSE_PERMS = """
Cannot DM the log of this ticket to the user who requested ticket.
{} please enable DMs or do not request DMed logs during close.

Aborting this attempt to close ticket.
"""
SWAP_NOTICE = """
Thank you {supporter} for taking the time and effort to support {user}.
A request for a new supporter has been sent to {channel}, another supporter will be with you ASAP!
If another supporter is not with you within 10 minutes, you're welcome to manually ping the mentioned role once every 10 minutes!
"""
GUILD_SUMMARY = """
__{guild}__

Ticket Category: {category}
Log Channel: {log_channel}
Ticket Channel: {tickets_channel}
Pinned Message: {message}

__Ticket Flows__
"""
TICKET_CONFIG_SUMMARY = """
Name: {name}
Prefix: {prefix}
Emoji: {emoji}
Timeout: {timeout}
Responding Roles: {roles}
"""
MSG_OR_STOP = "{}\n\nType 'stop' to cancel or stop here."
STOP_MSG = "stop"
TICKET_UNCLAIMED = """This ticket is now unclaimed.
Please read the questions and answers, to the first question: {jump_url}
To claim it, please click the reaction.

{mentions}"""
TICKET_REVIEW = """This ticket is seeking review.
Please read the questions and answers to get an idea for contents, to the first question: {jump_url}
To claim the review, please click the reaction.

{mentions}"""
TICKET_QUESTIONS_MENU = """These are the currently configured messages associated with ticket.
The following options are possible:

To view or edit an existing question: React to this message.
    {.regional']['w} is for the welcome introduction
    1, 2, ... etc are the questions that follow
To add a question, simply type the text you want to add as a question.
To go back to main push {.yes}.
To exit this menu, use {.no}'.
"""
TICKET_QUESTION_MANAGEMENT = """Displaying question #{q_num}.

> {q_text}

To remove: {e_remove}
To edit: {e_edit}.
To go to next: {e_next}"""
TICKET_DIRECTIONS = """
Hello, this is a private ticket. It operates as follows:

    You, staff and responders for this type of ticket can see the contents. The contents are NOT public.
    When you finish answering questions a ping will be made to responders.
    Responders will read the answers and one will claim it.
    When a responder claims the ticket, only you, the responder and staff can see ticket.
    Access to other responders will be removed until you **unclaim** it or request **review**.

To close ticket: {prefix}ticket close
To get a new supporter: {prefix}ticket unclaim
To get a reviewer: {prefix}ticket review
"""
KEY_CAP = '\N{COMBINING ENCLOSING KEYCAP}'  # Usage: str(1) + NUM_KEY => keycap 1


# Permissions for various users involved
DISCORD_PERMS = {
    'bot': discord.PermissionOverwrite(read_messages=True,
                                       send_messages=True,
                                       manage_messages=True,
                                       manage_channels=True,
                                       manage_permissions=True,
                                       read_message_history=True,
                                       add_reactions=True),
    'none': discord.PermissionOverwrite(read_messages=None,
                                        send_messages=None,
                                        read_message_history=None,
                                        add_reactions=None),
    'nothing': discord.PermissionOverwrite(read_messages=False,
                                           send_messages=False,
                                           read_message_history=False,
                                           add_reactions=False),
    'user': discord.PermissionOverwrite(read_messages=True,
                                        send_messages=True,
                                        read_message_history=True,
                                        add_reactions=True),
    'category_required': discord.Permissions(read_messages=True,
                                             manage_channels=True,
                                             add_reactions=True),
    'log_required': discord.Permissions(read_messages=True,
                                        send_messages=True,
                                        attach_files=True),
    'support_required': discord.Permissions(read_messages=True,
                                            send_messages=True,
                                            manage_messages=True,
                                            add_reactions=True),
    # *_required are used to validate existing perms needed by bot
}
PERM_ATTRIBUTES = (
    'add_reactions',
    'attach_files',
    'manage_channels',
    'manage_messages',
    'manage_permissions',
    'read_messages',
    'read_message_history',
    'send_messages',
)


def perms_to_msg(perms):
    """
    Simple converter from discord.Permissions object to a string with the names of the perms required.
    """
    pad = " " * 4
    msg = ""

    for attr in PERM_ATTRIBUTES:
        if getattr(perms, attr):
            name = attr.replace('_', ' ').title()
            msg += f"{pad}{name}\n"

    return msg


def check_chan_perms(channel, perms_key):
    """Run a check on the channel for required permissions.

    This is to be used when setting channels for tickets.
    A failure of permissions will trigger an exception

    Args:
        channel: The discord.TextChannel in question.
        perms_key: The key entry in DISCORD_PERMS.

    Raises:
        tick.exc.InvalidPerms: Raised when perms are invalid for the channel requested.
    """
    perms = DISCORD_PERMS[perms_key]
    if not perms.is_subset(channel.permissions_for(channel.guild.me)):
        raise tick.exc.InvalidPerms(PERMS_TEMPLATE.format(perms_to_msg(perms)))


class Action():
    """
    Top level action, contains shared logic.
    """
    def __init__(self, **kwargs):
        self.args = kwargs['args']
        self.bot = kwargs['bot']
        self.msg = kwargs['msg']
        self.session = kwargs['session']
        self.log = logging.getLogger(__name__)

    async def execute(self):
        """
        Take steps to accomplish requested action, including possibly
        invoking and scheduling other actions.
        """
        raise NotImplementedError


class StopChanges(Exception):
    """ Stop interactive changes. """
    pass


def create_msg_checker(first_msg):
    """
    Create a standard message checker for wait_for("message") events.
    Checks that channel and author are identical.
    """
    def check(msg):
        """ Wait for response in this channel and from the instigating author. """
        return msg.channel == first_msg.channel and msg.author == first_msg.author

    return check


def create_raw_reaction_checker(first_msg):
    """
    Create a standard message checker for wait_for("raw_reaction_add") events.
    Checks that channel and author are identical.
    """
    def check(event):
        """
        Notable: e.emoji, e.member, e.message_id, e.channel_id
        https://discordpy.readthedocs.io/en/stable/api.html#discord.RawReactionActionEvent
        """
        return event.channel_id == first_msg.channel.id and event.member == first_msg.author

    return check


class Admin(Action):
    """
    Provide high level configuration of the ticket bot.
    """
    async def pin(self, guild_config):
        """
        Create or update the pin that tickets will use.
        """
        pin_intro = """Please write a new message explaining the tickets you will setup.
Tickets will be started by reacting to this pinned message.
You can always edit this pin message later without breaking the bot."""
        await self.msg.channel.send(MSG_OR_STOP.format(pin_intro))

        resp = await self.bot.wait_for('message', check=create_msg_checker(self.msg))
        if resp.content and resp.content == STOP_MSG:
            return "Aborting new pinned message."
        else:
            # If a pin exists in config, unpin and delete it.
            if guild_config.pinned_message_id:
                try:
                    ticket_chan = self.msg.guild.get_channel(guild_config.ticket_channel_id)
                    pinned = await ticket_chan.fetch_message(guild_config.pinned_message_id)
                    await pinned.unpin()
                    await pinned.delete()
                except discord.errors.NotFound:
                    pass
                except discord.errors.Forbidden:
                    pass

            await resp.pin()
            for ticket_config in guild_config.ticket_configs:
                emoji = await self.msg.guild.fetch_emoji(ticket_config.emoji_id)
                await resp.add_reaction(emoji)
            guild_config.pinned_message_id = resp.id

            return f"Pinning your message. Add ticket flows with: **{self.bot.prefix}admin ticket_setup** name_of_tickets"

    async def guild_setup(self, guild_config):
        """
        Configure the guild_config interactively.
        """
        chan = self.msg.channel
        client = self.bot
        resp_channel = None
        check = create_msg_checker(self.msg)

        while True:
            await chan.send(MSG_OR_STOP.format("Please mention the channel to send logs to."))
            resp = await client.wait_for('message', check=check)
            if resp and resp.content == STOP_MSG:
                return
            elif resp and len(resp.channel_mentions) == 1:
                resp_channel = resp.channel_mentions[0]
                check_chan_perms(resp_channel, 'log_required')
                guild_config.log_channel_id = resp_channel.id
                await chan.send("Setting log channel to: {}".format(resp_channel.mention))
                break

        while True:
            await chan.send(MSG_OR_STOP.format("Please mention the channel to start tickets in."))
            resp = await client.wait_for('message', check=check)
            if resp and resp.content == STOP_MSG:
                return
            elif resp and len(resp.channel_mentions) == 1:
                resp_channel = resp.channel_mentions[0]
                check_chan_perms(resp_channel, 'support_required')
                guild_config.ticket_channel_id = resp_channel.id
                await chan.send("Setting tickets channel to: {}".format(resp_channel.mention))
                break

        while True:
            await chan.send(MSG_OR_STOP.format("Please type the **exact** name of the category for tickets."))
            resp = await client.wait_for('message', check=check)
            if resp and resp.content == STOP_MSG:
                return
            elif resp:
                found = [x for x in self.msg.guild.categories if x.name.lower() == resp.content.lower()]
                if not found:
                    await chan.send("Failed to match category name, please try again.")
                else:
                    resp_channel = found[0]
                    check_chan_perms(resp_channel, 'category_required')
                    guild_config.category_channel_id = resp_channel.id
                    await chan.send("Setting tickets category to: {}".format(resp_channel.name))
                    break

        return f"Configuration completed! Create the main ticket pin with: **{client.prefix}admin pin**"

    async def ticket_setup(self, guild_config):
        """
        Configure a ticket flow.
        """
        chan = self.msg.channel
        client = self.bot
        resp = None
        event = None  # Reaction event
        ticket_config = tickdb.query.get_or_add_ticket_config(self.session, self.msg.guild.id, self.args.name)
        print(ticket_config)
        self.session.flush()

        def check_reaction(event):
            """
            Notable: e.emoji, e.member, e.message_id, e.channel_id
            https://discordpy.readthedocs.io/en/stable/api.html#discord.RawReactionActionEvent
            """
            return (event.channel_id == self.msg.channel.id
                    and event.member == self.msg.author
                    and event.emoji
                    and event.emoji.id)

        check_msg = create_msg_checker(self.msg)
        setup_intro = """Creating or updating a ticket flow called: {}.

Please type a unique prefix of lenth < {} for ticket channels.""".format(ticket_config.name, tickdb.schema.LEN_TICKET_PREFIX)
        while True:
            await chan.send(MSG_OR_STOP.format(setup_intro))
            resp = await client.wait_for('message', check=check_msg)
            if resp and resp.content == STOP_MSG:
                return
            elif resp and len(resp.content) <= tickdb.schema.LEN_TICKET_PREFIX:
                ticket_config.prefix = resp.content
                try:
                    self.session.flush()
                except sqlalchemy.exc.IntegrityError:
                    self.session.rollback()
                    continue
                await chan.send("Setting prefix for ticket channels to: {}".format(resp.content))
                break

        while True:
            await chan.send("Please react with a custom server emoji used to start tickets.")
            event = await client.wait_for('raw_reaction_add', check=check_reaction)
            ticket_config.emoji_id = event.emoji.id
            try:
                self.session.flush()
                await chan.send("Setting emoji to start tickets: {}".format(event.emoji))
                break
            except sqlalchemy.exc.IntegrityError:
                self.session.rollback()
                continue

        while True:
            await chan.send(MSG_OR_STOP.format("How long before tickets should timeout?\n\nAnswer in number of hours. 0 is no timeout."))
            resp = await client.wait_for('message', check=check_msg)
            if resp and resp.content == STOP_MSG:
                return
            try:
                ticket_config.timeout = int(float(resp.content) * 3600)
                await chan.send("Setting {} tickets to timeout in: {} hours".format(ticket_config.name, resp.content))
                break
            except ValueError:
                pass

        while True:
            await chan.send(MSG_OR_STOP.format("Mention ALL the roles you want to respond to these tickets."))
            resp = await client.wait_for('message', check=check_msg)
            if resp and resp.content == STOP_MSG:
                break
            elif resp and len(resp.role_mentions) > 0:
                tickdb.query.remove_roles_for_ticket(self.session, ticket_config)
                self.session.commit()
                role_text = ""
                for r_mention in resp.role_mentions:
                    role = tickdb.schema.TicketConfigRole(
                        ticket_config_id=ticket_config.id,
                        role_id=r_mention.id,
                        role_text=r_mention.name
                    )
                    self.session.add(role)
                    role_text += "\n {}".format(r_mention.name)

                await chan.send("Setting roles to the following:\n{}".format(role_text))
                break

        ticket_chan = self.msg.guild.get_channel(guild_config.ticket_channel_id)
        pinned = await ticket_chan.fetch_message(guild_config.pinned_message_id)
        await pinned.add_reaction(event.emoji)

        return f"Ticket flow completed. Reaction added to pin. To setup questions: **{self.bot.prefix}admin questions {ticket_config.name}**"

    async def ticket_remove(self, guild_config):
        """
        Remove a configured ticket from flow.
        """
        ticket_config = tickdb.query.get_or_add_ticket_config(self.session, self.msg.guild.id, self.args.name)
        if not ticket_config.prefix or not ticket_config.emoji_id or not ticket_config.name:
            self.session.rollback()
            return "This ticket flow isn't fully configured. Please complete that first."

        if ticket_config.tickets:
            await self.msg.channel.send("Warning! There are active tickets for this flow. It is best to remove when they are done.")
        resp, msg = await wait_for_user_reaction(
            self.bot, self.msg.channel, self.msg.author,
            f"Please confirm that you want to remove ticket flow: {ticket_config.name}. This will only remove configuration and pin.")
        if not resp:
            raise asyncio.TimeoutError

        # If a pin exists remove the emoji
        if guild_config.pinned_message_id:
            try:
                ticket_chan = self.msg.guild.get_channel(guild_config.ticket_channel_id)
                pinned = await ticket_chan.fetch_message(guild_config.pinned_message_id)
                emoji = await self.msg.guild.fetch_emoji(ticket_config.emoji_id)
                await pinned.remove_reaction(emoji, self.bot.user)
            except discord.errors.NotFound:
                pass
            except discord.errors.Forbidden:
                pass

        self.session.delete(ticket_config)

        return f"Ticket flow for \"{ticket_config.name}\" removed."

    async def questions(self, _):
        """
        View, edit and add ticket questions.
        """
        chan = self.msg.channel
        client = self.bot

        ticket_config = tickdb.query.get_or_add_ticket_config(self.session, self.msg.guild.id, self.args.name)
        if not ticket_config.prefix or not ticket_config.emoji_id or not ticket_config.name:
            self.session.rollback()
            return "This ticket flow isn't fully configured. Please complete that first."

        check_msg = create_msg_checker(self.msg)
        check_reaction = create_raw_reaction_checker(self.msg)
        q_num = 1

        for question in ticket_config.questions:
            resp = await chan.send(TICKET_QUESTION_MANAGEMENT.format(
                q_text=question.text, q_num=q_num,
                e_remove=EMOJIS['_no'],
                e_edit=EMOJIS['regional']['e'],
                e_next=EMOJIS['regional']['n'],
            ))
            q_num += 1
            for emoji in (EMOJIS['_no'], EMOJIS['regional']['e'], EMOJIS['regional']['n']):
                await resp.add_reaction(emoji)
            resp = await client.wait_for('raw_reaction_add', check=check_reaction)
            if str(resp.emoji) == EMOJIS['_no']:
                self.session.delete(question)
            elif str(resp.emoji) == EMOJIS['regional']['e']:
                await chan.send(MSG_OR_STOP.format("Write a new question to replace this one now."))
                resp = await client.wait_for('message', check=check_msg)
                question.text = resp.content

        self.session.commit()  # Deletions reflect before adding
        while True:
            await chan.send(MSG_OR_STOP.format("To add questions, simply type them here and they will be appended in order."))
            resp = await client.wait_for('message', check=check_msg)
            if resp and resp.content == STOP_MSG:
                break
            else:
                tickdb.query.add_ticket_question(self.session, ticket_config, resp.content)

        self.session.refresh(ticket_config)
        for ind, question in enumerate(ticket_config.questions, start=1):
            question.num = ind

        return f"Management of questions for tickets of: {ticket_config.name}"

    async def summary(self, guild_config):
        """
        Summarize the current settings for the bot.

        Args:
            guild_config: The guild configuration to update.
        """
        guild = self.msg.guild
        default = tick.util.NOT_SET
        message = default

        ticket_channel = guild.get_channel(guild_config.ticket_channel_id)
        if ticket_channel and guild_config.pinned_message_id:
            try:
                message_obj = await ticket_channel.fetch_message(guild_config.pinned_message_id)
                message = getattr(message_obj, 'jump_url', default)
            except discord.errors.NotFound:
                pass

        kwargs = {
            'guild': guild.name,
            'category': getattr(guild.get_channel(guild_config.category_channel_id), 'name', default),
            'log_channel': getattr(guild.get_channel(guild_config.log_channel_id), 'mention', default),
            'tickets_channel': getattr(guild.get_channel(guild_config.ticket_channel_id), 'mention', default),
            'message': message
        }
        summary = GUILD_SUMMARY.format(**kwargs)

        for ticket_config in guild_config.ticket_configs:
            t_kwargs = ticket_config.kwargs()
            if t_kwargs['emoji_id']:
                try:
                    t_kwargs['emoji'] = await guild.fetch_emoji(t_kwargs['emoji_id'])
                except discord.errors.NotFound:
                    pass
            summary += TICKET_CONFIG_SUMMARY.format(**t_kwargs)

        return summary

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

        resp = None
        try:
            func = getattr(self, self.args.subcmd)
            resp = await func(guild_config)
            self.session.commit()
        except TypeError:
            print(traceback.format_exc())
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
        except (sqla_oexc.NoResultFound, sqla_oexc.MultipleResultsFound) as e:
            raise tick.exc.InvalidCommandArgs("I can only close within ticket channels.") from e

        chan = self.bot.get_channel(ticket.channel_id)
        # Channel topic is format: A private ticket for username
        user_name = chan.topic.split(" ")[-1]

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
                LOG_TEMPLATE.format(action="Close", user=user_name,
                                    msg="__Reason:__ {}".format(reason)),
                files=[discord.File(fp=fname, filename=os.path.basename(fname))]
            )

            resp, _ = await wait_for_user_reaction(
                self.bot, self.msg.channel, self.msg.author,
                "Closing ticket. Do you want a log of this ticket DMed?")
            if resp:
                try:
                    user = self.msg.guild.get_member(ticket.user_id)
                    if user:
                        await user.send("The log of your support session. Take care.",
                                        files=[discord.File(fp=fname, filename=os.path.basename(fname))])
                except discord.Forbidden:
                    await self.msg.channel.send(TICKET_CLOSE_PERMS.format(self.msg.author.mention))
                    return

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

    async def unclaim(self, ticket, log_channel):
        """Unclaim a ticket from initial responder. Begins a swap process.

        Args:
            ticket: The Ticket database object.
            log_channel: The actual log TextChannel to send messages to.

        Raises:
            tick.exc.InvalidCommandArgs: Something gone critically wrong.
        """

        try:
            ticket = tickdb.query.get_ticket(self.session, self.msg.guild.id, channel_id=self.msg.channel.id)
        except (sqla_oexc.NoResultFound, sqla_oexc.MultipleResultsFound) as e:
            raise tick.exc.InvalidCommandArgs("I can only swap supporters in ticket channels.") from e

        chan = self.msg.channel
        mentions = " ".join([chan.guild.get_role(x.role_id).mention for x in ticket.ticket_config.roles])
        user = chan.guild.get_member(ticket.user_id)
        old_responder = chan.guild.get_member(ticket.responder_id)

        jump_url = "No jump set."
        for msg in (await chan.pins()):
            if "private ticket" in msg.content:
                continue
            jump_url = msg.jump_url

        def check_reaction(event):
            """
            Notable: e.emoji, e.member, e.message_id, e.channel_id
            https://discordpy.readthedocs.io/en/stable/api.html#discord.RawReactionActionEvent
            """
            return (event.channel_id == chan.id
                    and event.member != user
                    and event.member != self.bot.user
                    and str(event.emoji) == EMOJIS['_yes'])

        self.log.info("Ticket is unclaimed: %s", chan.name)

        # Revert to unclaimed status
        to_update = {chan.guild.get_role(x.role_id): DISCORD_PERMS['user'] for x in ticket.ticket_config.roles}
        to_update[old_responder] = DISCORD_PERMS['none']
        chan.overwrites.update(to_update)
        await chan.edit(reason="Set ticket to unclaimed.", overwrites=chan.overwrites)

        msg = await chan.send(TICKET_UNCLAIMED.format(jump_url=jump_url, mentions=mentions))
        await msg.add_reaction(EMOJIS['_yes'])
        resp = await self.bot.wait_for('raw_reaction_add', check=check_reaction)
        responder = resp.member
        ticket.responder_id = responder.id

        # New responder found, return perms
        to_update = {chan.guild.get_role(x.role_id): DISCORD_PERMS['nothing'] for x in ticket.ticket_config.roles}
        to_update[responder] = DISCORD_PERMS['user']
        chan.overwrites.update(to_update)
        await chan.edit(reason="Set ticket to claimed.", overwrites=chan.overwrites)

        self.log.info("Ticket is claimed: %s", chan.name)

        await log_channel.send(
            LOG_TEMPLATE.format(action="Swap", user=self.msg.author.name,
                                msg="__Old Responder:__ {}\n__New Responder:__ {}".format(old_responder.name, responder.name)),
        )

        return 'Hope your new responder {} can help. Take care!'.format(responder.mention)

    async def review(self, ticket, log_channel):
        """
        Review the events of a ticket by another responder.
        """
        try:
            ticket = tickdb.query.get_ticket(self.session, self.msg.guild.id, channel_id=self.msg.channel.id)
        except (sqla_oexc.NoResultFound, sqla_oexc.MultipleResultsFound) as e:
            raise tick.exc.InvalidCommandArgs("I can only review inside ticket channels.") from e

        chan = self.msg.channel
        mentions = " ".join([chan.guild.get_role(x.role_id).mention for x in ticket.ticket_config.roles])
        user = chan.guild.get_member(ticket.user_id)
        old_responder = chan.guild.get_member(ticket.responder_id)

        jump_url = "No jump set."
        for msg in (await chan.pins()):
            if "private ticket" in msg.content:
                continue
            jump_url = msg.jump_url

        def check_reaction(event):
            """
            Notable: e.emoji, e.member, e.message_id, e.channel_id
            https://discordpy.readthedocs.io/en/stable/api.html#discord.RawReactionActionEvent
            """
            return (event.channel_id == chan.id
                    and event.member != user
                    and event.member != old_responder
                    and event.member != self.bot.user
                    and str(event.emoji) == EMOJIS['_yes'])

        self.log.info("Ticket review is unclaimed: %s", chan.name)

        # Open to reviewers
        to_update = {chan.guild.get_role(x.role_id): DISCORD_PERMS['user'] for x in ticket.ticket_config.roles}
        chan.overwrites.update(to_update)
        await chan.edit(reason="Set ticket review unclaimed.", overwrites=chan.overwrites)

        msg = await chan.send(TICKET_REVIEW.format(jump_url=jump_url, mentions=mentions))
        await msg.add_reaction(EMOJIS['_yes'])
        resp = await self.bot.wait_for('raw_reaction_add', check=check_reaction)
        responder = resp.member

        # New responder found, return perms
        to_update = {chan.guild.get_role(x.role_id): DISCORD_PERMS['nothing'] for x in ticket.ticket_config.roles}
        to_update[responder] = DISCORD_PERMS['user']
        chan.overwrites.update(to_update)
        await chan.edit(reason="Set ticket review claimed.", overwrites=chan.overwrites)

        self.log.info("Ticket review is claimed: %s", chan.name)

        await log_channel.send(
            LOG_TEMPLATE.format(action="Reivew", user=self.msg.author.name,
                                msg="__New Reviewer:__ {}".format(responder.name))
        )

        return """Hello reviewer {}!. Above is a ticket.
Please read it over and provide feedback to requester who initiated the request.

Thank you very much.""".format(responder.mention)

    async def execute(self):
        try:
            ticket = tickdb.query.get_ticket(self.session, self.msg.guild.id, channel_id=self.msg.channel.id)
            log_channel = self.msg.guild.get_channel(ticket.guild.log_channel_id)
            # If log channel not configured, dev null log messages
            if not log_channel:
                log_channel = aiomock.AIOMock()
                log_channel.send.async_return_value = True
        except (sqla_oexc.NoResultFound, sqla_oexc.MultipleResultsFound) as e:
            raise tick.exc.InvalidCommandArgs("Tickets not configured. See `{prefix}admin`".format(prefix=self.bot.prefix)) from e

        try:
            func = getattr(self, self.args.subcmd)
            resp = await func(ticket, log_channel)
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


async def new_ticket_request(client, chan, user, ticket_config):
    """
    Within the newly made ticket:
        - Ask the user in the newly made tickets questions to gather information.
        - Allow a roled member to claim the ticket after that.

    Args:
        client: An instance of the bot.
        chan: The new ticket channel.
        user: The original requesting user.
        config: The ticket configuration.
    """
    def check_msg(msg):
        """ Wait for a response in from the user inside ticket channel. """
        return msg.channel == chan and msg.author == user

    def check_reaction(event):
        """
        Notable: e.emoji, e.member, e.message_id, e.channel_id
        https://discordpy.readthedocs.io/en/stable/api.html#discord.RawReactionActionEvent
        """
        return (event.channel_id == chan.id
                and event.member != user
                and event.member != client.user
                and str(event.emoji) == EMOJIS['_yes'])

    log_channel = chan.guild.get_channel(ticket_config.guild_config.log_channel_id)
    await log_channel.send(
        LOG_TEMPLATE.format(action="Ticket Created", user=user.name,
                            msg=f"{ticket_config.name} ticket created.")
    )
    msg = await chan.send(TICKET_DIRECTIONS.format(prefix=client.prefix))
    await msg.pin()
    with tickdb.session_scope(tickdb.Session) as session:
        ticket = tickdb.schema.Ticket(
            guild_id=ticket_config.guild.id,
            ticket_config_id=ticket_config.id,
            user_id=user.id,
            channel_id=chan.id,
        )
        session.add(ticket)
        session.commit()

        pin_first = True
        jump_url = "No jump set."
        for question in ticket_config.questions:
            msg = await chan.send(question)
            if pin_first:
                pin_first = False
                jump_url = msg.jump_url
                await msg.pin()
            resp = await client.wait_for('message', check=check_msg)
            tickdb.query.add_ticket_response(session, ticket, resp.content)

        mentions = " ".join([chan.guild.get_role(x.role_id).mention for x in ticket_config.roles])
        msg = await chan.send(TICKET_UNCLAIMED.format(jump_url=jump_url, mentions=mentions))
        await msg.add_reaction(EMOJIS['_yes'])
        resp = await client.wait_for('raw_reaction_add', check=check_reaction)
        ticket.responder_id = resp.member.id

        # Remove responding roles, whitelist user
        to_update = {chan.guild.get_role(x.role_id): DISCORD_PERMS['nothing'] for x in ticket.ticket_config.roles}
        to_update[resp.member] = DISCORD_PERMS['user']
        chan.overwrites.update(to_update)
        await chan.edit(reason="Set ticket to claimed.", overwrites=chan.overwrites)

        await log_channel.send(
            LOG_TEMPLATE.format(action="Ticket Taken", user=user.name,
                                msg="__Responder:__ {}".format(resp.member.name)),
        )
        await chan.send('Hope your new responder {} can help. Take care!'.format(resp.member.mention))


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


async def wait_for_user_reaction(client, chan, author, text, *, yes=EMOJIS['_yes'], no=EMOJIS['_no']):
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
