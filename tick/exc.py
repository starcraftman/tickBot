"""
Common exceptions.
"""


class TicketException(Exception):
    """
    All exceptions subclass this. All exceptions can:
        - Write something useful to the log.
        - Reply to the user with some relevant response.
    """
    def __init__(self, msg=None, lvl='info'):
        super().__init__()
        self.log_level = lvl
        self.message = msg

    def reply(self):
        """
        Construct a reponse to user.
        """
        return self.message

    def __str__(self):
        return str(self.reply())

    def write_log(self, log, *, content, author, channel):
        """
        Log all relevant message about this session.
        """
        log_func = getattr(log, self.log_level)
        header = '\n{}\n{}\n'.format(self.__class__.__name__ + ': ' + self.reply(), '=' * 20)
        log_func(header + log_format(content=content, author=author, channel=channel))


class UserException(TicketException):
    """
    Exception occurred usually due to user error.

    Not unexpected but can indicate a problem.
    """
    pass


class ArgumentParseError(UserException):
    """ Error raised on failure to parse arguments. """
    pass


class ArgumentHelpError(UserException):
    """ Error raised on request to print help for command. """
    pass


class InvalidCommandArgs(UserException):
    """ Unable to process command due to bad arguements.  """
    pass


class InvalidPerms(UserException):
    """ Unable to process command due to insufficient permissions.  """
    pass


class InvalidInput(UserException):
    """ User provided invalid input. """
    pass


def log_format(*, content, author, channel):
    """ Log useful information from discord.py """
    msg = "{aut} sent {cmd} from {cha}/{srv}"
    msg += "\n    Discord ID: " + str(author.id)
    msg += "\n    Username: {}#{}".format(author.name, author.discriminator)
    for role in author.roles[1:]:
        msg += "\n    {} on {}".format(role.name, role.guild.name)

    return msg.format(aut=author.display_name, cmd=content,
                      cha=channel, srv=channel.guild)
