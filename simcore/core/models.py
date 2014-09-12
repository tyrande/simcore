# -*- coding: utf-8 -*-
# Started by Alan
# MainTained by Alan
# Contact: alan@sinosims.com

from simcore.core.database import Srdb
from simcore.core.gol import raiseCode
import uuid, time

class RedisHash(dict):
    # Base class for models which use redis hash to store infos
    #   @attr _infoTX       Info Hash Timeout in Redis
    
    _redis = Srdb().redisPool
    _infoTX = None

    def __init__(self, id, info={}):
        # @param id:      model id
        # @param info:    Model Info
        
        self['id'] = self.id = id
        self.update(info)

    def save(self, info={}):
        # Update and Store info to Redis
        
        self.update(info)
        _infoKey = "%s:%s:info"%(self.__class__.__name__, self.id)
        d = self._redis.hmset(_infoKey, self)
        if self._infoTX: d.addCallback(lambda x: self._redis.expire(_infoKey, self._infoTX))
        d.addCallback(lambda x: self)
        return d

    def reload(self):
        d = self._redis.hgetall("%s:%s:info"%(self.__class__.__name__, self.id))
        d.addCallback(lambda hs: self.update(hs))
        d.addCallback(lambda x: self)
        return d

    def expire(self, tt=None):
        if not tt: tt = self._infoTX
        return self._redis.expire("%s:%s:info"%(self.__class__.__name__, self.id), tt)

    def _debug_(self, obj, msg=''):
        print '---- %s ----'%msg, repr(obj)
        return obj

    @classmethod
    def create(self, info={}):
        s = self(uuid.uuid1().hex)
        return s.save(info)

    @classmethod
    def findById(self, id):
        if not id: return None
        d = self._redis.hgetall("%s:%s:info"%(self.__name__, id))
        d.addCallback(lambda hs: self(id, hs) if len(hs) > 0 else None)
        return d

    @classmethod
    def findAllByIds(self, ids):
        if len(ids) == 0: return []
        getScript = "local infos = {}\n"
        getScript += "\n".join([ "infos[%d] = redis.call('hgetall',"%(i+1) + "'%s:%s:info'"%(self.__name__, ids[i]) + ")" for i in range(len(ids)) ])
        getScript += "return infos\n"
        d = self._redis.eval(getScript, [])
        d.addCallback(lambda infos: [self(i[0], dict(zip(i[1][::2], i[1][1::2]))) for i in zip(ids, infos)])
        return d

    @classmethod
    def findAllByKey(self, key):
        # Find models by a redis sort set key
        
        getScript = """
            local vals = {}
            local ids = redis.call('zrange', KEYS[1], 0, -1)
            for k, v in pairs(ids) do
                vals[k] = {v,redis.call('hgetall', KEYS[2]..':'..v..':info')}
            end
            return vals
        """
        d = self._redis.eval(getScript, [key, self.__name__])
        d.addCallback(lambda infos: [ self(i[0], dict(zip(i[1][::2], i[1][1::2]))) for i in infos ])
        return d

    @classmethod
    def reloadFromInfo(self, info):
        _id = info.get('id', None)
        if not _id: return None
        return self(_id, info)

class Session(RedisHash):
    # Session for auth the device which connected to server
    #   @key rol:  str      Role of the device
    #                           '00' -> 0x00  server
    #                           '01' -> 0x10  box
    #                           '11' -> 0x11  box news
    #                           '20' -> 0x20  phone iOS
    #                           '21' -> 0x21  phone Android
    #   @key imei: str      Device id, IMEI of Card, IMEI of Box or UDID of Phone
    #   @key chn:  str      Server Channel name
    #   
    #   @key Box:  str      Box id (only for BoxMo)
    #   @key Chip: str      Chip id (only for ChipMo)
    #   @key bid:  str      Box id (only for ChipMo and BoxMo)
    #
    #   @key User: str      User id (only for PhoneMo and PhoneNotiMo)
    #   @key ts:   int      Created at, int(time.time())
    
    _infoTX = 604800

