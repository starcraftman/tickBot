"""
Module should handle logic related to querying/manipulating tables from a high level.
"""
import datetime

import sqlalchemy as sqla

from tickdb.schema import (Ticket, GuildConfig, TicketText)
import tickdb.schema


def get_guild_config(session, guild_id):
    """
    Get the guild config for a given guild id.

    Args:
        session: Session to the db.
        guild_id: The id of the guild in question.

    Returns: A GuildConfig object for that server or None if not found.

    Raises: NoResultFound, MultipleResultsFound
    """
    return session.query(GuildConfig).filter(GuildConfig.id == guild_id).one()


def get_ticket(session, guild_id, *, user_id=None, channel_id=None):
    """
    Get the ticket information for a given ticket.

    Args:
        session: Session to the db.
        guild_id: The id of the guild in question.
        user_id: Lookup ticket by original user.
        channel_id: Lookup ticket by the channel id.

    Returns: A Ticket assuming one was matched. Otherwise it returns None.

    Raises: NoResultFound, MultipleResultsFound
    """
    query = session.query(Ticket).filter(Ticket.guild_id == guild_id)

    if user_id:
        query = query.filter(Ticket.user_id == user_id)
    if channel_id:
        query = query.filter(Ticket.channel_id == channel_id)

    return query.one()


async def get_active_tickets(session, guild):
    """
    Get all tickets for the guild.

    Args:
        session: Session to the db.
        guild: The guild being examined.

    Returns:
        all_ticks: All tickets currently in system for guild.
    """
    return session.query(Ticket).filter(Ticket.guild_id == guild.id).all();
