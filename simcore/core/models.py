# -*- coding: utf-8 -*-
# Started by Alan
# MainTained by Alan
# Contact: alan@sinosims.com

from simcore.core.database import Srdb
from simcore.core.gol import raiseCode
from messaging.sms import SmsDeliver, SmsSubmit, CdmaSmsSubmit, CdmaSmsDeliver
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
    #   Session:<id>:info      hash     @keys
    
    _infoTX = 604800
    # pass

class User(RedisHash):
    # User Model inherit from RedisHash
    #   User has many Boxes, user can control the chips in Box only if the Box pair to User
    #   @key id:            uuid.uuid1() generated, unique in whole system
    #
    # Redis Key
    #   User:<id>:info                  hash        @keys
    #   User:<id>:news                  sortset     timestamp : news session id
    #   User:<id>:Boxes                 sortset     timestamp : box id
    #   User:<id>:Cards                 hash        cardIMSI : json.dumps({'clr' : 'FFFFFF', 'icn' : '0~29', 'name' : 'My Card'})
    #   User:<id>:oths                  sortset     
    #   User:<id>:oth:<oth>:voices      sortset
    #   User:<id>:othsms                sortset
    #   User:<id>:othsms:<oth>:sms      sortset
    #   User:<id>:atk                   hash        phoneIMEI : phoneATK

    def newsHeart(self, ses, chn, body):
        # Called by PhoneNoti 401
        #   1   Set news Session info
        #   2   Add news Session to User
        #   3   Get current Calling

        _script = """
            local rc = '0_0_0'
            if KEYS[6] == '21' then
                local av = redis.call('hget', 'User:'..KEYS[3]..':info', 'av')
                if av then rc = av end
            elseif KEYS[6] == '20' then
                local ov = redis.call('hget', 'User:'..KEYS[3]..':info', 'ov')
                if ov then rc = ov end
            end
            redis.call('hset', 'Session:'..KEYS[1]..':info', 'chn', KEYS[2])
            redis.call('expire', 'Session:'..KEYS[4]..':info', KEYS[5])
            redis.call('zadd', 'User:'..KEYS[3]..':news', KEYS[4], KEYS[1])
            local c = {}
            local cs  = {}
            local cll = ''
            local bs = redis.call('zrange', 'User:'..KEYS[3]..':Boxes', 0, -1)
            for k, v in pairs(bs) do
                cs = redis.call('zrange', 'Box:'..v..':Chips', 0, -1)
                for p, q in pairs(cs) do
                    cll = redis.call('hget', 'Chip:'..q..':info', 'cll')
                    if cll then table.insert(c, redis.call('hmget', 'Call:'..tostring(cll)..':info', 'uid', 'cpid', 'oth', 'loc', 'id', 'st', 'ed')) end
                end
            end
            return {rc, c}
        """
        d = self._redis.eval(_script, [ses.id, chn, self.id, int(time.time()), Session._infoTX, ses.get('rol', '0')])
        d.addCallback(lambda cls: [cls[0].split('_'), [ {'cid' : c[1], 'oth' : c[2], 'seq' : c[4], 'loc' : c[3], 'tim' : int(c[5])} 
                                    for c in cls[1] 
                                    if c[0] == '' and (not c[6]) and (time.time() - int(c[5])) < 180 ]])
        return d

    # def addNewsSession(self, sid):
    #     d = self._redis.zadd("User:%s:news"%self.id, int(time.time()), sid)
    #     d.addCallback(lambda x: self)
    #     return d

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
        # return chip info hash if user has this chip 
        # raise 603 if user don't have this chip

        _script = """
            local bid = redis.call('hget', 'Chip:'..KEYS[1]..':info', 'bid')
            local csc = redis.call('zscore', 'Box:'..bid..':Chips', KEYS[1])
            local sc = redis.call('zscore', 'User:'..KEYS[2]..':Boxes', bid)
            local cp = {}
            if csc == nil then
                return {'0'}
            end
            if sc ~= nil then
                cp = redis.call('hgetall', 'Chip:'..KEYS[1]..':info')
            end
            return cp
        """
        d = self._redis.eval(_script, [cpid, self.id])
        d.addCallback(lambda hs: raiseCode(701) if len(hs) == 1 else hs)
        d.addCallback(lambda hs: Chip(cpid, dict(zip(hs[::2], hs[1::2]))) if len(hs) > 0 else raiseCode(603))
        return d

    def sendSMS(self, cpid, oth, msg, smsid):
        # Called by PhoneMo 3401
        #   1   Pack SMS to pdu string
        #   2   Format other number
        #   3   Gen new SMS id
        #   4   raise 603 if user don't have this chip
        #   5   Set Sms info

        # sms = SmsSubmit(oth, msg)
        # pdu = sms.to_pdu()[0]
        now = int(time.time()*1000)
        (fnum, inum, loc) = phoneNum.loads(oth)
        # smsid = "%s%d%d"%(inum, now, random.randrange(100, 999))
        now = now/1000
        _script = """
            local bid = redis.call('hget', 'Chip:'..KEYS[1]..':info', 'bid')
            local csc = redis.call('zscore', 'Box:'..bid..':Chips', KEYS[1])
            local sc = redis.call('zscore', 'User:'..KEYS[2]..':Boxes', bid)
            local cp = {}
            if csc == nil then
                return {'0'}
            end
            if sc ~= nil then
                cp = redis.call('hmget', 'Chip:'..KEYS[1]..':info', 'id', 'mod', 'cdid', 'bid', 'sid', 'chn')
                redis.call('hmset', 'Sms:'..KEYS[3]..':info', 'id', KEYS[3], 'cpid', cp[1], 'cdid', cp[3], 'bid', cp[4], 'uid', KEYS[2], 'oth', KEYS[4], 'fnum', KEYS[5], 'inum', KEYS[6], 'loc', KEYS[7], 'msg', KEYS[8], 'st', KEYS[9])
            end
            return cp
        """
        d = self._redis.eval(_script, [cpid, self.id, smsid, oth, fnum, inum, loc, base64.b64encode(msg.encode('utf8')), now])
        d.addCallback(lambda hs: raiseCode(701) if len(hs) == 1 else hs)
        d.addCallback(lambda hs: Chip(cpid, dict(zip(['id', 'mod', 'cdid', 'bid', 'sid', 'chn'], hs))) if len(hs) > 0 else raiseCode(603))
        d.addCallback(lambda cp: [cp, SmsSubmit(oth, msg).to_pdu()[0] if cp['mod'] == 'MG2639' else CdmaSmsSubmit(oth, msg).to_pdu()[0]])
        d.addCallback(lambda cs: [cs[0], [cs[0].id, 4, smsid, 0x00, 10, '', 'AT+CMGS=%d\r'%cs[1].length, '%s\x1a'%cs[1].pdu] if cs[0]['mod'] == 'MG2639' else [cs[0].id, 4, smsid, 0x00, 10, '', 'AT+CMGS=%d\r%s\x1a'%(cs[1].length, cs[1].pdu)]])
        # d.addCallback(lambda cs: [cs[0], [cs[1][0], cs[1][1].length, cs[1][1].pdu]])
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
    #   @key stt:       int     Chip status
    #
    #   @key cll:       str     Current Call id, Key don't exist or Value is '' if no current call
    #
    # Redis key
    #   Chip:<id>:info          hash        @keys

    def login(self, imsi, bid, ses, chn, mod, icc, lvl):
        # Called by ChipMo 102
        #   1   Set Chip info
        #   2   Add Chip to Box
        #   3   Change Session info:Chip
        #   4   Change User info:bv
        #   5   Set Card to User
        #   6   Find Card number
        #   7   Set Card info

        self.update({ 'cdid' : imsi, 'bid' : bid, 'sid' : ses.id, 'chn' : chn, 'mod' : mod, 'lvl' : lvl })
        ses['Chip'] = self.id
        isph = {'00' : 11, '02' : 11, '07' : 11, '01' : 12, '06' : 12, '20' : 12, '03' : 13, '05' : 13}
        isp = 1 if mod == 'SI3050' else isph.get(imsi[3:5], 0)
        _script = """
            redis.call('hmset', 'Chip:'..KEYS[1]..':info', 'id', KEYS[1], 'cdid', KEYS[2], 'bid', KEYS[3], 'sid', KEYS[4], 'chn', KEYS[5], 'mod', KEYS[6], 'lvl', KEYS[9], 'lcon', KEYS[10])
            redis.call('zadd', 'Box:'..KEYS[3]..':Chips', tonumber(KEYS[10]), KEYS[1])
            redis.call('hset', 'Session:'..KEYS[4]..':info', 'Chip', KEYS[1])
            local us = redis.call('zrange', 'Box:'..KEYS[3]..':Users', 0, -1)
            local ses = {}
            for k, v in pairs(us) do
                redis.call('hset', 'User:'..v..':info', 'bv', KEYS[10])
                redis.call('hsetnx', 'User:'..v..':Cards', KEYS[2], '')
                redis.call('zremrangebyscore', 'User:'..v..':news', 0, tonumber(KEYS[10]) - 5*60)
                for p,q in pairs(redis.call('zrange', 'User:'..v..':news', 0, -1)) do
                    table.insert(ses, {q,redis.call('hget', 'Session:'..q..':info', 'chn')})
                end
            end
            local ni = redis.call('hexists', 'Card:'..KEYS[2]..':info', 'num')
            if ni == 0 then redis.call('hmset', 'Card:'..KEYS[2]..':info', 'imsi', KEYS[2], 'mod', KEYS[6], 'icc', KEYS[7], 'isp', KEYS[8]) end
            return ses
        """
        return self._redis.eval(_script, [self.id, imsi, bid, ses.id, chn, mod, icc, isp, lvl, int(time.time())])

    def startCall(self, clid, uid):
        # Called by ChipMo 1001 Dial return ok
        #   1   Set new Calling
        #   2   Set Chip info:cll

        self['cll'] = clid
        oth = clid[0:-16]
        (fnum, inum, loc) = phoneNum.loads(oth)
        _script = """
            redis.call('hmset', 'Call:'..KEYS[1]..':info', 'id', KEYS[1], 'cdid', KEYS[2], 'cpid', KEYS[3], 'bid', KEYS[4], 'uid', KEYS[5], 'oth', KEYS[6], 'fnum', KEYS[7], 'inum', KEYS[8], 'loc', KEYS[9], 'typ', '0', 'stt', '1', 'st', KEYS[10])
            redis.call('hset', 'Chip:'..KEYS[3]..':info', 'cll', KEYS[1])
            redis.call('zadd', 'Box:'..KEYS[4]..':Chips', tonumber(KEYS[10]), KEYS[3])
        """
        d = self._redis.eval(_script, [clid, self.get('cdid', ''), self.id, self['bid'], uid, oth, fnum, inum, loc, int(time.time())]) 
        d.addCallback(lambda x: Call(clid))
        return d

    def ringing(self, clid):
        # Calling by ChipMo 2001:4001
        #   1   Set new Calling
        #   2   Set Chip info:cll
        #   3   Find Users atk which should push ring
        #   4   Remove Timeout News Session
        #   5   Find News Session which should push ring
        #   6   Add Calling to Asynchronous System:Ring list

        self['cll'] = clid
        oth = clid[0:-16]
        (fnum, inum, loc) = phoneNum.loads(oth)
        # _script = """
        #     redis.call('hmset', 'Call:'..KEYS[1]..':info', 'id', KEYS[1], 'cdid', KEYS[2], 'cpid', KEYS[3], 'bid', KEYS[4], 'uid', '', 'oth', KEYS[5], 'fnum', KEYS[6], 'inum', KEYS[7], 'loc', KEYS[8], 'typ', '1', 'stt', '1', 'st', KEYS[9])
        #     redis.call('hset', 'Chip:'..KEYS[3]..':info', 'cll', KEYS[1])
        #     local ids = redis.call('zrange', 'Box:'..KEYS[4]..':Users', 0, -1)
        #     local ses = {}
        #     local atk = ''
        #     for k, v in pairs(ids) do
        #         for m,n in pairs(redis.call('hvals', 'User:'..v..':atk')) do
        #             atk = atk..n..','
        #         end
        #         redis.call('zremrangebyscore', 'User:'..v..':news', 0, KEYS[9] - 5*60)
        #         for p,q in pairs(redis.call('zrange', 'User:'..v..':news', 0, -1)) do
        #             table.insert(ses, {q,redis.call('hget', 'Session:'..q..':info', 'chn')})
        #         end
        #     end
        #     if atk ~= '' then redis.call('rpush', 'System:Ring', atk..KEYS[5]..','..KEYS[9]) end
        #     return ses
        # """
        _script = """
            redis.call('hmset', 'Call:'..KEYS[1]..':info', 'id', KEYS[1], 'cdid', KEYS[2], 'cpid', KEYS[3], 'bid', KEYS[4], 'uid', '', 'oth', KEYS[5], 'fnum', KEYS[6], 'inum', KEYS[7], 'loc', KEYS[8], 'typ', '1', 'stt', '1', 'st', KEYS[9])
            redis.call('hset', 'Chip:'..KEYS[3]..':info', 'cll', KEYS[1])
            redis.call('zadd', 'Box:'..KEYS[4]..':Chips', tonumber(KEYS[9]), KEYS[3])
            local ids = redis.call('zrange', 'Box:'..KEYS[4]..':Users', 0, -1)
            local ses = {}
            local an = ''
            local n = ''
            for k, v in pairs(ids) do
                n = redis.call('hget', 'User:'..v..':info', 'atkname')
                if n then an = an..n..',' end
                redis.call('zremrangebyscore', 'User:'..v..':news', 0, KEYS[9] - 5*60)
                for p,q in pairs(redis.call('zrange', 'User:'..v..':news', 0, -1)) do
                    table.insert(ses, {q,redis.call('hget', 'Session:'..q..':info', 'chn')})
                end
            end
            if an ~= '' then redis.call('rpush', 'System:Ring', an..KEYS[5]..','..KEYS[9]) end
            return ses
        """
        d = self._redis.eval(_script, [clid, self.get('cdid', ''), self.id, self['bid'], oth, fnum, inum, loc, int(time.time())])
        d.addCallback(lambda sa: (sa, inum, loc))
        return d

    def answerCall(self, clid, uid):
        return Call(clid).save({ 'uid' : uid })

    def changeCall(self):
        # Calling by ChipMo 2001:4004
        #   1   Find User who should be noticed Current Calling status changing
        #   2   Remove Timeout News Session
        #   3   Find News Session which should be noticed Current Calling status changing

        clid = self.get('cll', None)
        if not clid: return None 
        _script = """
            local uid = redis.call('hget', 'Call:'..KEYS[1]..':info', 'uid')
            local ses = {}
            redis.call('zremrangebyscore', 'User:'..uid..':news', 0, tonumber(KEYS[2]) - 5*60)
            for k,v in pairs(redis.call('zrange', 'User:'..uid..':news', 0, -1)) do
                table.insert(ses, {v,redis.call('hget', 'Session:'..v..':info', 'chn')})
            end
            return ses
        """
        d = self._redis.eval(_script, [clid, int(time.time())])
        d.addCallback(lambda sa: (sa, clid))
        return d

    def endCall(self):
        # Calling by ChipMo 2001:4004
        #   1   Change Calling info:stt ed
        #   2   Del Chip info:cll
        #   3   Add Calling to Asynchronous System:Calls list
        #   4   Find User who should be noticed Current Calling ended
        #   5   Remove Timeout News Session
        #   6   Find News Session which should be noticed Current Calling ended

        clid = self.get('cll', None)
        if not clid: return None
        del self['cll']
        _script = """
            redis.call('hmset', 'Call:'..KEYS[1]..':info', 'stt', KEYS[2], 'ed', KEYS[3])
            redis.call('hdel', 'Chip:'..KEYS[4]..':info', 'cll')
            redis.call('zadd', 'Box:'..KEYS[5]..':Chips', tonumber(KEYS[3]), KEYS[4])
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
            redis.call('zadd', 'Box:'..KEYS[4]..':Chips', tonumber(KEYS[2]), KEYS[3])
        """
        return self._redis.eval(_script, [smsid, int(time.time()), self.id, self['bid']])

    def smsing(self, pdu):
        # Called by ChipMo 2001:4002
        #   1   Unpack SMS from pdu string
        #   2   Format other number
        #   3   Gen new SMS id
        #   4   Set Sms info
        #   5   Add Sms to Asynchronous System:Sms list
        #   6   Find Users atk which should push smsing
        #   7   Remove Timeout News Session
        #   8   Find News Session which should push smsing
        #   9   Add Calling to Asynchronous System:Smsing smsing  

        sms = SmsDeliver(pdu).data if self['mod'] == 'MG2639' else CdmaSmsDeliver(pdu).data
        tim = int(time.mktime(sms['date'].utctimetuple())) + 28800
        now = int(time.time()*1000)
        (fnum, inum, loc) = phoneNum.loads(sms['number'])
        smsid = "%s%d%d"%(inum[-20:], now, random.randrange(100, 999))
        now = now/1000
        msg = base64.b64encode(sms['text'].encode('utf8'))
        # _script = """
        #     redis.call('hmset', 'Sms:'..KEYS[1]..':info', 'id', KEYS[1], 'cpid', KEYS[2], 'cdid', KEYS[3], 'bid', KEYS[4], 'oth', KEYS[5], 'fnum', KEYS[6], 'inum', KEYS[7], 'loc', KEYS[8], 'msg', KEYS[9], 'st', KEYS[10], 'ed', KEYS[11])
        #     redis.call('rpush', 'System:Sms', KEYS[1])
        #     local ids = redis.call('zrange', 'Box:'..KEYS[4]..':Users', 0, -1)
        #     local ses = {}
        #     local atk = ''
        #     for k, v in pairs(ids) do
        #         for m,n in pairs(redis.call('hvals', 'User:'..v..':atk')) do
        #             atk = atk..n..','
        #         end
        #         redis.call('zremrangebyscore', 'User:'..v..':news', 0, KEYS[10] - 5*60)
        #         for p,q in pairs(redis.call('zrange', 'User:'..v..':news', 0, -1)) do
        #             table.insert(ses, {q,redis.call('hget', 'Session:'..q..':info', 'chn')})
        #         end
        #     end
        #     if atk ~= '' then redis.call('rpush', 'System:Smsing', atk..KEYS[1]) end
        #     return ses
        # """
        print '----', repr([smsid, self.id, self['cdid'], self['bid'], sms['number'], fnum, inum, loc, msg, tim, now])
        _script = """
            redis.call('hmset', 'Sms:'..KEYS[1]..':info', 'id', KEYS[1], 'cpid', KEYS[2], 'cdid', KEYS[3], 'bid', KEYS[4], 'oth', KEYS[5], 'fnum', KEYS[6], 'inum', KEYS[7], 'loc', KEYS[8], 'msg', KEYS[9], 'st', KEYS[10], 'ed', KEYS[11])
            redis.call('rpush', 'System:Sms', KEYS[1])
            local ids = redis.call('zrange', 'Box:'..KEYS[4]..':Users', 0, -1)
            local ses = {}
            local an = ''
            local n = ''
            for k, v in pairs(ids) do
                n = redis.call('hget', 'User:'..v..':info', 'atkname')
                if n then an = an..n..',' end
                redis.call('zremrangebyscore', 'User:'..v..':news', 0, tonumber(KEYS[11]) - 5*60)
                for p,q in pairs(redis.call('zrange', 'User:'..v..':news', 0, -1)) do
                    table.insert(ses, {q,redis.call('hget', 'Session:'..q..':info', 'chn')})
                end
            end
            if an ~= '' then redis.call('rpush', 'System:Smsing', an..KEYS[1]) end
            return ses
        """
        d = self._redis.eval(_script, [smsid, self.id, self['cdid'], self['bid'], sms['number'], fnum, inum, loc, msg, tim, now ])
        d.addCallback(lambda sa: self._debug_(sa))
        d.addCallback(lambda sa: (sa, [sms['number'], sms['text'], tim, inum, smsid]))
        return d

    def users(self):
        return Box(self['bid']).users()

    def onl(self, info):
        # Called by ChipMo 2002
        #   1   Change Box Chips Timestamp
        #   2   Delay Session Redis expire time

        self['sig'] = info[1]
        self['stt'] = info[2]
        _script = """
            redis.call('zadd', 'Box:'..KEYS[1]..':Chips', KEYS[2], KEYS[3])
            redis.call('hmset', 'Chip:'..KEYS[3]..':info', 'sig', KEYS[6], 'stt', KEYS[7])
            redis.call('expire', 'Session:'..KEYS[4]..':info', KEYS[5])
            local ses = {}
            for k, v in pairs(redis.call('zrange', 'Box:'..KEYS[1]..':Users', 0, -1)) do
                for p,q in pairs(redis.call('zrange', 'User:'..v..':news', 0, -1)) do
                    table.insert(ses, {q,redis.call('hget', 'Session:'..q..':info', 'chn')})
                end
            end
            return ses
        """
        return self._redis.eval(_script, [self['bid'], int(time.time()), self.id, self['sid'], Session._infoTX, info[1], info[2]])

    def call(self):
        pass

    # def callingUser(self):
    #     cll = self.get('cll', None)
    #     if not cll: return None 
    #     _script = """
    #         local uid = redis.call('hget', 'Call:'..KEYS[1]..':info', 'uid')
    #         return redis.call('hgetall', 'User:'..uid..':info')
    #     """
    #     d = self._redis.eval(_script, [cll])
    #     d.addCallback(lambda info: User.reloadFromInfo(dict(zip(info[::2], info[1::2]))))
    #     return d

    def setNum(self, num):
        (fnum, inum, loc) = phoneNum.loads(num)
        return self._redis.hmset('Card:%s:info'%self['cdid'], 'num', num, 'loc', loc, 'inum', inum)

    def fineOth(self, oth):
        # Add "#" to the end of Other number through SI3050

        if self['mod'] == 'SI3050': oth = oth.replace('+86', '')# + "#"
        return (self, oth)

    # @classmethod
    # def findById(self, id):
    #     if not id: return None
    #     _script = """
    #         local bid = redis.call('hget', 'Chip:'..KEYS[1]..':info', 'bid')
    #         redis.call('zadd', 'Box:'..bid..':Chips', KEYS[2], KEYS[1])
    #         return redis.call('hgetall', 'Chip:'..KEYS[1]..':info')
    #     """
    #     d = self._redis.eval(_script, [id, int(time.time())])
    #     # d = self._redis.hgetall("%s:%s:info"%(self.__name__, id))
    #     print '-----'
    #     d.addCallback(lambda hs: dict(zip(hs[::2], hs[1::2])))
    #     d.addCallback(lambda hs: self._debug_(hs))
    #     d.addCallback(lambda hs: self(id, hs) if len(hs) > 0 else None)
    #     return d


