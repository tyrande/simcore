# -*- coding: utf-8 -*-
# Started by Alan
# MainTained by Alan
# Contact: alan@sinosims.com

from simcore.core.database import Srdb
from simcore.core.gol import raiseCode
from messaging.sms import SmsDeliver, SmsSubmit
from simisp import phoneNum
import uuid, time, random, base64

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
        _script = "local infos = {}\n"
        _script += "\n".join([ "infos[%d] = redis.call('hgetall',"%(i+1) + "'%s:%s:info'"%(self.__name__, ids[i]) + ")" for i in range(len(ids)) ])
        _script += "return infos\n"
        d = self._redis.eval(_script, [])
        d.addCallback(lambda infos: [self(i[0], dict(zip(i[1][::2], i[1][1::2]))) for i in zip(ids, infos)])
        return d

    @classmethod
    def findAllByKey(self, key):
        # Find models by a redis sort set key
        
        _script = """
            local vals = {}
            local ids = redis.call('zrange', KEYS[1], 0, -1)
            for k, v in pairs(ids) do
                vals[k] = {v,redis.call('hgetall', KEYS[2]..':'..v..':info')}
            end
            return vals
        """
        d = self._redis.eval(_script, [key, self.__name__])
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
    #   @key bv:   int      Box Status change timestemp
    #
    # Redis Key
    #   Session:<id>:info      hash
    
    _infoTX = 604800