class User(RedisHash):
    # User Model inherit from RedisHash
    #   User has many Boxes, user can control the chips in Box only if the Box pair to User
    #   @key id:            uuid.uuid1() generated, unique in whole system
    #   @key atk:  str      Apple push Token
    #   @key rol:  str      Current device Role
    #                           '20' -> 0x20  phone iOS
    #                           '21' -> 0x21  phone Android

    def newsHeart(self, ses, chn):
        setScript = """
            redis.call('hset', 'Session:'..KEYS[1]..':info', 'chn', KEYS[2])
            redis.call('zadd', 'User:'..KEYS[3]..':news', KEYS[4], KEYS[1])
            local c = {}
            local cs  = {}
            local cll = ''
            local bs = redis.call('zrange', 'User:'..KEYS[3]..':Boxes', 0, -1)
            for k, v in pairs(bs) do
                cs = redis.call('zrange', 'Box:'..v..':Chips', 0, -1)
                for p, q in pairs(cs) do
                    cll = redis.call('hget', 'Chip:'..q..':info', 'cll')
                    c[p] = redis.call('hmget', 'Call:'..tostring(cll)..':info', 'uid', 'cpid', 'oth', 'id', 'st')
                end
            end
            return c
        """
        d = self._redis.eval(setScript, [ses.id, chn, self.id, int(time.time())])
        d.addCallback(lambda cls: [ {'cid' : c[1], 'oth' : c[2], 'seq' : c[3], 'tim' : int(c[4])} for c in cls if c[0] == '' and (time.time() - int(c[4])) < 60 ])
        return d

    def addNewsSession(self, sid):
        d = self._redis.zadd("User:%s:news"%self.id, int(time.time()), sid)
        d.addCallback(lambda x: self)
        return d

    def newsSessions(self):
        # Remove dead sessions which scores are 5 minutes ago
        d = self._redis.zremrangebyscore("User:%s:news"%self.id, 0, int(time.time()) - 5*60)
        d.addCallback(lambda x: Session.findAllByKey("User:%s:news"%self.id))
        return d

    def delNewsSession(self, sid):
        d = self._redis.zrem("User:%s:news"%self.id, sid)
        d.addCallback(lambda x: self)
        return d

    def addBox(self, bid):
        addScript = """
            redis.call('zadd', 'User:'..KEYS[1]..':Boxes', KEYS[3], KEYS[2])
            redis.call('zadd', 'Box:'..KEYS[2]..':Users', KEYS[3], KEYS[1])
        """
        return self._redis.eval(addScript, [self.id, bid, int(time.time())])

    def boxes(self):
        return Box.findAllByKey("User:%s:Boxes"%self.id)

    def delBox(self, bid):
        delScript = """
            redis.call('zrem', 'User:'..KEYS[1]..':Boxes', KEYS[2])
            redis.call('zrem', 'Box:'..KEYS[2]..':Users', KEYS[1])
        """
        return self._redis.eval(delScript, [self.id, bid])

    def chips(self):
        findScript = """
            local c = {}
            local cs  = {}
            local bs = redis.call('zrange', 'User:'..KEYS[1]..':Boxes', 0, -1)
            for k, v in pairs(bs) do
                cs = redis.call('zrange', 'Box:'..v..':Chips', 0, -1)
                for p, q in pairs(cs) do
                    c[p] = {q,redis.call('hgetall', 'Chip:'..q..':info')}
                end
            end
            return c
        """
        d = self._redis.eval(findScript, [self.id])
        d.addCallback(lambda infos: [ Chip(i[0], dict(zip(i[1][::2], i[1][1::2]))) for i in infos ])
        return d

    def chip(self, cpid):
        findScript = """
            local bid = redis.call('hget', 'Chip:'..KEYS[1]..':info', 'bid')
            local sc = redis.call('zscore', 'User:'..KEYS[2]..':Boxes', bid)
            local cp = {}
            if sc ~= nil then
                cp = redis.call('hgetall', 'Chip:'..KEYS[1]..':info')
            end
            return cp
        """
        d = self._redis.eval(findScript, [cpid, self.id])
        d.addCallback(lambda hs: Chip(cpid, dict(zip(hs[::2], hs[1::2]))) if len(hs) > 0 else raiseCode(603))
        return d

    def addCard(self, cdid):
        return self._redis.zadd("User:%s:Cards"%self.id, int(time.time()), cdid)

    def cards(self):
        return Cards.findAllByKey("User:%s:Cards"%self.id)

    def delCard(self, cdid):
        return self._redis.zrem("User:%s:Cards"%self.id, cdid)

