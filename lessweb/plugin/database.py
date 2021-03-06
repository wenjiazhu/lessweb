from typing import Any, overload, List
from urllib.parse import quote

from contextlib import contextmanager
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, scoped_session
from sqlalchemy.orm.session import Session
from sqlalchemy.ext.declarative import declarative_base

from ..context import Context
from ..storage import Storage
from ..model import Model, PagedList

__all__ = ["global_data", "DbModel", "init", "processor", "create_all", "make_session", "dumpall"]


class GlobalData:
    db_session_maker: Any
    db_engine: Any
    autocommit: bool


class DatabaseCtx(Context):
    db : Session


global_data = GlobalData()


def _db_model_storage(self):
    return Storage({k: v for k, v in self.__dict__.items() if k[0] != '_'})


def _db_model_setall(self, *mapping, **kwargs):
    if mapping:
        _db_model_setall(self, **mapping[0])
    for k, v in kwargs.items():
        if k[0] != '_':
            try:
                setattr(self, k, v)
            except AttributeError:  # property without setter
                pass


def _db_model_copy(self, *mapping, **kwargs):
    ret = self.__class__()
    ret.setall(**self.storage())
    if mapping:
        ret.setall(**mapping[0])
    ret.setall(**kwargs)
    return ret


DbModel = declarative_base()
DbModel.storage = _db_model_storage
DbModel.setall = _db_model_setall
DbModel.copy = _db_model_copy
DbModel.__eq__ = lambda self, other: self is other or (type(self) == type(other) and self.items() == other.items())
DbModel.__repr__ = lambda self: '<DbModel ' + repr(self.items()) + '>'


class DumpAllDbModel:
    def __ror__(self, other) -> List:
        if other is None:
            return []
        return [x.dump() for x in other]


dumpall = DumpAllDbModel()


class DumpPageModel:
    def __init__(self, pageNo, pageSize):
        if pageNo < 1: pageNo = 1
        assert pageSize >= 1, pageSize
        self.pageNo = pageNo
        self.pageSize = pageSize

    def __ror__(self, other) -> PagedList:
        pagelist = PagedList()
        pagelist.pageNo = self.pageNo
        pagelist.pageSize = self.pageSize

        if other is None:
            return pagelist

        totalNum = other.count()
        dbitems = other.offset((self.pageNo - 1) * self.pageSize).limit(self.pageSize).all()

        if totalNum > 0:
            pagelist.list.extend(x.dump() for x in dbitems)
            pagelist.totalNum = totalNum
        return pagelist


def dumppage(pageNo, pageSize):
    return DumpPageModel(pageNo, pageSize)


class DumpOneModel:
    def __ror__(self, other):
        if other is None:
            return None
        return other.dump()


dumpone = DumpOneModel()


@overload
def init(*, dburi, echo=True, autoflush=True, autocommit=False): ...
@overload
def init(*, protocol, username, password, host, port:int, entity, echo=True, autoflush=True, autocommit=False): ...


def init(*, protocol=None, username=None, password=None, host=None, port:int=None, entity=None, dburi=None,
         echo:bool=True, autoflush=True, autocommit=False):
    """
    Database requirements:
        sqlalchemy

    Drivers requirements:
        protocol = mysql+mysqlconnector (default-port = 3306)
            mysql-connector==2.1.4
        protocol = postgresql (default-port = 5432)
            psycopg2

    """
    if dburi:
        engine = create_engine(dburi)
    else:
        engine = create_engine(
            '{protocol}://{username}:{password}@{host}:{port}/{entity}'.format(
                protocol=protocol, username=quote(username), password=quote(password),
                host=host, port=port, entity=entity
            ),
            pool_recycle=3600
        )
    engine.echo = echo
    global_data.db_session_maker = scoped_session(sessionmaker(
        autoflush=autoflush, autocommit=autocommit, bind=engine))
    global_data.db_engine = engine
    global_data.autocommit = autocommit


