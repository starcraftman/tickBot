"""
Test cogdb.query module.
"""
import sqlalchemy.orm.exc as sqla_oexc
import pytest

import tickdb
from tickdb.schema import (GuildConfig)
import tickdb.query


def test_get_guild_config(session, f_guild_configs):
    guild_config = tickdb.query.get_guild_config(session, 1111)

    assert isinstance(guild_config, GuildConfig)


def test_get_guild_config_invalid(session, f_guild_configs):
    with pytest.raises(sqla_oexc.NoResultFound):
        tickdb.query.get_guild_config(session, 9999)


def test_get_get_ticket(session, f_guild_configs, f_tickets):
    tick = tickdb.query.get_ticket(session, 1111, user_id=1)
    assert tick.supporter_id == 2

    tick = tickdb.query.get_ticket(session, 1111, channel_id=241)
    assert tick.supporter_id == 11