class Chip(RedisHash):
    # Chip Model inherit from RedisHash
    #   Chip can be plug into Boxes
    #   @key id:        str     IMEI of the Chip, unique in whole system
    #   @key mod:       str     Type of the Chip
    #                               'MG2639'   Insert GSM SIM Card
    #                               'MC8332'  Insert CDMA SIM Card
    #                               'SI3050'  Plugin PSTN Line
    #   @key cdid:      str     ID of the Card in the Chip, None if chip type is PSTN
    #   @key bid:       str     ID of the Box which the Chip plug in
    #
    #   @key sid:       str     Current connected Session id
    #   @key chn:       str     Current connected Server channel
    #   @key onl:       int     Chip is online or not, 0 means not online, 1 means online
    #   @key sig:       int     Sthength of the Signal, 0 ~ 9, 0 means no signal
    #
    #   @key cll:       str     Current Call id, Key don't exist or Value is '' if no current call

    def login(self, imsi, bid, ses, chn, mod):
        self.update({ 'cdid' : imsi, 'bid' : bid, 'sid' : ses.id, 'chn' : chn, 'mod' : mod })
        ses['Chip'] = self.id
        setScript = """
            redis.call('hmset', 'Chip:'..KEYS[1]..':info', 'id', KEYS[1], 'cdid', KEYS[2], 'bid', KEYS[3], 'sid', KEYS[4], 'chn', KEYS[5], 'mod', KEYS[6])
            redis.call('zadd', 'Box:'..KEYS[3]..':Chips', tonumber(KEYS[7]), KEYS[1])
            redis.call('hset', 'Session:'..KEYS[4]..':info', 'Chip', KEYS[1])
        """
        return self._redis.eval(setScript, [self.id, imsi, bid, ses.id, chn, mod, int(time.time())])

    def startCall(self, clid, uid):
        self['cll'] = clid
        setScript = """
            redis.call('hmset', 'Call:'..KEYS[1]..':info', 'id', KEYS[1], 'cdid', KEYS[2], 'cpid', KEYS[3], 'bid', KEYS[4], 'uid', KEYS[5], 'oth', KEYS[6], 'typ', '0', 'stt', '1', 'st', KEYS[7])
            redis.call('hset', 'Chip:'..KEYS[3]..':info', 'cll', KEYS[1])
        """
        d = self._redis.eval(setScript, [clid, self.get('cdid', ''), self.id, self['bid'], uid, clid[0:-16], int(time.time())]) 
        d.addCallback(lambda x: Call(clid))
        return d

    def ringing(self, clid):
        self['cll'] = clid
        setScript = """
            redis.call('hmset', 'Call:'..KEYS[1]..':info', 'id', KEYS[1], 'cdid', KEYS[2], 'cpid', KEYS[3], 'bid', KEYS[4], 'uid', '', 'oth', KEYS[5], 'typ', '1', 'stt', '1', 'st', KEYS[6])
            redis.call('hset', 'Chip:'..KEYS[3]..':info', 'cll', KEYS[1])
            local vals = {}
            local ids = redis.call('zrange', 'Box:'..KEYS[4]..':Users', 0, -1)
            for k, v in pairs(ids) do
                vals[k] = {v,redis.call('hgetall', 'User:'..v..':info')}
            end
            return vals
        """
        d = self._redis.eval(setScript, [clid, self.get('cdid', ''), self.id, self['bid'], clid[0:-16], int(time.time())])
        d.addCallback(lambda infos: ([ User(i[0], dict(zip(i[1][::2], i[1][1::2]))) for i in infos ], clid))
        return d

    def answerCall(self, clid, uid):
        return Call(clid).save({ 'uid' : uid })

    def endCall(self):
        clid = self.get('cll', None)
        if not clid: return None
        setScript = """
            redis.call('hmset', 'Call:'..KEYS[1]..':info', 'stt', KEYS[2], 'ed', KEYS[3])
            redis.call('hdel', 'Chip:'..KEYS[4]..':info', 'cll')
            redis.call('rpush', 'System:Calls', KEYS[1])
            local uid = redis.call('hget', 'Call:'..KEYS[1]..':info', 'uid')
            local vals = {}
            if uid ~= '' then
                vals[1] = {uid,redis.call('hgetall', 'User:'..uid..':info')}
            else
                local ids = redis.call('zrange', 'Box:'..KEYS[5]..':Users', 0, -1)
                for k, v in pairs(ids) do
                    vals[k] = {v,redis.call('hgetall', 'User:'..v..':info')}
                end
            end
            return vals
        """
        d = self._redis.eval(setScript, [clid, 0, int(time.time()), self.id, self['bid']])
        # d.addCallback(lambda info: (User.reloadFromInfo(dict(zip(info[::2], info[1::2]))), clid))
        d.addCallback(lambda infos: ([ User(i[0], dict(zip(i[1][::2], i[1][1::2]))) for i in infos ], clid))
        return d

    def users(self):
        return Box(self['bid']).users()

    def onl(self):
        setScript = """
            redis.call('zadd', 'Box:'..KEYS[1]..':Chips', KEYS[2], KEYS[3])
            redis.call('expire', 'Session:'..KEYS[4]..':info', KEYS[5])
        """
        return self._redis.eval(setScript, [self['bid'], int(time.time()), self.id, self['sid'], Session._infoTX])

    def call(self):
        pass

    def callingUser(self):
        cll = self.get('cll', None)
        if not cll: return None 
        findScript = """
            local uid = redis.call('hget', 'Call:'..KEYS[1]..':info', 'uid')
            return redis.call('hgetall', 'User:'..uid..':info')
        """
        d = self._redis.eval(findScript, [cll])
        d.addCallback(lambda info: User.reloadFromInfo(dict(zip(info[::2], info[1::2]))))
        return d

