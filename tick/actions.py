"""
To facilitate complex actions based on commands create a
hierarchy of actions that can be recombined in any order.
All actions have async execute methods.
"""
import logging

import discord

import tick.exc
import tick.tbl
import tick.util


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
        self.log = logging.getLogger(__name__)

    async def execute(self):
        """
        Take steps to accomplish requested action, including possibly
        invoking and scheduling other actions.
        """
        raise NotImplementedError


class Support(Action):
    """
    Provide the support command.
    """
    async def execute(self):
        response = "Please wait while support comes."

        await self.msg.channel.send(response)


class Ticket(Action):
    """
    Provide the ticket command.
    """
    async def create(self):
        """
        Create a ticket.
        """
        name = '-'.join(self.args.name)
        print('ticket create', name)
        guild = self.bot.guilds[0]
        print(guild.name)

        overwrites = {
            guild.default_role: discord.PermissionOverwrite(read_messages=False),
            guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True,
                                                  manage_channels=True),
            self.msg.author: discord.PermissionOverwrite(read_messages=True, send_messages=True),
        }
        chan = await guild.create_text_channel(name=name, topic=name, overwrites=overwrites,
                                               category=self.msg.channel.category)

        await chan.send("Welcome message here.")

        return 'Created: ' + name

    async def close(self):
        """
        Close a ticket.
        """
        reason = ' '.join(self.args.reason)
        await self.msg.channel.delete(reason=reason)

    async def rename(self):
        """
        Rename a ticket.
        """
        new_name = " ".join(self.args.name)
        await self.msg.channel.edit(reason='New name was requested.', name=new_name)

        return 'rename'

    async def execute(self):
        #  try:
        func = getattr(self, self.args.subcmd)
        resp = await func()
        if resp:
            await self.msg.channel.send(resp)
        #  except AttributeError:
            #  raise tick.exc.InvalidCommandArgs(
                #  "Bad subcommand of `{p}ticket`, see `{p}ticket -h` for help.".format(
                    #  p=self.bot.prefix))


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
        #  ['{prefix}admin', 'Admin commands'],
        lines = [
            ['Command', 'Effect'],
            ['{prefix}status', 'Info about this bot'],
            ['{prefix}help', 'This help message'],
        ]
        lines = [[line[0].format(prefix=prefix), line[1]] for line in lines]

        response = '\n'.join(over) + tick.tbl.wrap_markdown(tick.tbl.format_table(lines, header=True))
        await self.bot.send_ttl_message(self.msg.channel, response)
        await self.msg.delete()


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
