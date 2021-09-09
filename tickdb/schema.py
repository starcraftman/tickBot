"""
Define the database schema and some helpers.

N.B. Schema defaults only applied once object commited.
"""
import sqlalchemy as sqla
import sqlalchemy.ext.declarative

import tickdb


LEN_NAME = 100
LEN_REQUEST = 2500
LEN_QUESTION = 400
LEN_OVERSEER = 500
Base = sqlalchemy.ext.declarative.declarative_base()


class GuildConfig(Base):
    """
    Configuration for a particular server.
    """
    __tablename__ = 'configs'

    id = sqla.Column(sqla.BigInteger, primary_key=True)  # The actual guild id
    support_channel_id = sqla.Column(sqla.BigInteger)
    support_pin_id = sqla.Column(sqla.BigInteger)
    category_channel_id = sqla.Column(sqla.BigInteger)
    log_channel_id = sqla.Column(sqla.BigInteger)
    role_id = sqla.Column(sqla.BigInteger)
    adult_role_id = sqla.Column(sqla.BigInteger)
    overseer_role_ids = sqla.Column(sqla.String(LEN_OVERSEER), default="")
    # All for separate practice logic.
    practice_channel_id = sqla.Column(sqla.BigInteger)
    practice_role_id = sqla.Column(sqla.BigInteger)
    practice_pin_id = sqla.Column(sqla.BigInteger)

    def __repr__(self):
        keys = ['id', 'support_channel_id', 'category_channel_id', 'log_channel_id',
                'role_id', 'adult_role_id', 'practice_channel_id', 'practice_role_id',
                'practice_pin_id', 'overseer_role_ids']
        kwargs = ['{}={!r}'.format(key, getattr(self, key)) for key in keys]

        return "{}({})".format(self.__class__.__name__, ', '.join(kwargs))

    def __eq__(self, other):
        return isinstance(other, GuildConfig) and self.id == other.id


class Ticket(Base):
    """
    A ticket in the system.
    """
    __tablename__ = 'tickets'

    id = sqla.Column(sqla.Integer, primary_key=True)
    user_id = sqla.Column(sqla.BigInteger)
    supporter_id = sqla.Column(sqla.BigInteger)
    channel_id = sqla.Column(sqla.BigInteger)
    guild_id = sqla.Column(sqla.BigInteger, sqla.ForeignKey('configs.id'))
    request_msg = sqla.Column(sqla.String(LEN_REQUEST), default="")
    is_practice = sqla.Column(sqla.Boolean, default=False)
    created_at = sqla.Column(sqla.DateTime, server_default=sqla.func.now())
    updated_at = sqla.Column(sqla.DateTime, onupdate=sqla.func.now())

    def __repr__(self):
        keys = ['user_id', 'supporter_id', 'channel_id', 'guild_id', 'is_practice', 'created_at', 'updated_at']
        kwargs = ['{}={!r}'.format(key, getattr(self, key)) for key in keys]

        return "{}({})".format(self.__class__.__name__, ', '.join(kwargs))

    def __str__(self):
        """
        Show additional computed properties.
        """
        return "id={!r}, {!r}".format(self.id, self)

    def __eq__(self, other):
        return isinstance(other, Ticket) and self.name == other.name


class Question(Base):
    """
    A question to ask user upon every request.
    """
    __tablename__ = 'questions'

    id = sqla.Column(sqla.Integer, primary_key=True)
    text = sqla.Column(sqla.String(LEN_QUESTION), default="")

    def __repr__(self):
        keys = ['id', 'text']
        kwargs = ['{}={!r}'.format(key, getattr(self, key)) for key in keys]

        return "{}({})".format(self.__class__.__name__, ', '.join(kwargs))

    def __str__(self):
        return "{id}) {text}".format(id=self.id, text=self.text)

    def __eq__(self, other):
        return isinstance(other, Question) and self.id == other.id

    @sqla.orm.validates('text')
    def validate_text(self, key, value):
        """
        Validate text and ensure it is what is expected and of right length.
        """
        try:
            if not value:
                raise ValueError("Text was empty.")
            if len(value) > LEN_QUESTION:
                raise ValueError("Text longer than allowable {} chars.".format(LEN_QUESTION))
        except TypeError:
            raise ValueError("Text was not of right type.")

        return value


def empty_tables(session, *, perm=False):
    """
    Drop all tables.
    """
    for cls in ALL_CLASSES:
        for matched in session.query(cls):
            session.delete(matched)
    session.commit()


def recreate_tables():
    """
    Recreate all tables in the database, mainly for schema changes and testing.
    """
    Base.metadata.drop_all(tickdb.engine)
    Base.metadata.create_all(tickdb.engine)


if tickdb.TEST_DB:
    recreate_tables()
else:
    Base.metadata.create_all(tickdb.engine)
ALL_CLASSES = [Question, Ticket, GuildConfig]


def main():  # pragma: no cover
    """
    This continues to exist only as a sanity test for schema and relations.
    """
    Base.metadata.drop_all(tickdb.engine)
    Base.metadata.create_all(tickdb.engine)
    #  session = tickdb.Session()


if __name__ == "__main__":  # pragma: no cover
    main()