class Box(RedisHash):
    # Box Model inherit from RedisHash
    #   @key id:        str     IMEI of the Box, unique in whole system
    #   @key set:       int     The Box is in the setting mode or not, 0 means not in setting mode, 1 means in
    #   @key onl:       int     Box is online or not, 0 means not online, 1 means online

    def users(self):
        return User.findAllByKey("Box:%s:Users"%self.id)

    def addChip(self, cpid):
        return self._redis.zadd("Box:%s:Chips"%self.id, int(time.time()), cpid)

    def chips(self):
        return Chip.findAllByKey("Box:%s:Chips"%self.id)

    def delChip(self, cpid):
        return self._redis.zrem("Box:%s:Chips"%self.id, cpid)

class Card(RedisHash):
    # SIM Card Model inherit from RedisHash
    #   @key id:        str     IMSI of the Card
    #   @key num:       str     Number of the Card
    #   @key isp:       str     ISP(Internet Service Providers) name
    #   @key lct:       str     ISP Location
    pass

class Call(RedisHash):
    # Call Model inherit from RedisHash
    #   @key id:        str     Sequence id generated by phone or chip
    #   @key cdid:      str     ID of SIM Card, None if PSTN
    #   @key cpid:      str     ID of the Chip
    #   @key bid:       str     ID of the Box which contains the Chip
    #
    #   @key uid:       str     ID of user who uses chip
    #   @key oth:       str     Other's Phone Number
    #   @key typ:       str     Chip is host or guest, 0 means host, 1 means guest
    #   @key stt:       str     Calling status of the Card in Chip
    #   @key st:        int     Starting Timestamp
    #   @key ed:        int     Ending Timestamp
    
    _infoTX = 604800

class Message(RedisHash):
    pass
