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


def test_get_all_questions(session, f_questions):
    questions = tickdb.query.get_all_questions(session)
    assert questions[-1].text == f_questions[-1].text


def test_get_question_by_id_exists(session, f_questions):
    question = tickdb.query.get_question_by_id(session, id=3)
    assert question.id == f_questions[-1].id
    assert question.text == f_questions[-1].text


def test_get_question_by_id_not_exists(session, f_questions):
    question = tickdb.query.get_question_by_id(session, id=99)
    assert question.id == 99
    assert question.text == ''
