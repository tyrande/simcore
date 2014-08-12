# -*- coding: utf-8 -*-
# Started by Alan
# MainTained by Alan
# Contact: alan@sinosims.com

from simcore.core.database import Srdb
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
        d.addCallback(lambda hash: self.update(hash))
        d.addCallback(lambda x: self)
        return d

    @classmethod
    def create(self, info={}):
        s = self(uuid.uuid1().hex)
        return s.save(info)

    @classmethod
    def findById(self, id):
        d = self._redis.hgetall("%s:%s:info"%(self.__name__, id))
        d.addCallback(lambda hash: self(id, hash))
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
    #   @key bid:  str      Box id (only for Card and Box)
    #   @key cid:  str      Card id (only for Card)
    #
    #   @key uid:  str      User id (only for Phone)
    #   @key ts:   int      Created at, int(time.time())
    
    _infoTX = 604800

class User(RedisHash):
    # User Model inherit from RedisHash
    #   User has many Boxes, user can control the chips in Box only if the Box pair to User
    #   @key id:                uuid.uuid1() generated, unique in whole system
    #   @key atk:  str          Apple push Token

    def addNewsSession(self, sid):
        d = self._redis.zadd("User:%s:news"%self.id, time.time(), sid)
        d.addCallback(lambda x: self)
        return d

    def newsSessions(self):
        return Session.findAllByKey("User:%s:news"%self.id)

    def delNewsSession(self, sid):
        d = self._redis.zrem("User:%s:news"%self.id, sid)
        d.addCallback(lambda x: self)
        return d

    def addBox(self, bid):
        pass

    def boxes(self):
        pass

    def delBox(self, bid):
        pass

    def chips(self):
        # return Chip.findAllByKey("User:%s:list:Chip"%self.id)
        d = self._redis.zrange("U:%s:list:C"%self.id, 0, -1)
        d.addCallback(lambda cids: Chip.findAllByIds(['460025125862622']))
        return d

    def chip(self, cpid):
        return Chip('460025125862622').reload()

    def addCard(self, cdid):
        pass

    def cards(self):
        return []

    def delCard(self, cdid):
        pass

class Chip(RedisHash):
    # Chip Model inherit from RedisHash
    #   Chip can be plug into Boxes
    #   @key id:        str     IMEI of the Chip, unique in whole system
    #   @key typ:       str     Type of the Chip
    #                               'GSM'   Insert GSM SIM Card
    #                               'CDMA'  Insert CDMA SIM Card
    #                               'PSTN'  Plugin PSTN Line
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
        d.addCallback(lambda x: cl)
        return d

    def users(self):
        # return User.findAllByKey("Chip:%s:list:User"%self.id)
        d = self._redis.zrange("C:%s:list:U"%self.id, 0, -1)
        d.addCallback(lambda uids: User.findAllByIds(['0f9c509afcd711e383b700163e0212e4']))
        d.addCallback(lambda s: self.pp(s))
        return d

    def pp(self, s):
        print repr(s)
        return s

    def call(self):
        pass

class Box(RedisHash):
    # Box Model inherit from RedisHash
    #   @key id:        str     IMEI of the Box, unique in whole system
    #   @key set:       int     The Box is in the setting mode or not, 0 means not in setting mode, 1 means in
    #   @key onl:       int     Box is online or not, 0 means not online, 1 means online

    def chips(self):
        return []

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
