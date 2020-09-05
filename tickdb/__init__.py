"""
All database related code resides under this module.
Only one rule, no sql text.

Useful Documentation
--------------------
ORM  tutorial:
    http://docs.sqlalchemy.org/en/latest/orm/tutorial.html
Relationships:
    http://docs.sqlalchemy.org/en/latest/orm/basic_relationships.html
Relationship backrefs:
    http://docs.sqlalchemy.org/en/latest/orm/backref.html#relationships-backref
"""
import logging
import os
import sys

import sqlalchemy
import sqlalchemy.event
import sqlalchemy.exc
import sqlalchemy.orm

import tick.util

# Old engine, just in case
# engine = sqlalchemy.create_engine('sqlite://', echo=False)

MYSQL_SPEC = 'mysql+pymysql://{user}:{pass}@{host}/{db}?charset=utf8mb4'
CREDS = tick.util.get_config('dbs', 'main')
CREDS['db'] = 'tick'

TEST_DB = False
if 'pytest' in sys.modules:
    CREDS['db'] = 'test'
    TEST_DB = True

engine = sqlalchemy.create_engine(MYSQL_SPEC.format(**CREDS), echo=False, pool_recycle=3600)
Session = sqlalchemy.orm.sessionmaker(bind=engine)
logging.getLogger(__name__).info('Main Engine Selected: %s', engine)

CREDS = None


def fresh_sessionmaker(db=None):
    """
    If in another process, create a new connection setup for new sessions.

    args:
        db: The database to select with mysql, by default COG_TOKEN.
    """
    creds = tick.util.get_config('dbs', 'main')
    if not db:
        db = os.environ.get('COG_TOKEN', 'dev')
    creds['db'] = db

    eng = sqlalchemy.create_engine(MYSQL_SPEC.format(**creds), echo=False, pool_recycle=3600)
    return sqlalchemy.orm.sessionmaker(bind=eng)