"""
To facilitate complex actions based on commands create a
hierarchy of actions that can be recombined in any order.
All actions have async execute methods.
"""
import asyncio
import datetime
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
QUESTION_LENGTH_TOO_MUCH = f"""The response to the question was too long.
Please answer again with a message < {MAX_QUESTION_LEN} characters long.

To cancel any time, just reply with: **{QUESTIONS_CANCEL}**"""
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
Monitor Activity: {monitor_activity}
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

To close this ticket: {prefix}ticket close
To get a new supporter: {prefix}ticket unclaim
To get a reviewer: {prefix}ticket review
"""
KEY_CAP = '\N{COMBINING ENCLOSING KEYCAP}'  # Usage: str(1) + NUM_KEY => keycap 1
#  TICKET_INACTIVITY_SECS = 30 * 60
TICKET_INACTIVITY_SECS = 60
TICKET_INACTIVITY_WARNING = """Inactivity has been detected on this channel.

Pinging users to provide the option to cancel ticket close. By default if no response provided this ticket will be closed."""
TICKET_CLOSE_REASON = "Ticket over."

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
            if resp and len(resp.channel_mentions) == 1:
                resp_channel = resp.channel_mentions[0]
                check_chan_perms(resp_channel, 'log_required')
                guild_config.log_channel_id = resp_channel.id
                await chan.send(f"Setting log channel to: {resp_channel.mention}")
                break

        while True:
            await chan.send(MSG_OR_STOP.format("Please mention the channel to start tickets in."))
            resp = await client.wait_for('message', check=check)
            if resp and resp.content == STOP_MSG:
                return
            if resp and len(resp.channel_mentions) == 1:
                resp_channel = resp.channel_mentions[0]
                check_chan_perms(resp_channel, 'support_required')
                guild_config.ticket_channel_id = resp_channel.id
                await chan.send(f"Setting tickets channel to: {resp_channel.mention}")
                break

        while True:
            await chan.send(MSG_OR_STOP.format("Please type the **exact** name of the category for tickets."))
            resp = await client.wait_for('message', check=check)
            if resp and resp.content == STOP_MSG:
                return
            if resp:
                found = [x for x in self.msg.guild.categories if x.name.lower() == resp.content.lower()]
                if not found:
                    await chan.send("Failed to match category name, please try again.")
                else:
                    resp_channel = found[0]
                    check_chan_perms(resp_channel, 'category_required')
                    guild_config.category_channel_id = resp_channel.id
                    await chan.send(f"Setting tickets category to: {resp_channel.name}")
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
        setup_intro = f"""Creating or updating a ticket flow called: {ticket_config.name}.

Please type a unique prefix of lenth < {tickdb.schema.LEN_TICKET_PREFIX} for ticket channels."""
        while True:
            await chan.send(MSG_OR_STOP.format(setup_intro))
            resp = await client.wait_for('message', check=check_msg)
            if resp and resp.content == STOP_MSG:
                return
            if resp and len(resp.content) <= tickdb.schema.LEN_TICKET_PREFIX:
                ticket_config.prefix = resp.content
                try:
                    self.session.flush()
                except sqlalchemy.exc.IntegrityError:
                    self.session.rollback()
                    continue
                await chan.send(f"Setting prefix for ticket channels to: {resp.content}")
                break

        while True:
            await chan.send("Please react with a custom server emoji used to start tickets.")
            event = await client.wait_for('raw_reaction_add', check=check_reaction)
            ticket_config.emoji_id = event.emoji.id
            try:
                self.session.flush()
                await chan.send(f"Setting emoji to start tickets: {event.emoji}")
                break
            except sqlalchemy.exc.IntegrityError:
                self.session.rollback()
                continue

        ticket_config.monitor_activity, _ = await wait_for_user_reaction(
            self.bot, self.msg.channel,
            "Do you want activity monitored? Inactive tickets will be auto closed after warning.",
            author=self.msg.author
        )
        await chan.send(f"Inactivity monitoring for these tickets: {ticket_config.monitor_activity}")

        while True:
            await chan.send(MSG_OR_STOP.format("Mention ALL the roles you want to respond to these tickets."))
            resp = await client.wait_for('message', check=check_msg)
            if resp and resp.content == STOP_MSG:
                break
            if resp and len(resp.role_mentions) > 0:
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
                    role_text += f"\n {r_mention.name}"

                await chan.send(f"Setting roles to the following:\n{role_text}")
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
        resp, _ = await wait_for_user_reaction(
            self.bot, self.msg.channel,
            f"Please confirm that you want to remove ticket flow: {ticket_config.name}. This will only remove configuration and pin.",
            author=self.msg.author)
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
        except (sqla_oexc.NoResultFound, sqla_oexc.MultipleResultsFound) as exc:
            raise tick.exc.InvalidCommandArgs("I can only close within ticket channels.") from exc

        chan = self.bot.get_channel(ticket.channel_id)
        reason = ' '.join(self.args.reason)

        delete_ticket = await close_ticket(self.bot, chan, ticket, reason=reason, mention_users=False)
        if delete_ticket:
            self.session.delete(ticket)

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
        except (sqla_oexc.NoResultFound, sqla_oexc.MultipleResultsFound) as exc:
            raise tick.exc.InvalidCommandArgs("I can only swap supporters in ticket channels.") from exc

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
                                msg=f"__Old Responder:__ {old_responder.name}\n__New Responder:__ {responder.name}"),
        )

        return f'Hope your new responder {responder.mention} can help. Take care!'

    async def review(self, ticket, log_channel):
        """
        Review the events of a ticket by another responder.
        """
        try:
            ticket = tickdb.query.get_ticket(self.session, self.msg.guild.id, channel_id=self.msg.channel.id)
        except (sqla_oexc.NoResultFound, sqla_oexc.MultipleResultsFound) as exc:
            raise tick.exc.InvalidCommandArgs("I can only review inside ticket channels.") from exc

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
                                msg=f"__New Reviewer:__ {responder.name}")
        )

        return f"""Hello reviewer {responder.mention}!. Above is a ticket.
