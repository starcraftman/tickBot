"""
Module should handle logic related to querying/manipulating tables from a high level.
"""
import datetime

from tickdb.schema import (Ticket, GuildConfig)


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
    Get all tickets currently active.
    Also get a list of tickets will no activity in last 3 days and 7 days.
    Tickets will be live updated with following information:
        channel_name -> channel name
        last_msg -> datetime of last message sent

    Args:
        session: Session to the db.
        guild: The guild being examined.

    Returns:
        (all_ticks, three_days, seven_days)
        all_ticks: All tickets currently in system for guild.
    """
    three_ago = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=3)
    seven_ago = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=7)

    all_ticks, three_days, seven_days = [], [], []
    for tick in session.query(Ticket).filter(Ticket.guild_id == guild.id).all():
        channel = await guild.get_channel(tick.channel_id)
        async for msg in channel.history(limit=1):
            last_sent = msg
        tick.last_msg = last_sent.created_at
        tick.channel_name = channel.name

        if last_sent.created_at < seven_ago:
            seven_days += [tick]
        elif last_sent.created_at < three_ago:
            three_days += [tick]
        all_ticks += [tick]

    return (all_ticks, three_days, seven_days)
