"""
Module should handle logic related to querying/manipulating tables from a high level.
"""
from tickdb.schema import (Ticket, GuildConfig)


def get_guild_config(session, guild_id):
    """
    Get the guild config for a given guild id.

    Returns: A GuildConfig object for that server or None if not found.

    Raises: NoResultFound, MultipleResultsFound
    """
    return session.query(GuildConfig).filter(GuildConfig.id == guild_id).one()


def get_ticket(session, *, user_id=None, channel_id=None):
    """
    Get the ticket information for a given ticket.

    Returns: A Ticket assuming one was matched. Otherwise it returns None.

    Raises: NoResultFound, MultipleResultsFound
    """
    query = session.query(Ticket)

    if user_id:
        query = query.filter(Ticket.user_id == user_id)
    if channel_id:
        query = query.filter(Ticket.channel_id == channel_id)

    return query.one()
