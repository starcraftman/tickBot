"""
Used for pytest fixtures and anything else test setup/teardown related.
"""
import datetime
import sys

import aiomock
import pytest
try:
    import uvloop
    LOOP = uvloop.new_event_loop
    L_SHOW = LOOP()
    L_SHOW.set_debug(True)
    print("Test loop policy:", str(L_SHOW))
    del L_SHOW
except ImportError:
    print("Missing: uvloop")
    sys.exit(1)

import tick.util
import tickdb
import tickdb.query
from tickdb.schema import (GuildConfig, Ticket, Question)


#  @pytest.yield_fixture(scope='function', autouse=True)
#  def around_all_tests(session):
    #  """
    #  Executes before and after EVERY test.

    #  Can be helpful for tracking bugs, like dirty database after test.
    #  Disabled unless needed. Non-trivial overhead.
    #  """
    #  start = datetime.datetime.now(datetime.timezone.utc)
    #  yield
    #  print(" Time", datetime.datetime.now(datetime.timezone.utc) - start, end="")

    #  classes = [DUser, SheetRow, System, SystemUM, Drop, Hold, KOS]
    #  for cls in classes:
        #  assert not session.query(cls).all()


@pytest.fixture
def event_loop():
    """
    Provide a a new test loop for each test.
    Save system wide loop policy, and use uvloop if available.

    To test either:
        1) Mark with pytest.mark.asyncio
        2) event_loop.run_until_complete(asyncio.gather(futures))
    """
    loop = LOOP()
    loop.set_debug(True)

    yield loop

    loop.close()


@pytest.fixture
def session():
    session = tickdb.Session()

    yield tickdb.Session()

    session.close()


@pytest.fixture
def db_cleanup(session):
    """
    Clean the whole database. Guarantee it is empty.
    Used when tests don't use a fixture.
    """
    yield

    tickdb.schema.empty_tables(session, perm=True)

    classes = [Ticket, GuildConfig]
    for cls in classes:
        assert session.query(cls).all() == []


@pytest.fixture
def f_guild_configs(session):
    """
    Fixture to insert some test GuildConfigs.
    """
    configs = (
        GuildConfig(id=1111, support_channel_id=1, category_channel_id=10, log_channel_id=2,
                    role_id=3, adult_role_id=8),
        GuildConfig(id=3333, support_channel_id=9, category_channel_id=90, log_channel_id=18,
                    role_id=27, adult_role_id=8),
    )
    session.add_all(configs)
    session.commit()

    yield configs

    for matched in session.query(GuildConfig):
        session.delete(matched)
    session.commit()


@pytest.fixture
def f_tickets(session):
    """
    Fixture to insert some test Tickets.
    """
    tickets = (
        Ticket(id=1, user_id=1, supporter_id=2, channel_id=222, guild_id=1111),
        Ticket(id=2, user_id=5, supporter_id=2, channel_id=223, guild_id=1111),
        Ticket(id=3, user_id=6, supporter_id=11, channel_id=241, guild_id=1111),
        Ticket(id=4, user_id=32, supporter_id=111, channel_id=332, guild_id=3333),
    )
    session.add_all(tickets)
    session.commit()

    yield tickets

    for matched in session.query(Ticket):
        session.delete(matched)
    session.commit()


@pytest.fixture
def f_questions(session):
    """
    Fixture to insert some test Tickets.
    """
    tickets = (
        Question(id=1, text='What do pythons eat?'),
        Question(id=2, text='What is a question?'),
        Question(id=3, text='What is the meaning of life?'),
    )
    session.add_all(tickets)
    session.commit()

    yield tickets

    for matched in session.query(Question):
        session.delete(matched)
    session.commit()


@pytest.fixture
def f_testbed(f_guild_configs, f_tickets, f_questions):

    yield [f_guild_configs, f_tickets]


# Fake objects look like discord data classes
class FakeObject():
    """
    A fake class to impersonate Data Classes from discord.py
    """
    oid = 0

    @classmethod
    def next_id(cls):
        cls.oid += 1
        return '{}-{}'.format(cls.__name__, cls.oid)

    def __init__(self, name, id=None):
        if not id:
            id = self.__class__.next_id()
        self.id = id
        self.name = name

    def __repr__(self):
        return "{}: {} {}".format(self.__class__.__name__, self.id, self.name)

    def __str__(self):
        return "{}: {}".format(self.__class__.__name__, self.name)