class User(RedisHash):
    # User Model inherit from RedisHash
    #   User has many Boxes, user can control the chips in Box only if the Box pair to User
    #   @key id:            uuid.uuid1() generated, unique in whole system
    #
    # Redis Key
    #   User:<id>:info                  hash
    #   User:<id>:news                  sortset
    #   User:<id>:Boxes                 sortset
    #   User:<id>:Cards                 hash
    #   User:<id>:oths                  sortset
    #   User:<id>:oth:<oth>:voices      sortset
    #   User:<id>:othsms                sortset
    #   User:<id>:othsms:<oth>:sms      sortset
    #   User:<id>:atk                   hash

    def newsHeart(self, ses, chn):
        _script = """
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
                    if cll then c[p] = redis.call('hmget', 'Call:'..tostring(cll)..':info', 'uid', 'cpid', 'oth', 'loc', 'id', 'st', 'ed') end
                end
            end
            return c
        """
        d = self._redis.eval(_script, [ses.id, chn, self.id, int(time.time())])
        d.addCallback(lambda cls: [ {'cid' : c[1], 'oth' : c[2], 'seq' : c[4], 'loc' : c[3], 'tim' : int(c[5])} 
                                    for c in cls 
                                    if c[0] == '' and (not c[6]) and (time.time() - int(c[5])) < 60 ])
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
        _script = """
            redis.call('zadd', 'User:'..KEYS[1]..':Boxes', KEYS[3], KEYS[2])
            redis.call('zadd', 'Box:'..KEYS[2]..':Users', KEYS[3], KEYS[1])
        """
        return self._redis.eval(_script, [self.id, bid, int(time.time())])

    def boxes(self):
        return Box.findAllByKey("User:%s:Boxes"%self.id)

    def delBox(self, bid):
        _script = """
            redis.call('zrem', 'User:'..KEYS[1]..':Boxes', KEYS[2])
            redis.call('zrem', 'Box:'..KEYS[2]..':Users', KEYS[1])
        """
        return self._redis.eval(_script, [self.id, bid])

    def chips(self):
        _script = """
            local c = {}
            local cs  = {}
            local bs = redis.call('zrange', 'User:'..KEYS[1]..':Boxes', 0, -1)
            for k, v in pairs(bs) do
                cs = redis.call('zrange', 'Box:'..v..':Chips', 0, -1)
                for p, q in pairs(cs) do
                    table.insert(c, {q,redis.call('hgetall', 'Chip:'..q..':info')})
                end
            end
            return c
        """
        d = self._redis.eval(_script, [self.id])
        d.addCallback(lambda infos: [ Chip(i[0], dict(zip(i[1][::2], i[1][1::2]))) for i in infos ])
        return d

    def chip(self, cpid):
        _script = """
            local bid = redis.call('hget', 'Chip:'..KEYS[1]..':info', 'bid')
            local sc = redis.call('zscore', 'User:'..KEYS[2]..':Boxes', bid)
            local cp = {}
            if sc ~= nil then
                cp = redis.call('hgetall', 'Chip:'..KEYS[1]..':info')
            end
            return cp
        """
        d = self._redis.eval(_script, [cpid, self.id])
        d.addCallback(lambda hs: Chip(cpid, dict(zip(hs[::2], hs[1::2]))) if len(hs) > 0 else raiseCode(603))
        return d

    def sendSMS(self, cpid, oth, msg):
        sms = SmsSubmit(oth, msg)
        pdu = sms.to_pdu()[0]
        now = int(time.time()*1000)
        (fnum, inum, loc) = phoneNum.loads(oth)
        smsid = "%s%d%d"%(inum, now, random.randrange(100, 999))
        now = now/1000
        _script = """
            local bid = redis.call('hget', 'Chip:'..KEYS[1]..':info', 'bid')
            local sc = redis.call('zscore', 'User:'..KEYS[2]..':Boxes', bid)
            local cp = {}
            if sc ~= nil then
                cp = redis.call('hmget', 'Chip:'..KEYS[1]..':info', 'id', 'mod', 'cdid', 'bid', 'sid', 'chn')
                redis.call('hmset', 'Sms:'..KEYS[3]..':info', 'id', KEYS[3], 'cpid', cp[1], 'cdid', cp[3], 'bid', cp[4], 'uid', KEYS[2], 'oth', KEYS[4], 'fnum', KEYS[5], 'inum', KEYS[6], 'loc', KEYS[7], 'msg', KEYS[8], 'st', KEYS[9])
            end
            return cp
        """
        d = self._redis.eval(_script, [cpid, self.id, smsid, oth, fnum, inum, loc, base64.b64encode(msg.encode('utf8')), now])
        d.addCallback(lambda hs: [Chip(cpid, dict(zip(['id', 'mod', 'cdid', 'bid', 'sid', 'chn'], hs))), [smsid, pdu.length, pdu.pdu]] if len(hs) > 0 else raiseCode(603))
        return d

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
    #   @key lvl:       int     Chip's level on the top of the Box
    #   @key sig:       int     Sthength of the Signal, 0 ~ 9, 0 means no signal
    #
    #   @key cll:       str     Current Call id, Key don't exist or Value is '' if no current call
    #
    # Redis key
    #   Chip:<id>:info          hash

    def login(self, imsi, bid, ses, chn, mod, icc, lvl):
        self.update({ 'cdid' : imsi, 'bid' : bid, 'sid' : ses.id, 'chn' : chn, 'mod' : mod, 'lvl' : lvl })
        ses['Chip'] = self.id
        isph = {'00' : 11, '02' : 11, '07' : 11, '01' : 12, '06' : 12, '20' : 12, '03' : 13, '05' : 13}
        isp = 1 if mod == 'SI3050' else isph.get(imsi[3:5], 0)
        _script = """
            redis.call('hmset', 'Chip:'..KEYS[1]..':info', 'id', KEYS[1], 'cdid', KEYS[2], 'bid', KEYS[3], 'sid', KEYS[4], 'chn', KEYS[5], 'mod', KEYS[6], 'lvl', KEYS[9])
            redis.call('zadd', 'Box:'..KEYS[3]..':Chips', tonumber(KEYS[10]), KEYS[1])
            redis.call('hset', 'Session:'..KEYS[4]..':info', 'Chip', KEYS[1])
            local us = redis.call('zrange', 'Box:'..KEYS[3]..':Users', 0, -1)
            for k, v in pairs(us) do
                redis.call('hset', 'User:'..v..':info', 'bv', KEYS[10])
                redis.call('hsetnx', 'User:'..v..':Cards', KEYS[2], '')
            end
            local ni = redis.call('hexists', 'Card:'..KEYS[2]..':info', 'num')
            if ni == 0 then redis.call('hmset', 'Card:'..KEYS[2]..':info', 'imsi', KEYS[2], 'mod', KEYS[6], 'icc', KEYS[7], 'isp', KEYS[8]) end
            return ni
        """
        return self._redis.eval(_script, [self.id, imsi, bid, ses.id, chn, mod, icc, isp, lvl, int(time.time())])

    def startCall(self, clid, uid):
        self['cll'] = clid
        oth = clid[0:-16]
        (fnum, inum, loc) = phoneNum.loads(oth)
        _script = """
            redis.call('hmset', 'Call:'..KEYS[1]..':info', 'id', KEYS[1], 'cdid', KEYS[2], 'cpid', KEYS[3], 'bid', KEYS[4], 'uid', KEYS[5], 'oth', KEYS[6], 'fnum', KEYS[7], 'inum', KEYS[8], 'loc', KEYS[9], 'typ', '0', 'stt', '1', 'st', KEYS[10])
            redis.call('hset', 'Chip:'..KEYS[3]..':info', 'cll', KEYS[1])
        """
        d = self._redis.eval(_script, [clid, self.get('cdid', ''), self.id, self['bid'], uid, oth, fnum, inum, loc, int(time.time())]) 
        d.addCallback(lambda x: Call(clid))
        return d

    def ringing(self, clid):
        self['cll'] = clid
        oth = clid[0:-16]
        (fnum, inum, loc) = phoneNum.loads(oth)
        _script = """
            redis.call('hmset', 'Call:'..KEYS[1]..':info', 'id', KEYS[1], 'cdid', KEYS[2], 'cpid', KEYS[3], 'bid', KEYS[4], 'uid', '', 'oth', KEYS[5], 'fnum', KEYS[6], 'inum', KEYS[7], 'loc', KEYS[8], 'typ', '1', 'stt', '1', 'st', KEYS[9])
            redis.call('hset', 'Chip:'..KEYS[3]..':info', 'cll', KEYS[1])
            local ids = redis.call('zrange', 'Box:'..KEYS[4]..':Users', 0, -1)
            local ses = {}
            local atk = ''
            for k, v in pairs(ids) do
                for m,n in pairs(redis.call('hvals', 'User:'..v..':atk')) do
                    atk = atk..n..','
                end
                redis.call('zremrangebyscore', 'User:'..v..':news', 0, KEYS[9] - 5*60)
                for p,q in pairs(redis.call('zrange', 'User:'..v..':news', 0, -1)) do
                    table.insert(ses, {q,redis.call('hget', 'Session:'..q..':info', 'chn')})
                end
            end
            if atk ~= '' then redis.call('rpush', 'System:Ring', atk..KEYS[5]..','..KEYS[9]) end
            return ses
        """
        d = self._redis.eval(_script, [clid, self.get('cdid', ''), self.id, self['bid'], oth, fnum, inum, loc, int(time.time())])
        d.addCallback(lambda sa: (sa, clid))
        return d

    def answerCall(self, clid, uid):
        return Call(clid).save({ 'uid' : uid })

    def changeCall(self):
        clid = self.get('cll', None)
        if not clid: return None 
        _script = """
            local uid = redis.call('hget', 'Call:'..KEYS[1]..':info', 'uid')
            local ses = {}
            redis.call('zremrangebyscore', 'User:'..uid..':news', 0, KEYS[2] - 5*60)
            for k,v in pairs(redis.call('zrange', 'User:'..uid..':news', 0, -1)) do
                table.insert(ses, {v,redis.call('hget', 'Session:'..v..':info', 'chn')})
            end
            return ses
        """
        d = self._redis.eval(_script, [clid, int(time.time())])
        d.addCallback(lambda sa: (sa, clid))
        return d

    def endCall(self):
        clid = self.get('cll', None)
        if not clid: return None
        _script = """
            redis.call('hmset', 'Call:'..KEYS[1]..':info', 'stt', KEYS[2], 'ed', KEYS[3])
            redis.call('hdel', 'Chip:'..KEYS[4]..':info', 'cll')
            redis.call('rpush', 'System:Calls', KEYS[1])
            local uid = redis.call('hget', 'Call:'..KEYS[1]..':info', 'uid')
            local ids = {uid}
            if uid == '' then ids = redis.call('zrange', 'Box:'..KEYS[5]..':Users', 0, -1) end
            local ses = {}
            for k, v in pairs(ids) do
                redis.call('zremrangebyscore', 'User:'..v..':news', 0, KEYS[3] - 5*60)
                for p,q in pairs(redis.call('zrange', 'User:'..v..':news', 0, -1)) do
                    table.insert(ses, {q,redis.call('hget', 'Session:'..q..':info', 'chn')})
                end
            end
            return ses
        """
        d = self._redis.eval(_script, [clid, 0, int(time.time()), self.id, self['bid']])
        d.addCallback(lambda sa: (sa, clid))
        return d

        # d = self._redis.zremrangebyscore("User:%s:news"%self.id, 0, int(time.time()) - 5*60)
        # d.addCallback(lambda x: Session.findAllByKey("User:%s:news"%self.id))

    def sendSMSOver(self, smsid):
        _script = """
            redis.call('hmset', 'Sms:'..KEYS[1]..':info', 'ed', KEYS[2])
            redis.call('rpush', 'System:Sms', KEYS[1])
        """
        return self._redis.eval(_script, [smsid, int(time.time())])

    def smsing(self, pdu):
        smsid = uuid.uuid1().hex
        sms = SmsDeliver(pdu).data
        tim = int(time.mktime(sms['date'].timetuple()))
        now = int(time.time()*1000)
        (fnum, inum, loc) = phoneNum.loads(sms['csca'])
        smsid = "%s%d%d"%(inum[-20:], now, random.randrange(100, 999))
        now = now/1000
        msg = base64.b64encode(sms['text'].encode('utf8'))
        _script = """
            redis.call('hmset', 'Sms:'..KEYS[1]..':info', 'id', KEYS[1], 'cpid', KEYS[2], 'cdid', KEYS[3], 'bid', KEYS[4], 'oth', KEYS[5], 'fnum', KEYS[6], 'inum', KEYS[7], 'loc', KEYS[8], 'msg', KEYS[9], 'st', KEYS[10], 'ed', KEYS[11])
            redis.call('rpush', 'System:Sms', KEYS[1])
            local ids = redis.call('zrange', 'Box:'..KEYS[4]..':Users', 0, -1)
            local ses = {}
            local atk = ''
            for k, v in pairs(ids) do
                for m,n in pairs(redis.call('hvals', 'User:'..v..':atk')) do
                    atk = atk..n..','
                end
                redis.call('zremrangebyscore', 'User:'..v..':news', 0, KEYS[10] - 5*60)
                for p,q in pairs(redis.call('zrange', 'User:'..v..':news', 0, -1)) do
                    table.insert(ses, {q,redis.call('hget', 'Session:'..q..':info', 'chn')})
                end
            end
            if atk ~= '' then redis.call('rpush', 'System:Smsing', atk..KEYS[1]) end
            return ses
        """
        d = self._redis.eval(_script, [smsid, self.id, self['cdid'], self['bid'], sms['csca'], fnum, inum, loc, msg, tim, now ])
        d.addCallback(lambda sa: (sa, [sms['csca'], sms['text'], tim]))
        return d

    def users(self):
        return Box(self['bid']).users()

    def onl(self):
        _script = """
            redis.call('zadd', 'Box:'..KEYS[1]..':Chips', KEYS[2], KEYS[3])
            redis.call('expire', 'Session:'..KEYS[4]..':info', KEYS[5])
        """
        return self._redis.eval(_script, [self['bid'], int(time.time()), self.id, self['sid'], Session._infoTX])

    def call(self):
        pass

    def callingUser(self):
        cll = self.get('cll', None)
        if not cll: return None 
        _script = """
            local uid = redis.call('hget', 'Call:'..KEYS[1]..':info', 'uid')
            return redis.call('hgetall', 'User:'..uid..':info')
        """
        d = self._redis.eval(_script, [cll])
        d.addCallback(lambda info: User.reloadFromInfo(dict(zip(info[::2], info[1::2]))))
        return d

    def setNum(self, num):
        return self._redis.hset('Card:%s:info'%self['cdid'], 'num', num)

    def fineOth(self, oth):
        if self['mod'] == 'SI3050': oth = oth + "#"
        return (self, oth)

