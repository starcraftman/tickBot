"""
Define the database schema and some helpers.

N.B. Schema defaults only applied once object commited.
"""
import datetime
import sqlalchemy as sqla
import sqlalchemy.ext.declarative

import tick.util
import tickdb


LEN_ROLE = 100
LEN_TEXT = 1500
LEN_TICKET_NAME = 20
LEN_TICKET_PREFIX = 20
DEFAULT_TICKET_TIMEOUT = 7200
Base = sqlalchemy.ext.declarative.declarative_base()


class GuildConfig(Base):
    """
    Configuration for a particular server.
    """
    __tablename__ = 'guild_configs'

    id = sqla.Column(sqla.BigInteger, primary_key=True)  # The actual guild id
    category_channel_id = sqla.Column(sqla.BigInteger)  # Category id all tickets created under
    log_channel_id = sqla.Column(sqla.BigInteger)  # Logging channel
    ticket_channel_id = sqla.Column(sqla.BigInteger)  # Channel where tickets will start
    pinned_message_id = sqla.Column(sqla.BigInteger)  # The pinned message to check reactions for

    ticket_configs = sqla.orm.relationship(
        'TicketConfig', lazy='select', uselist=True, back_populates='guild',
    )
    tickets = sqla.orm.relationship(
        'Ticket', lazy='select', uselist=True, back_populates='guild',
    )

    def __repr__(self):
        keys = ['id', 'category_channel_id', 'log_channel_id',
                'ticket_channel_id', 'pinned_message_id']
        kwargs = ['{}={!r}'.format(key, getattr(self, key)) for key in keys]

        return "{}({})".format(self.__class__.__name__, ', '.join(kwargs))

    def __eq__(self, other):
        return isinstance(other, GuildConfig) and self.id == other.id


class TicketConfig(Base):
    """
    A guild can have multiple types of tickets configured.
    """
    __tablename__ = 'ticket_configs'

    __table_args__ = (
        sqla.UniqueConstraint('guild_id', 'name', name='guild_id_name_constraint'),
        sqla.UniqueConstraint('guild_id', 'emoji_id', name='guild_id_emoji_id_constraint'),
        sqla.UniqueConstraint('guild_id', 'prefix', name='guild_id_prefix_constraint'),
    )

    guild = sqla.orm.relationship(
        'GuildConfig', lazy='select', uselist=False, back_populates='ticket_configs',
    )
    questions = sqla.orm.relationship(
        'TicketConfigText', lazy='select', uselist=True, back_populates='ticket_config',
        cascade="all, delete-orphan",
    )
    roles = sqla.orm.relationship(
        'TicketConfigRole', lazy='select', uselist=True, back_populates='ticket_config',
        cascade="all, delete-orphan",
    )
    tickets = sqla.orm.relationship(
        'Ticket', lazy='select', uselist=True, back_populates='ticket_config',
        cascade="all, delete-orphan",
    )

    id = sqla.Column(sqla.BigInteger, primary_key=True)
    guild_id = sqla.Column(sqla.BigInteger, sqla.ForeignKey('guild_configs.id'))  # The actual guild id
    name = sqla.Column(sqla.String(LEN_TICKET_NAME), default=tick.util.NOT_SET)  # Name for convenience
    prefix = sqla.Column(sqla.String(LEN_TICKET_PREFIX), default=tick.util.NOT_SET)  # Prefix for ticket names
    emoji_id = sqla.Column(sqla.BigInteger, default=0)  # Emoji id to react and make ticket with
    timeout = sqla.Column(sqla.Integer, default=DEFAULT_TICKET_TIMEOUT)  # Timeout for tickets to idle and cleanup

    def __repr__(self):
        keys = ['id', 'guild_id', 'name', 'emoji_id', 'prefix', 'prefix']
        kwargs = ['{}={!r}'.format(key, getattr(self, key)) for key in keys]

        return "{}({})".format(self.__class__.__name__, ', '.join(kwargs))

    def __eq__(self, other):
        return isinstance(other, TicketConfig) and self.id == other.id

    def kwargs(self):
        """
        Create a useful kwargs bundle.
        """
        roles = tick.util.NOT_SET
        if self.roles:
            roles = ", ".join([role.role_text for role in self.roles])

        timeout_str = "{:3.2f} hours ({} seconds)".format(float(self.timeout) / 3600.0, self.timeout)
        return {
            'name': self.name,
            'prefix': self.prefix,
            'emoji': tick.util.NOT_SET,
            'emoji_id': self.emoji_id,
            'timeout': timeout_str,
            'roles': roles,
        }


class TicketConfigRole(Base):
    __tablename__ = 'ticket_configs_roles'

    id = sqla.Column(sqla.BigInteger, primary_key=True)
    ticket_config_id = sqla.Column(sqla.BigInteger, sqla.ForeignKey('ticket_configs.id'))
    role_id = sqla.Column(sqla.BigInteger)
    role_text = sqla.Column(sqla.String(LEN_ROLE))

    ticket_config = sqla.orm.relationship(
        'TicketConfig', lazy='select', uselist=False, back_populates='roles',
    )

    def __repr__(self):
        keys = ['id', 'ticket_config_id', 'role_id', 'role_text']
        kwargs = ['{}={!r}'.format(key, getattr(self, key)) for key in keys]

        return "{}({})".format(self.__class__.__name__, ', '.join(kwargs))

    def __eq__(self, other):
        return isinstance(other, TicketConfigRole) and (self.id == other.id and self.role_id == other.role_id)

    @sqla.orm.validates('role_text')
    def validate_role_text(self, key, value):
        """
        Validate text and ensure it is what is expected and of right length.
        """
        try:
            if not value:
                raise ValueError("Text was empty.")
            if len(value) > LEN_ROLE:
                raise ValueError("Text longer than allowable {} chars.".format(LEN_TEXT))
        except TypeError:
            raise ValueError("Text was not of right type.")

        return value


