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

    @classmethod
    def create(self, info={}):
        s = self(uuid.uuid1().hex)
        return s.save(info)

    @classmethod
    def findById(self, id):
        d = self._redis.hgetall("%s:%s:info"%(self.__name__, id))
        d.addCallback(lambda hs: self(id, hs) if len(hs) > 0 else None)
        return d

    @classmethod
    def findAllByIds(self, ids):
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

    def addNewsSession(self, sid):
        d = self._redis.zadd("User:%s:news"%self.id, int(time.time()), sid)
        d.addCallback(lambda x: self)
        return d

    def newsSessions(self):
        return Session.findAllByKey("User:%s:news"%self.id)

    def delNewsSession(self, sid):
        d = self._redis.zrem("User:%s:news"%self.id, sid)
        d.addCallback(lambda x: self)
        return d

    def addBox(self, bid):
        addScript = """
            redis.call('zadd', 'User:'..KEYS[1]..':'..'Boxes', KEYS[3], KEYS[2])
            redis.call('zadd', 'Box:'..KEYS[2]..':'..'Users', KEYS[3], KEYS[1])
        """
        return self._redis.eval(addScript, [self.id, bid, int(time.time())])

    def boxes(self):
        return Box.findAllByKey("User:%s:Boxes"%self.id)

    def delBox(self, bid):
        delScript = """
            redis.call('zrem', 'User:'..KEYS[1]..':'..'Boxes', KEYS[2])
            redis.call('zrem', 'Box:'..KEYS[2]..':'..'Users', KEYS[1])
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
        # d = self.boxes()
        # d.addCallback(lambda bs: [ {b.id : b.chips()} for b in bs ])
        d = self._redis.eval(findScript, [self.id])
        d.addCallback(lambda infos: [ Chip(i[0], dict(zip(i[1][::2], i[1][1::2]))) for i in infos ])
        return d
        # return Chip.findAllByKey("User:%s:Chips"%self.id)
        # d = self._redis.zrange("U:%s:list:C"%self.id, 0, -1)
        # d.addCallback(lambda cids: Chip.findAllByIds(['460025125862622']))
        # return d

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
        d.addCallback(lambda hs: dict(zip(hs[::2], hs[1::2])))
        d.addCallback(lambda hs: Chip(cpid, hs) if len(hs) > 0 else raiseCode(603))
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

    def startCall(self, clid, uid, oth, typ):
        cl = Call(clid)
        d = cl.save({ 'cdid' : self.get('cdid', ''), 'cpid' : self.id, 'bid' : self['bid'], 'uid' : uid, 'oth' : oth, 'typ' : typ, 'stt' : 1, 'st' : int(time.time()) })
        d.addCallback(lambda c: self.save({ 'cll' : cl.id }))
        d.addCallback(lambda x: cl)
        return d

    def answerCall(self, clid, uid):
        cl = Call(clid)
        d = cl.save({ 'uid' : uid })
        d.addCallback(lambda c: cl)
        return d

    def endCall(self, clid):
        cl = Call(clid)
        d = cl.save({ 'stt' : 0, 'ed' : int(time.time()) })
        d.addCallback(lambda c: self.save({ 'cll' : '' }))
        d.addCallback(lambda c: self._redis.rpush('System:Calls', cl.id))
        d.addCallback(lambda x: cl)
        return d

    def users(self):
        return Box(self['bid']).users()
        # d = self._redis.zrange("C:%s:list:U"%self.id, 0, -1)
        # d.addCallback(lambda uids: User.findAllByIds(['0f9c509afcd711e383b700163e0212e4']))
        # d.addCallback(lambda s: self.pp(s))
        # return d

    def call(self):
        pass

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