class Box(RedisHash):
    # Box Model inherit from RedisHash
    #   @key id:        str     IMEI of the Box, unique in whole system
    #   @key set:       int     The Box is in the setting mode or not, 0 means not in setting mode, 1 means in
    #   @key onl:       int     Box last http connection timestemp
    #
    # Redis key
    #   Box:<id>:info           hash
    #   Box:<id>:Users          sortset
    #   Box:<id>:Chips          sortset

    def users(self):
        return User.findAllByKey("Box:%s:Users"%self.id)

    def addChip(self, cpid):
        return self._redis.zadd("Box:%s:Chips"%self.id, int(time.time()), cpid)

    def chips(self):
        return Chip.findAllByKey("Box:%s:Chips"%self.id)

    def delChip(self, cpid):
        _script = """
            redis.call('zrem', 'Box:'..KEYS[1]..':Chips', KEYS[2])
            local us = redis.call('zrange', 'Box:'..KEYS[1]..':Users', 0, -1)
            for k, v in pairs(us) do
                redis.call('hset', 'User:'..v..':info', 'bv', KEYS[3])
            end
        """
        return self._redis.eval(_script, [self.id, cpid, int(time.time())])

class Card(RedisHash):
    # SIM Card Model inherit from RedisHash
    #   @key id:        str     IMSI of the Card
    #   @key icc:       str     ICCID of the Card
    #   @key num:       str     Number of the Card
    #   @key mod:       str     MG2639, MC8332, SI3050
    #
    #   ISP(Internet Service Providers) name: ICCID[0:6]
    #   ISP Location:                         ICCID[9:10]
    #
    # Redis key
    #   Card:<id>:info          hash
    #   Card:City               hash
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
    #   @key fnum:      str     Other's format Phone Number
    #   @key inum:      str     Other's core Phone Number
    #   @key loc:       str     Location of Other's Phone Number
    #   @key typ:       str     Chip is host or guest, 0 means host, 1 means guest
    #   @key stt:       str     Calling status of the Card in Chip
    #   @key st:        int     Starting Timestamp
    #   @key ed:        int     Ending Timestamp
    #
    # Redis key
    #   Call:<id>:info          hash
    
    _infoTX = 604800

class Sms(RedisHash):
    # SMS model inherit from RedisHash
    #   @key id:        str     uuid.uuid1().hex, unique in whole system
    #   @key cdid:      str     ID of SIM Card, None if PSTN
    #   @key cpid:      str     ID of the Chip
    #   @key bid:       str     ID of the Box which contains the Chip
    #
    #   @key uid:       str     ID of user who send the SMS, None if SMS is received
    #   @key oth:       str     Other number
    #   @key fnum:      str     Other's format Phone Number
    #   @key inum:      str     Other's core Phone Number
    #   @key loc:       str     Location of Other's Phone Number
    #   @key msg:       str     SMS content
    #   @key st:        str     SMS sending timestamp
    #   @key ed:        str     SMS sended timestamp, None if send fail

    _infoTX = 86400
