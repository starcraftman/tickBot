"""
Module should handle logic related to querying/manipulating tables from a high level.
"""
import sqlalchemy as sqla
import sqlalchemy.orm.exc as sqla_oexc

from tickdb.schema import (GuildConfig, TicketConfig, TicketConfigText, TicketConfigRole, Ticket, TicketText)
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


def get_ticket_config(session, guild_id, emoji_id):
    """
    To be used on creating a ticket.
    """
    return session.query(TicketConfig).\
        filter(TicketConfig.guild_id == guild_id, TicketConfig.emoji_id == emoji_id).\
        one()


def get_or_add_ticket_config(session, guild_id, name):
    """
    Get the ticket config for a guild in question or return a new one.
    """
    try:
        found = session.query(TicketConfig).\
            filter(TicketConfig.guild_id == guild_id, TicketConfig.name == name).\
            one()
    except sqla_oexc.NoResultFound:
        found = TicketConfig(guild_id=guild_id, name=name)
        session.add(found)

    return found


def remove_roles_for_ticket(session, ticket_config):
    """
    Remove all the associated ticket roles, if any.
    """
    session.query(TicketConfigRole).\
        filter(TicketConfigRole.ticket_config_id == ticket_config.id).\
        delete()


def add_ticket_question(session, ticket_config, text):
    """Set a ticket question in the database.

    Args:
        session: The session to the database.
        num: The number of the question. 0 for welcome text.
        text: The text in question to use.
    """
    found = TicketConfigText(
        ticket_config_id=ticket_config.id,
        text=text
    )
    session.add(found)

    return found


def add_ticket_response(session, ticket, text):
    """Add a ticket answer to the database.

    Args:
        session: The session to the database.
        ticket: The ticket associated with the reply text.
        text: The text replied to the question.
    """
    found = TicketText(
        ticket_id=ticket.id,
        text=text,
    )
    session.add(found)

    return found


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
    return session.query(Ticket).filter(Ticket.guild_id == guild.id).all()