class Box(RedisHash):
    # Box Model inherit from RedisHash
    #   @key id:        str     IMEI of the Box, unique in whole system
    #   @key set:       int     The Box is in the setting mode or not, 0 means not in setting mode, 1 means in
    #   @key onl:       int     Box last http connection timestemp
    #   @key name:      str     Box name user for development and test
    #   @key bv:        str     New version box should update
    #   @key nv:        str     New version need allow by user to update
    #   @key typ:       str     typ D : develop, T : test, A : alpha, N : Normal
    #
    # Redis key
    #   Box:<id>:info           hash            @keys
    #   Box:<id>:Users          sortset         timestamp : user id
    #   Box:<id>:Chips          sortset         timestamp : chip id
    #   System:Box:version      sortset         timestamp : version id
    #   Box:version:<vid>       hash 
    #       id          str         Version id, uuid.uuid4().hex, unique in whole system
    #       ver         str         Version num, 0.1.1
    #       desc        str         Description of the version 
    #       tm          int         Download times
    #       pc          str         Premission Code for update
    #       pub_<typ>   str         typ D : develop, T : test, A : alpha, N : Normal
    #   System:Box:<typ>:list   sortset         timestamp : bid
    #       typ         str         typ D : develop, T : test, A : alpha, N : Normal

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
            local ses = {}
            for k, v in pairs(us) do
                redis.call('hset', 'User:'..v..':info', 'bv', KEYS[3])
                for p,q in pairs(redis.call('zrange', 'User:'..v..':news', 0, -1)) do
                    table.insert(ses, {q,redis.call('hget', 'Session:'..q..':info', 'chn')})
                end
            end
            return ses
        """
        return self._redis.eval(_script, [self.id, cpid, int(time.time())])

class Card(RedisHash):
    # SIM Card Model inherit from RedisHash
    #   @key id:        str     IMSI of the Card
    #   @key icc:       str     ICCID of the Card
    #   @key num:       str     Number of the Card
    #   @key inum:      str     Core number of the Card
    #   @key mod:       str     MG2639, MC8332, SI3050
    #   @key loc:       str     Location of the Card
    #   @key isp:       int     0 unknown, 1 PSTN, 11 China Mobile, 12 China Union, 13 China Telecom
    #
    #   ISP(Internet Service Providers) name: IMSI[3:5]
    #   ISP Location:                         simisp.phoneNum.loads(num)[2]
    #
    # Redis key
    #   Card:<id>:info          hash            @keys
    
    pass

class Call(RedisHash):
    # Call Model inherit from RedisHash
    #   @key id:        str     Sequence id generated by phone or chip, "%s%d%d"%(inum[-20:], int(time.time()), random.randrange(100, 999))
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
    #   Call:<id>:info          hash            @keys
    #   System:Calls            list            ['id']
    #   System:Ring             list            ['atk,atk,...,atk,oth,int(time.time()']
    
    _infoTX = 604800

class Sms(RedisHash):
    # SMS model inherit from RedisHash
    #   @key id:        str     "%s%d%d"%(inum[-20:], int(time.time()), random.randrange(100, 999)), unique in whole system
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
    #
    # Redis key
    #   System:Sms              list            ['id']
    #   System:Smsing           list            ['atk,atk,..,atk,id']

    _infoTX = 86400


# class Phone(RedisHash):
    # Phone model inherit from RedisHash
    #   @key id:        str     IMEI of the Phone
    #   @key uid:       str     Login User id of the Phoen
    #
    # Redis key
    #   Phone:<id>:info          hash            @keys
