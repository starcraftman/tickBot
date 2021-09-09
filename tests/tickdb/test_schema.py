"""
Test the schema for the database.
"""
import pytest

import tickdb
import tickdb.schema
from tickdb.schema import (GuildConfig, Ticket, Question)


def test_empty_tables_all(session, f_guild_configs, f_tickets):
    classes = [GuildConfig, Ticket]
    for cls in classes:
        assert session.query(cls).all()

    tickdb.schema.empty_tables(session, perm=True)
    session.commit()

    for cls in classes:
        assert session.query(cls).all() == []


def test_guild_config__repr__(session, f_guild_configs, f_tickets):
    expect = "GuildConfig(id=1111, support_channel_id=1, category_channel_id=10, log_channel_id=2, role_id=3, adult_role_id=8, practice_channel_id=None, practice_role_id=None, practice_pin_id=None, overseer_role_ids='')"
    assert repr(f_guild_configs[0]) == expect


def test_ticket__repr__(session, f_guild_configs, f_tickets):
    expect = "Ticket(user_id=1, supporter_id=2, channel_id=222, guild_id=1111, is_practice=False"
    assert repr(f_tickets[0]).startswith(expect)


def test_question__repr__(session, f_questions):
    expect = "Question(id=3, text='What is the meaning of life?')"
    assert repr(f_questions[-1]) == expect


def test_question_validate_text(session, f_questions):
    with pytest.raises(ValueError):
        question = Question(text="")

    with pytest.raises(ValueError):
        question = Question(text="A" * 1000)

    with pytest.raises(ValueError):
        question = Question(text=55)
