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
    desc = """Ticket command.

{prefix}ticket create name of the ticket
        Create a ticket.
{prefix}ticket close
        Close a ticket.
{prefix}ticket rename
        Rename an existing ticket from inside the channel.
    """.format(prefix=prefix)
    sub = subs.add_parser(prefix + 'ticket', description=desc, formatter_class=RawHelp)
    sub.set_defaults(cmd='Ticket')
    tick_subs = sub.add_subparsers(title='subcommands',
                                   description='Ticket subcommands', dest='subcmd')

    tick_sub = tick_subs.add_parser('create', help='Create a new ticket.')
    tick_sub.add_argument('name', nargs='+', help='The name of the ticket.')
    tick_sub = tick_subs.add_parser('close', help='Close a ticket.')
    tick_sub.add_argument('reason', nargs='+', help='The name of the ticket.')
    tick_sub = tick_subs.add_parser('rename', help='ate a new ticket.')
    tick_sub.add_argument('name', nargs='+', help='The name of the ticket.')


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
