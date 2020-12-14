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
    desc = """Admin command, usable by user with the following server role:
        `Ticket Supervisor`

{prefix}admin category unique substring
        Bot will create tickets under the category indicated by `unique substring`.
{prefix}admin log #mention-log-channel
        Set bot to log finished tickets to this channel for upload.
{prefix}admin role @role
        Set bot to ping mentioned role for tickets.
{prefix}admin adult_role @role
        Set bot to ping mentioned adult_role for tickets when an adult needed.
{prefix}admin support #mention-support-channel
        Set bot to monitor this channel for support requests.
{prefix}admin support #mention-support-channel
        Set bot to monitor this channel for support requests.
{prefix}admin practice_role @role
        Set the practice support role to pin on request.
{prefix}admin practice_support #mention-support-channel
        Set the practice support channel pin in the mentioned channel.
{prefix}admin summary
        List the current configuration for tickets.
    """.format(prefix=prefix)
    sub = subs.add_parser(prefix + 'admin', description=desc, formatter_class=RawHelp)
    sub.set_defaults(cmd='Admin')
    tick_subs = sub.add_subparsers(title='subcommands',
                                   description='Admin subcommands', dest='subcmd')

    tick_sub = tick_subs.add_parser('category', help='The category to put new tickets under.')
    tick_sub.add_argument('name', nargs='+', help='The unique substring of the category.')
    tick_sub = tick_subs.add_parser('logs', help='Send logs to mentioned channel.')
    tick_sub = tick_subs.add_parser('role', help='The role to ping for tickets.')
    tick_sub = tick_subs.add_parser('adult_role', help='The role to ping for adult tickets.')
    tick_sub = tick_subs.add_parser('support', help='Respond to support in mentioned channel.')
    tick_sub = tick_subs.add_parser('practice_role', help='The role to ping for practice.')
    tick_sub = tick_subs.add_parser('practice_support', help='The channel to start a practice session')
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
    tick_sub.add_argument('reason', nargs='+', help='The name of the ticket.')
    tick_sub = tick_subs.add_parser('rename', help='ate a new ticket.')
    tick_sub.add_argument('name', nargs='+', help='The name of the ticket.')
    tick_sub = tick_subs.add_parser('review', help='Get a responder to review.')
    tick_sub = tick_subs.add_parser('swap', help='Get a new responder.')


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
