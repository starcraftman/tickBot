"""
Everything related to parsing arguements from the received text.

By setting defaults passed on the parser (cmd, subcmd) can differeciate
what action to be invoked.
"""
import argparse
from argparse import RawDescriptionHelpFormatter as RawHelp

import tick.exc

PARSERS = []


class ThrowArggumentParser(argparse.ArgumentParser):
    """
    ArgumentParser subclass that does NOT terminate the program.
    """
    def print_help(self, file=None):  # pylint: disable=redefined-builtin
        formatter = self._get_formatter()
        formatter.add_text(self.description)
        raise tick.exc.ArgumentHelpError(formatter.format_help())

    def error(self, message):
        raise tick.exc.ArgumentParseError(message)

    def exit(self, status=0, message=None):
        """
        Suppress default exit behaviour.
        """
        raise tick.exc.ArgumentParseError(message)


def make_parser(prefix):
    """
    Returns the bot parser.
    """
    parser = ThrowArggumentParser(prog='', description='simple discord bot')

    subs = parser.add_subparsers(title='subcommands',
                                 description='The subcommands of tick')

    for func in PARSERS:
        func(subs, prefix)

    return parser


def register_parser(func):
    """ Simple registration function, use as decorator. """
    PARSERS.append(func)
    return func


@register_parser
def subs_admin(subs, prefix):
    """ Subcommand parsing for admin """
    desc = """Admin command, usable by user(s) with the following server role:
        `Ticket Supervisor`

To setup run in following order:
        {prefix}admin guild_setup
        {prefix}admin pin
        {prefix}admin ticket_setup [name]

{prefix}admin guild_setup
        Run through interactive configuration for the guild.
{prefix}admin pin
        Write a message to be pinned in ticket channel.
        Tickets reactions will be hooked onto this pinned message.
        Configuration of individual tickets will come after this pin.
{prefix}admin ticket_setup [name]
        Run through interactive configuration for one ticket flow on guild.
{prefix}admin ticket_remove [name]
        Remove a ticket flow, all questions and the config will be purged.
{prefix}admin ticket_questions [name]
        You will be able to view, edit or delete existing questions or add new ones.
{prefix}admin summary
        List the current configuration for the guild's tickets.
    """.format(prefix=prefix)
    sub = subs.add_parser(prefix + 'admin', description=desc, formatter_class=RawHelp)
    sub.set_defaults(cmd='Admin')
    tick_subs = sub.add_subparsers(title='subcommands',
                                   description='admin subcommands', dest='subcmd')

    tick_sub = tick_subs.add_parser('guild_setup', help='Perform interactive guild configuration.')
    tick_sub = tick_subs.add_parser('pin', help='Create the main support pin.')
    tick_sub = tick_subs.add_parser('ticket_setup', help='Configure an individual ticket.')
    tick_sub.add_argument('name', help='The unique name of the ticket config.')
    tick_sub = tick_subs.add_parser('ticket_remove', help='Remove an individual ticket and questions.')
    tick_sub.add_argument('name', help='The unique name of the ticket config.')
    tick_sub = tick_subs.add_parser('questions', help='Create the main support pin.')
    tick_sub.add_argument('name', help='The unique name of the ticket config.')
    tick_sub = tick_subs.add_parser('summary', help='Show the current configuration.')


@register_parser
def subs_ticket(subs, prefix):
    """ Subcommand parsing for admin """
    desc = """Ticket command.

{prefix}ticket close A reason to close ticket.
        Close a ticket.
{prefix}ticket rename a-new-name
        Rename an existing ticket from inside the channel.
{prefix}ticket swap
        The existing responder has to go, will reping for a new one.
{prefix}ticket review
        For use in practice tickets, pings for a reviewer to provide feedback.
    """.format(prefix=prefix)
    sub = subs.add_parser(prefix + 'ticket', description=desc, formatter_class=RawHelp)
    sub.set_defaults(cmd='Ticket')
    tick_subs = sub.add_subparsers(title='subcommands',
                                   description='Ticket subcommands', dest='subcmd')

    tick_sub = tick_subs.add_parser('close', help='Close a ticket.')
    tick_sub.add_argument('reason', nargs='*', default=["Ticket over."], help='The reason to close the ticket.')
    tick_subs.add_parser('review', help='Get a responder to review.')
    tick_subs.add_parser('unclaim', help='Get a new responder.')


@register_parser
def subs_help(subs, prefix):
    """ Subcommand parsing for help """
    sub = subs.add_parser(prefix + 'help', description='Show overall help message.')
    sub.set_defaults(cmd='Help')


@register_parser
def subs_status(subs, prefix):
    """ Subcommand parsing for status """
    sub = subs.add_parser(prefix + 'status', description='Info about this bot.')
    sub.set_defaults(cmd='Status')