def processor(ctx: DatabaseCtx):
    try:
        ctx.db = global_data.db_session_maker()
        if global_data.autocommit:
            with ctx.db.begin():
                return ctx()
        else:
            return ctx()
    except:
        ctx.db.rollback()
        raise
    finally:
        ctx.db.close()


def create_all(*DbModelClass):
    """
    init(...)
    create_all(DbUser, DbOrder, ...)
    create_all([DbUser, DbOrder, ...])
    """
    if len(DbModelClass) == 1 and isinstance(DbModelClass[0], (list, tuple)):
        return create_all(*DbModelClass[0])

    for db_class in DbModelClass:
        db_class.metadata.create_all(global_data.db_engine)


@contextmanager
def make_session():
    session = None
    try:
        session = global_data.db_session_maker()
        yield session
    except:
        session.rollback()
        raise
    finally:
        session.close()

"""
==== Tutorial: SQLALCHEMY USAGE ====

#DEFINING MODELS
from lessweb.plugin.database import DbModel 
from sqlalchemy import Column, Integer, Numeric, String, Text, Enum
class UserInfo(DbModel):
    __tablename__ = 'tbl_cookies'
    cookie_id = Column(Integer, primary_key=True)
    cookie_name = Column(String(50), index=True)
    cookie_recipe_url = Column(String(255))
    cookie_sku = Column(String(55))
    quantity = Column(Integer())
    unit_cost = Column(Numeric(12, 2))
    category = Column(Enum(Category))
    intro = Column(Text)

#CREATE TABLE
from lessweb.plugin.database import create_all
index.py: create_all(DbUser)  #表已存在则忽略，不会清空数据或改变表结构。可以用drop_all()删表。但无法ALTER表结构

#INSERT
##ADD A COOKIE
cc_cookie = Cookie(cookie_name='chip', cookie_recipe_url='http://some.me', cookie_sku='CC01', quantity=12, unit_cost=0.50, category=Category.A, intro='')
ctx.db.add(cc_cookie)
ctx.db.commit()
print(cc_cookie.cookie_id)  #output: 1

session = ctx.db

#QUERY
##ALL THE COOKIES
cookies = session.query(Cookie).all()
print(cookies)  #output:  [Cookie(cookie_name='chip',...), Cookie(...), Cookie(...)]

for cookie in session.query(Cookie):
    print(cookie)  #output: Cookie(...)

##PARTICULAR ATTRIBUTES
print(session.query(Cookie.cookie_name, Cookie.quantity).first())  #output: ('chip', 12)

##ORDER BY
for cookie in session.query(Cookie).order_by(Cookie.quantity):
    print('{:3} - {}'.format(cookie.quantity, cookie.cookie_name))  #output:  12 - chip

##DECENDING
from sqlalchemy import desc
for cookie in session.query(Cookie).order_by(desc(Cookie.quantity)):
    print('{:3} - {}'.format(cookie.quantity, cookie.cookie_name))

##LIMITING
query = session.query(Cookie).order_by(Cookie.quantity).limit(2)
print([result.cookie_name for result in query])  #output: ['chip', 'butter']

##DATABASE FUNCTIONS
from sqlalchemy import func
inv_count = session.query(func.sum(Cookie.quantity)).scalar()  #scalar() get the first element whatever that happens to be assumed column
print(inv_count)  #output: 136

rec_count = session.query(func.count(Cookie.cookie_name)).first()
print(rec_count)  #output: (3, 0)

##LABELING
rec_count = session.query(func.count(Cookie.cookie_name).label('inventory_count')).first()
print(rec_count.keys())  #output: ['inventory_count']
print(rec_count.inventory_count)  #output: 3

##FILTER_BY
record = session.query(Cookie).filter_by(cookie_name = 'chip').first()
print(record)  #output: Cookie(cookie_name="chip",...)
record = session.query(Cookie).filter_by(Cookie.cookie_name == 'chip').first()

#CLAUSEELEMENTS
query = session.query(Cookie).filter(Cookie.cookie_name.like('%chip%'))

##CLAUSEELEMENTS METHODS
* between(cleft, cright) - Find where the column is between cleft and cright
* distinct() - Find only unique values for column* in_([list]) - Find where the column is in the list
* is_(None) - Find where the column is None (commonly used for Null checks with None)
* contains('string') - Find where the column has 'string' in it (Case-sensitve)
* endswith('string')
* startswith('string')
* ilike('string') - Find where the column is link 'string'

##OPERATORS
from sqlalchemy import cast
query = session.query(Cookie.cookie_name,
    cast(
        (Cookie.quantity * Cookie.unit_cost), Numeric(12,2)
    ).label('inv_cost'))
for result in query:
    print('{} - {}'.format(result.cookie_name, result.inv_cost))  #output: chip - 6.00

##CONJUNCTIONS
from sqlalchemy import and_, or_, not_
query = session.query(Cookie).filter(
    or_(
        Cookie.quantity.between(10, 50),
        Cookie.cookie_name.contains('chip')
    )
)

#UPDATE
query = session.query(Cookie)
cc_cookie = query.filter(Cookie.cookie_name == "chip").first()
cc_cookie.quantity = cc_cookie.quantity + 120
session.commit()
print(cc_cookie.quantity)  #output: 132

#DELETE
query = session.query(Cookie)
query = query.filter(Cookie.cookie_name == "butter")

dcc_cookie = query.one()
session.delete(dcc_cookie)
session.commit()
dcc_cookie = query.first()
print(dcc_cookie)  #output: None

##USING RELATIONSHIPS IN QUERIES
query = session.query(Order.order_id, User.username, User.phone, Cookie.cookie_name, LineItem.quantity, LineItem.extended_cost)
query = query.join(User).join(LineItem).join(Cookie)
results = query.filter(User.username == 'cookiemon').all()
print(results)  #output: [(1, 'cookiemon', '111-1111', 'chip', ...), (1, 'cookiemon', '111-1111', 'raisin', ...)]

##ANOTHER EXAMPLE
query = session.query(User.username, func.count(Order.order_id))
query = query.outerjoin(Order).group_by(User.username)
for row in query:
    print(row)  #output: ('cookiemon', 1)

#EXECUTE SQL
result = session.execute('SELECT * FROM my_table WHERE my_column = :val', {'val': 5})
for row in result:
    #type(row) is RowProxy, not tuple
    print row  #output: (493L, '张三', '13880775240', 11L, '渝A82222', 0L, 1)

##PRIMARY KEY AFTER INSERT
result = session.execute('insert into user (lpn, carModel) values(:lpn, :model)', {'lpn':'渝B12321', 'model': '00001'})
print result.lastrowid  #output: 9
print session.commit()  #output: None
print [result.lastrowid]  #output: [9L]
#参考: http://docs.sqlalchemy.org/en/latest/core/connections.html
    
##JOIN WITHOUT RELATIONSHIP
class UserInfo(Base):
    __tablename__ = 'user'
    id = Column(Integer, primary_key=True)
    lpn = Column(String(45))

class Company(Base):
    __tablename__ = 'company'
    id = Column(Integer, primary_key=True)
    companyName = Column(String(50))

query = session.query(UserInfo.id, UserInfo.lpn, Company.companyName).join(Company, UserInfo.id==Company.id)
for row in query:
    print row[0], row[1], row[2]

sql: SELECT user.id AS user_id, user.lpn AS use_lpn, company.`companyName` AS `company_companyName` FROM user INNER JOIN company ON user.id = company.id
output: 
  1 川A12345 平安
  2 川A77777 人保
#注意: .query()中出现的第一个表名为主查询表，所以.join()第一个参数应该为副查询表，否则会执行出错
#参考: http://docs.sqlalchemy.org/en/latest/orm/query.html

"""