Please read it over and provide feedback to requester who initiated the request.

Thank you very much."""

    async def execute(self):
        try:
            ticket = tickdb.query.get_ticket(self.session, self.msg.guild.id, channel_id=self.msg.channel.id)
            log_channel = self.msg.guild.get_channel(ticket.guild.log_channel_id)
            # If log channel not configured, dev null log messages
            if not log_channel:
                log_channel = aiomock.AIOMock()
                log_channel.send.async_return_value = True
        except (sqla_oexc.NoResultFound, sqla_oexc.MultipleResultsFound) as exc:
            raise tick.exc.InvalidCommandArgs(f"Tickets not configured. See `{self.bot.prefix}admin -h`") from exc

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
            f'For more information do: `{prefix}Command -h`',
            f'       Example: `{prefix}admin -h`',
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
            ['Version', f'{tick.__version__}'],
        ]

        await self.msg.channel.send(tick.tbl.wrap_markdown(tick.tbl.format_table(lines)))


async def new_ticket_request(client, session, chan, user, ticket_config):
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

    log_channel = chan.guild.get_channel(ticket_config.guild.log_channel_id)
    await log_channel.send(
        LOG_TEMPLATE.format(action="Ticket Created", user=user.name,
                            msg=f"{ticket_config.name} ticket created.")
    )
    msg = await chan.send(TICKET_DIRECTIONS.format(prefix=client.prefix))
    await msg.pin()
    ticket = tickdb.schema.Ticket(
        guild_id=ticket_config.guild.id,
        ticket_config_id=ticket_config.id,
        user_id=user.id,
        channel_id=chan.id,
    )
    session.add(ticket)
    session.commit()

    # Questions to user
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

    # Get someone to claim
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
                            msg=f"__Responder:__ {resp.member.name}"),
    )
    await chan.send(f'Hope your new responder {resp.member.mention} can help. Take care!')


async def ticket_activity_monitor(client, interval):
    """Monitor the activity of tickets, automatically close tickets that are inactive.

    This task will schedule itself indefinitely once started.
    It must continue operation.

    Args:
        client: The discord bot itself.
        interval: The interval between running the checks, seconds.
    """
    with tickdb.session_scope(tickdb.Session) as session:
        for ticket in tickdb.query.get_all_tickets(session, remove_ignored=True):
            asyncio.create_task(check_ticket(client, ticket.guild_id, ticket.channel_id))

    await asyncio.sleep(interval)
    asyncio.create_task(ticket_activity_monitor(client, interval))


async def check_ticket(client, guild_id, channel_id):
    """Check a ticket for activity.

    Args:
        client: The bot client.
        ticket_id: The ticket object from db.
    """
    now = datetime.datetime.utcnow()
    with tickdb.session_scope(tickdb.Session) as session:
        ticket = tickdb.query.get_ticket(session, guild_id, channel_id=channel_id)
        t_channel = client.get_channel(ticket.channel_id)

        if not t_channel:  # Cleanup leftovers if something went wrong or channel removed
            session.delete(ticket)
            return

        async for msg in t_channel.history(limit=100):
            if msg.author == client.user:  # Skip bot messages
                continue

            if (now - msg.created_at).seconds > TICKET_INACTIVITY_SECS:
                deleted = await close_ticket(client, t_channel, ticket, timeout_confirms=True)
                if deleted:
                    session.delete(ticket)

            break  # Only look at last message not bot


async def close_ticket(client, channel, ticket, *, timeout_confirms=False,
                       reason=TICKET_CLOSE_REASON, mention_users=True):
    fname, close_confirmed, dm_log = '', None, None
    try:
        # Channel topic is format: A private ticket for username, user might not still be on server
        username = channel.topic.split(" ")[-1]
        guard_number = 100
        mention = ''
        if mention_users:
            mention = f"{channel.guild.get_member(ticket.user_id).mention}"
            if ticket.responder_id:
                mention = f"{channel.guild.get_member(ticket.responder_id).mention}"

        if timeout_confirms:
            await channel.send(TICKET_INACTIVITY_WARNING)
        try:
            close_confirmed, dm_log = await ask_to_close_ticket(client, channel, timeout=30,
                                                                default_on_timeout=guard_number, mention=mention)
            if not close_confirmed:
                await channel.send("Cancelling ticket close.")
                return False
        except asyncio.TimeoutError:
            if not timeout_confirms:
                await channel.send("Cancelling ticket close.")
                return False

        last_msg = await channel.fetch_message(channel.last_message_id)
        fname = await create_log(last_msg, os.path.join(tempfile.mkdtemp(), channel.name + ".txt"))
        if dm_log:
            try:
                user = channel.guild.get_member(ticket.user_id)
                if user:
                    await user.send("The log of your support session. Take care.",
                                    files=[discord.File(fp=fname, filename=os.path.basename(fname))])
            except discord.Forbidden:
                await channel.send(TICKET_CLOSE_PERMS.format(username))

        log_channel = client.get_channel(ticket.guild.log_channel_id)
        if timeout_confirms  and close_confirmed == guard_number:
            reason = "Inactive ticket."
        await log_channel.send(
            LOG_TEMPLATE.format(action="Close", user=username,
                                msg=f"__Reason:__ {reason}"),
            files=[discord.File(fp=fname, filename=os.path.basename(fname))]
        )
        await channel.delete(reason=reason)
        return True
    finally:
        try:
            shutil.rmtree(os.path.dirname(fname))
        except (FileNotFoundError, OSError):
            pass


async def create_log(last_msg, fname=None):
    """
    Log a whole channel's history to a file for preservation.

    Args:
        filename: The path of the file to write out.
        last_msg: The last message sent in channel to archive

    Returns: The file path.
    """
    if not fname:
        fname = f"{last_msg.channel.name:50}.txt"
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


async def ask_to_close_ticket(client, channel, *,
                              author=None, timeout=RESPONSE_TIMEOUT, default_on_timeout=False, mention=''):
    """Ask users in a ticket the following:
    Will ping both users on first dialog.

    Args:
        client: The bot itself.
        channel: The channel of the ticket.

    Kwargs:
        author: If passed in, will only allow author to respond. Default is None, no restriction.
        timeout: A timeout to use as max possible.
        default_on_timeout: Assume this boolean for close_confirmed on timeout.
        mention: If passed in, will be appended to close request to get users attention. By default it is nothing.

    Returns:
        (close_confirmed, dm_log):
            close_confirmed - User has confirmed desire to close this. Otherwise, timeout expired and automatic assume.
            dm_log - User explicitly indicated would like log of ticket. On timeout of confirmation, assumed no.

    Raises:
        asyncio.TimeoutError : User didn't respond in time.
    """
    close_confirmed = False
    dm_log = False

    close_text = f"Please confirm that you want to close ticket by reacting below.\n\n{mention}"
    close_confirmed, _ = await wait_for_user_reaction(
        client, channel,
        close_text,
        author=author, timeout=timeout)

    if not close_confirmed:  # Do not bother people cancelling with DM question.
        return False, False

    dm_log, _ = await wait_for_user_reaction(
        client, channel,
        "Closing ticket. Do you want a log of this ticket DMed to user?",
        author=author, timeout=timeout)

    return (close_confirmed, dm_log)


async def wait_for_user_reaction(client, chan, text, *,
                                 author=None, timeout=RESPONSE_TIMEOUT,
                                 yes_emoji=EMOJIS['_yes'], no_emoji=EMOJIS['_no']):
    """
    A simple reusable mechanism to present user with a choice and wait for reaction.

    Args:
        client: The bot client.
        chan: The channel to send the message to.
        text: The message to send to channel.
    Kwargs:
        author: The only author allowed to react. Default none, anyone can.
        yes_emoji: The yes emoji to use in unicode.
        no_emoji: The no emoji to use in unicode.

    Returns: (Boolean, msg_sent)
        True if user accepted otherwise False.

    Raises:
        TimeoutError - User didn't react within the timeout.
    """
    msg = await chan.send(text)
    await msg.add_reaction(yes_emoji)
    await msg.add_reaction(no_emoji)

    def check_reaction(react, user):
        if author:
            if user != author:
                return False

        return str(react) in (yes_emoji, no_emoji)

    react, _ = await client.wait_for('reaction_add', check=check_reaction, timeout=timeout)

    return str(react) == yes_emoji, msg