class TicketConfigText(Base):
    """
    Storage for text that is associated with a TicketConfig
    """
    __tablename__ = 'ticket_configs_text'

    id = sqla.Column(sqla.BigInteger, primary_key=True)
    ticket_config_id = sqla.Column(sqla.BigInteger, sqla.ForeignKey('ticket_configs.id'))
    num = sqla.Column(sqla.Integer, default=1)
    text = sqla.Column(sqla.String(LEN_TEXT))

    ticket_config = sqla.orm.relationship(
        'TicketConfig', lazy='select', uselist=False, back_populates='questions',
    )

    def __repr__(self):
        keys = ['id', 'ticket_config_id', 'num', 'text']
        kwargs = ['{}={!r}'.format(key, getattr(self, key)) for key in keys]

        return "{}({})".format(self.__class__.__name__, ', '.join(kwargs))

    def __str__(self):
        return "{id}) {text}".format(id=self.num, text=self.text)

    def __eq__(self, other):
        return isinstance(other, TicketConfigText) and self.id == other.id

    @sqla.orm.validates('num')
    def validate_num(self, key, value):
        """
        Numbers must be valid.
        """
        try:
            if value < 0:
                raise ValueError("TicketTex.num must be >= 0.")
        except TypeError:
            raise ValueError("TicketText.num must be an integer.")

        return value

    @sqla.orm.validates('text')
    def validate_text(self, key, value):
        """
        Validate text and ensure it is what is expected and of right length.
        """
        try:
            if not value:
                raise ValueError("Text was empty.")
            if len(value) > LEN_TEXT:
                raise ValueError("Text longer than allowable {} chars.".format(LEN_TEXT))
        except TypeError:
            raise ValueError("Text was not of right type.")

        return value


class Ticket(Base):
    """
    A ticket in the system. Represents all the "current" information for one.
    """
    __tablename__ = 'tickets'

    id = sqla.Column(sqla.BigInteger, primary_key=True)
    guild_id = sqla.Column(sqla.BigInteger, sqla.ForeignKey('guild_configs.id'))
    ticket_config_id = sqla.Column(sqla.BigInteger, sqla.ForeignKey('ticket_configs.id'))
    user_id = sqla.Column(sqla.BigInteger)
    responder_id = sqla.Column(sqla.BigInteger)
    channel_id = sqla.Column(sqla.BigInteger, unique=True)
    created_at = sqla.Column(sqla.DateTime, default=datetime.datetime.utcnow)
    updated_at = sqla.Column(sqla.DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)
    closed_at = sqla.Column(sqla.DateTime)

    guild = sqla.orm.relationship(
        'GuildConfig', lazy='select', uselist=False, back_populates='tickets',
    )
    ticket_config = sqla.orm.relationship(
        'TicketConfig', lazy='select', uselist=False, back_populates='tickets',
    )
    texts = sqla.orm.relationship(
        'TicketText', lazy='select', uselist=True, back_populates='ticket',
        cascade="all, delete-orphan",
    )

    def __repr__(self):
        keys = ['id', 'guild_id', 'ticket_config_id', 'user_id', 'responder_id', 'channel_id'
                'created_at', 'updated_at', 'closed_at']
        kwargs = ['{}={!r}'.format(key, getattr(self, key)) for key in keys]

        return "{}({})".format(self.__class__.__name__, ', '.join(kwargs))

    def __str__(self):
        """
        Show additional computed properties.
        """
        return "id={!r}, {!r}".format(self.id, self)

    def __eq__(self, other):
        return isinstance(other, Ticket) and self.id == other.id


class TicketText(Base):
    """
    Storage for text that is associated with a Ticket.
    """
    __tablename__ = 'tickets_text'

    id = sqla.Column(sqla.BigInteger, primary_key=True)
    ticket_id = sqla.Column(sqla.BigInteger, sqla.ForeignKey('tickets.id'))
    num = sqla.Column(sqla.Integer, default=1)
    text = sqla.Column(sqla.String(LEN_TEXT))

    ticket = sqla.orm.relationship(
        'Ticket', lazy='select', uselist=False, back_populates='texts',
    )

    def __repr__(self):
        keys = ['id', 'ticket_id', 'num', 'text']
        kwargs = ['{}={!r}'.format(key, getattr(self, key)) for key in keys]

        return "{}({})".format(self.__class__.__name__, ', '.join(kwargs))

    def __str__(self):
        return "{id}) {text}".format(id=self.num, text=self.text)

    def __eq__(self, other):
        return isinstance(other, TicketConfigText) and self.id == other.id

    @sqla.orm.validates('num')
    def validate_num(self, key, value):
        """
        Numbers must be valid.
        """
        try:
            if value < 0:
                raise ValueError("TicketText.num must be >= 0")
        except TypeError:
            raise ValueError("TicketText.num must be an integer.")

        return value

    @sqla.orm.validates('text')
    def validate_text(self, key, value):
        """
        Validate text and ensure it is what is expected and of right length.
        """
        try:
            if not value:
                raise ValueError("Text was empty.")
            if len(value) > LEN_TEXT:
                raise ValueError("Text longer than allowable {} chars.".format(LEN_TEXT))
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
ALL_CLASSES = [TicketText, Ticket, TicketConfigText, TicketConfigRole, TicketConfig, GuildConfig]


def main():  # pragma: no cover
    """
    This continues to exist only as a sanity test for schema and relations.
    """
    recreate_tables()
    #  session = tickdb.Session()


if __name__ == "__main__":  # pragma: no cover
    main()
