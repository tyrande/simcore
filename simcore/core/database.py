from simcore.libs.txredisapi import lazyConnectionPool

class Srdb(object):
    def __new__(cls, *args, **kw):
        if not hasattr(cls, '_instance'):
            orig = super(Srdb, cls)
            cls._instance = orig.__new__(cls, *args, **kw)
        return cls._instance

    def initRedisPool(self, host, port, db):
        self.host, self.port, self.db = host, port, db
        self.redisPool = lazyConnectionPool(host, port, db)

class SrPushdb(object):
    def __new__(cls, *args, **kw):
        if not hasattr(cls, '_instance'):
            orig = super(SrPushdb, cls)
            cls._instance = orig.__new__(cls, *args, **kw)
        return cls._instance

    def initRedisPool(self, host, port, db):
        self.host, self.port, self.db = host, port, db
        self.redisPool = lazyConnectionPool(host, port, db)