class Server(FakeObject):
    def __init__(self, name, id=None):
        super().__init__(name, id)
        self.channels = []

    def add(self, channel):
        self.channels.append(channel)

    # def __repr__(self):
        # channels = "\n  Channels: " + ", ".join([cha.name for cha in self.channels])
        # return super().__repr__() + channels


class Channel(FakeObject):
    def __init__(self, name, *, srv=None, id=None):
        super().__init__(name, id)
        self.guild = srv
        self.all_delete_messages = []

    # def __repr__(self):
        # return super().__repr__() + ", Server: {}".format(self.server.name)

    async def delete_messages(self, messages):
        for msg in messages:
            msg.is_deleted = True
        self.all_delete_messages += messages


class Member(FakeObject):
    def __init__(self, name, roles, *, id=None):
        super().__init__(name, id)
        self.discriminator = '12345'
        self.display_name = self.name
        self.roles = roles

    @property
    def mention(self):
        return self.display_name

    # def __repr__(self):
        # roles = "Roles:  " + ", ".join([rol.name for rol in self.roles])
        # return super().__repr__() + ", Display: {} ".format(self.display_name) + roles


class Role(FakeObject):
    def __init__(self, name, srv=None, *, id=None):
        super().__init__(name, id)
        self.guild = srv

    # def __repr__(self):
        # return super().__repr__() + "\n  {}".format(self.server)


class Message(FakeObject):
    def __init__(self, content, author, srv, channel, mentions, *, id=None):
        super().__init__(None, id)
        self.author = author
        self.channel = channel
        self.content = content
        self.mentions = mentions
        self.guild = srv
        self.is_deleted = False

    # def __repr__(self):
        # return super().__repr__() + "\n  Content: {}\n  Author: {}\n  Channel: {}\n  Server: {}".format(
            # self.content, self.author, self.channel, self.server)

    @property
    def created_at(self):
        return datetime.datetime.now(datetime.timezone.utc)

    @property
    def edited_at(self):
        return datetime.datetime.now(datetime.timezone.utc)

    async def delete(self):
        self.is_deleted = True


def fake_servers():
    """ Generate fake discord servers for testing. """
    srv = Server("Gears' Hideout")
    channels = [
        Channel("feedback", srv=srv),
        Channel("live_hudson", srv=srv),
        Channel("private_dev", srv=srv)
    ]
    for cha in channels:
        srv.add(cha)

    return [srv]


def fake_msg_gears(content):
    """ Generate fake message with GearsandCogs as author. """
    srv = fake_servers()[0]
    roles = [Role('Cookie Lord', srv), Role('Hudson', srv)]
    aut = Member("GearsandCogs", roles, id="1000")
    return Message(content, aut, srv, srv.channels[1], None)


def fake_msg_newuser(content):
    """ Generate fake message with GearsandCogs as author. """
    srv = fake_servers()[0]
    roles = [Role('Hudson', srv)]
    aut = Member("newuser", roles, id="1003")
    return Message(content, aut, srv, srv.channels[1], None)


@pytest.fixture
def f_bot():
    """
    Return a mocked bot.

    Bot must have methods:
        bot.send_message
        bot.send_long_message
        bot.send_ttl_message
        bot.delete_message
        bot.emoji.fix - EmojiResolver tested elsewhere
        bot.loop.run_in_executor, None, func, *args
        bot.get_member_by_substr

    Bot must have attributes:
        bot.uptime
        bot.prefix
    """
    member = aiomock.Mock()
    member.mention = "@Gears"
    fake_bot = aiomock.AIOMock(uptime=5, prefix="!")
    fake_bot.send_message.async_return_value = fake_msg_gears("A message to send.")
    fake_bot.send_ttl_message.async_return_value = fake_msg_gears("A ttl message to send.")
    fake_bot.send_long_message.async_return_value = fake_msg_gears("A long message to send.")
    fake_bot.get_member_by_substr.return_value = member
    fake_bot.wait_for.async_return_value = None  # Whenever wait_for needed, put message here.
    fake_bot.emoji.fix = lambda x, y: x
    fake_bot.guilds = fake_servers()
    fake_bot.get_channel_by_name.return_value = 'private_dev'

    def fake_exec(_, func, *args):
        return func(*args)
    fake_bot.loop.run_in_executor.async_side_effect = fake_exec

    tick.util.BOT = fake_bot

    yield fake_bot

    tick.util.BOT = None
