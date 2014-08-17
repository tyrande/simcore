# -*- coding: utf-8 -*-
# Started by Alan
# MainTained by Alan
# Contact: alan@sinosims.com

from twisted.internet import protocol, reactor, defer
from twisted.internet.protocol import ClientFactory, Protocol
from simcore.core.database import SrPushdb
from simcore.core.gol import Gol
from simcore.core.models import Session
import simcore.libs.txredisapi as redis
from apns import APNs, Payload
import struct, msgpack, uuid, time, random

class PackBase(object):
    # Package struct implement Hub Protocol 

    _headerSync = '\x05\x00\x0B\x00'
    _version = 1
    _headerLen = 14

    def dump(self):
        # Dump the package to bytes.
        #   Will generate a new session id if self.sid is None. 

        bodyPacked = msgpack.packb(self.body) if self.body != None else ""
        sidPacked = '' if self.sid == None else uuid.UUID(hex=self.sid).bytes
        header = struct.pack("!4sccHHc3s", self._headerSync, chr(self._version), chr(self._flags), self.apiRet, self.id, chr(len(sidPacked)), struct.pack("!I", len(bodyPacked))[1:])
        return header + sidPacked + bodyPacked

    def __init__(self, id, apiRet, sid, body):
        # @param id:          Package id, unique in socket.
        # @param apiRet:      Route code to match the route api in Request package, Route return code in Respond package
        # @param sid:         Session id
        # @param body:        Package body, should be array or hash

        self.id, self.apiRet, self.sid, self.body  = id, apiRet, sid, body
        self.routeCode = None
        self._TPack = None
        self._PPack = None

class TPack(PackBase):
    # Request Package inherit from PackBase
    #   See Wiki for more: http://192.168.6.66/projects/sim/wiki/Hub%E5%8D%8F%E8%AE%AE

    _flags = 0x00

    def __init__(self, id, apiRet, sid, body):
        PackBase.__init__(self, id, apiRet, sid, body)
        self.routeCode = apiRet

    def peerToPPack(self, pp):
        self._PPack = pp
        return self

class DPack(PackBase):
    # Respond Package inherit from PackBase
    #   See Wiki for more: http://192.168.6.66/projects/sim/wiki/Hub%E5%8D%8F%E8%AE%AE

    _flags = 0x80

    def peerToTPack(self, tp):
        self._TPack = tp
        self.routeCode = tp.routeCode
        self._PPack = tp._PPack
        return self

class PPack(object):
    # Package for pass from current socket to target socket
    # @attr receiverSckId:      Socket id of target socket, should be sesstion id or session id + sckType 
    # @attr senderId:           Mo id of current socket
    # @attr senderCls:          Mo class of current socket
    # @attr senderChannel:      Channel of current socket
    # @attr senderSid:          Session id of current socket
    # @attr packId:             Parent TPack id if flag is 0x00, Peer TPack id if flag is 0x80
    # @attr flag:               Package flag which ask target socket to send
    # @attr apiRet:             Package apiRet which ask target socket to send
    # @attr body:               Package body which ask target socket to send

    def __init__(self, argArr):
        self.receiverSckId, self.senderId, self.senderCls, self.senderChannel, self.senderSid, self.packId, self.flag, self.apiRet, self.body = argArr

    def dump(self):
        # Dump the self with msgpack 
        #   Let it can be passed by Redis Pub&Sub system

        return msgpack.packb([self.receiverSckId, self.senderId, self.senderCls, self.senderChannel, self.senderSid, self.packId, self.flag, self.apiRet, self.body])

    def __repr__(self):
        return repr([self.receiverSckId, self.senderId, self.senderCls, self.senderChannel, self.senderSid, self.packId, self.flag, self.apiRet, self.body])

    @classmethod
    def loads(self, str):
        return PPack(msgpack.unpackb(str))

def routeCode(code):
    # Decorator for route code and route api
    
    def decorator(callback):
        Gol().addRoute(code, callback)
        return callback
    return decorator

class SHProtocol(protocol.Protocol):
    # Simhub Protocol
    #   Receive and Send data with Hub Protocol

    #   @attr _session:         The auth info for current socket
    #   @attr _mo:              Mobile Originated, Current User or Card in the other side of the socket
    #   @attr _ot:              opposite terminal
    #   @attr _TPackWaitPeer:   TPack wait hash, record the request package cross to box
    #   @attr _pckId:           Use to generate new TPack id, start from 1000 because Phone and Card generate TPack id from 1
    
    _redis = SrPushdb().redisPool

    def connectionMade(self):
        # -*- Debug -*-
        Gol()._logPack_('CM', self, None, '>> %s'%self.__class__.__name__)

        self._recvBuf = ''
        self._pckId = 1000 + random.randint(0, 5000)
        self._session = None
        self._mo = None
        self._TPackWaitPeer = {}

    def connectionLost(self, reason):
        if self._session: Gol().delSck(self._session.id, self.factory._sckType)

        # -*- Debug -*-
        Gol()._logPack_('CL', self, None, '<< %s'%self.__class__.__name__)

    def dataReceived(self, data):
        self._recvBuf += data
        while len(self._recvBuf) > 4:
            self._recvBuf, pack = packLoads(self._recvBuf)
            if pack: self.recvPack(pack)

    def recvPack(self, pack):
        if type(pack) == DPack:
            tp = self.findWaitingTPack(pack.id)
            if tp: pack.peerToTPack(tp)
            else: self.errorRoutePack(500, pack)
        
        # -*- Debug -*-
        Gol()._logPack_('FR', self, pack)

        d = defer.Deferred()
        d.addCallback(self.loadSession)
        d.addCallback(self.loadMo)
        d.addCallback(lambda x: Gol().route(pack.routeCode)(self, pack))
        d.addCallbacks(self.finishRoutePack, lambda x: self.errorRoutePack(x, pack))
        d.callback(pack)

    def processPPack(self, ppack):
        # Process package from other socket, maybe from the same server, maybe from an other server through Redis
        #   @param senderId:        Sender socket mo id
        #   @param senderCls:       Sender socket mo class
        #   @param senderChannel:   Sender socket factory channel
        
        # -*- Debug -*-
        # Gol()._logPack_('PP', self, None, "[%s %s %s:%s:%s RC %s:%s:%s] %s"%(pack.__class__.__name__.replace('ack', ''), pack.id, self.factory.channel, self._mo.__class__.__name__, self._mo.id, senderChannel, senderCls, senderId, pack.routeCode))

        if ppack.flag == 0x00:
            pack = TPack(self.newPackId(), ppack.apiRet, self._session.id, ppack.body)
            pack.peerToPPack(ppack)
            self.addTPackWaiting(pack)
            self.send(pack)
        else:
            self.returnDPack(ppack.apiRet, ppack.body, ppack.packId)

        # if type(pack) == TPack:
        #     pack.setMo(senderId, senderCls, senderChannel)
        #     if parentTPack:
        #         pack.peerToTPack(parentTPack)

        #     self.addTPackWaiting(pack)
        #     return self.send(pack)
        #     return Gol().route(pack.routeCode)(self, pack)
        # else:
        #     return self.send(pack)

    def loadSession(self, pack):
        # Load Session by received package sid
        #   If socket already has session:                      Check current session id with package sid
        #   If socket has no session and package has sid:       Load session from redis by package sid
        #   if socket has no session and package has no sid:    Create a new session for this new socket

        d = None
        if self._session != None:
            if pack.sid != self._session.id: raise Exception(401)
        else:
            d = Session.findById(pack.sid) if len(pack.sid) == 32 else Session.create({ 'ts' : int(time.time()) })
            d.addCallback(lambda s: self.setSession(s))
            d.addCallback(lambda s: Gol().addSck(self, s.id, self.factory._sckType))
        return d

    def setSession(self, s):
        self._session = s
        return s

    def loadMo(self, s):
        # Load Mo by current session
        #   If there has no current session:       Nothing to load
        #   Else:                                  Find Mo by Mo class and Mo id which store in session

        if not self._session: return None
        _moid = self._session.get(self._moClass.__name__, None)
        if not _moid: return None
        d = self._moClass.findById(_moid)
        d.addCallback(lambda mo: self.setMo(mo))
        return d

    def setMo(self, mo):
        self._mo = mo
        return mo

    def send(self, pack):
        # -*- Debug -*-
        Gol()._logPack_('TO', self, pack)

        self.transport.write(pack.dump())
        return pack

    def newPackId(self):
        self._pckId = (self._pckId + 1)%50000
        return self._pckId

    def returnDPack(self, rt, body, tpid):
        # Respond package through current socket
        #   @param rt:      Return Code
        #   @param body:    Package body
        #   @param tpid:    Which TPack id should be respond
        
        pack = DPack(tpid, rt, self._session.id, body)
        return self.send(pack)

    def passToSck(self, channel, SckId, packId, flag, apiRet, body):
        # -*- Debug -*-
        # Simhub()._logPack_('PT', self, None, "[%s %s %s:%s:%s To %s:%s] %s"%(pack.__class__.__name__.replace('ack', ''), pack.id, self.factory.channel, self._mo.__class__.__name__, self._mo.id, channel, sid, pack.routeCode))

        ppack = PPack([SckId, self._mo.id, self._mo.__class__.__name__, self.factory.channel, self._session.id, packId, flag, apiRet, body])
        if channel == self.factory.channel and False:
            sck = self.findSck(SckId)
            if sck:
                return sck.processPPack(ppack)
        else:
            return self._redis.publish(channel, ppack.dump())

    def notiToUsers(self, us, rc, body):
        [ self.notiToUser(u, rc, body) for u in us ]

    def notiToUser(self, u, rc, body):
        # Push notice through user's news socket
        #   If user's phone system is iOS, also push notice through Apple's notice channel
        #   -*- TODO -*- : 1. Support user has mutiple devices
        #                  2. When push through socket fail, use the Apple way

        d = u.newsSessions()
        d.addCallback(lambda ses: [ self.passToSck(s['chn'], s.id + 'news', '', 0x00, rc, body) for s in ses ])
        if u.get('rol', None) == '20' and u.get('atk', None):
            d.addCallback(lambda x: self.sendNotiToApple(u['atk'], 'Calling...'))
        return d

    def sendNotiToApple(self, pushTok, note):
        payload = Payload(alert=note, sound="default", badge=1)
        self.factory._apns.gateway_server.send_notification(pushTok, payload)

    def finishRoutePack(self, pack):
        pass

    def errorRoutePack(self, failure, tpack):
        raise failure
        print 'error Route', failure
        self.returnDPack(int(failure.getErrorMessage()), None)

    def addTPackWaiting(self, pack):
        self._TPackWaitPeer[pack.id] = pack

    def findWaitingTPack(self, packid):
        tp = self._TPackWaitPeer.get(packid, None)
        if tp: del self._TPackWaitPeer[packid]
        return tp

    def findSck(self, SckId):
        return Gol().findSck(SckId)


class SHPFactory(protocol.Factory):
    # Factory class to create SHProtocol socket
    # @attr _apns:      For pushing Apple notice
    # @attr _sckType:   Commend socket should be '', News socket should be 'news'
    # @attr channel:    Current server id, use to subscribe Redis Pub&Sub system

    _apns = APNs(use_sandbox=True, cert_file='ca/aps_development.pem', key_file='ca/simhub_nopass.pem')
    _sckType = ''

    def __init__(self, channel):
        self.channel = channel

    def __repr__(self):
        return "[ %s on %s ]"%(self.__class__.__name__, self.channel)


class RedisSub(redis.SubscriberProtocol):
    # Redis Subscribe Socket
    #   One server should have only one sub socket
    #   Use server id (self.factory.channel) to subscribe to Redis Pub&Sub system

    def connectionMade(self):
        self.subscribe(self.factory.channel)

    def messageReceived(self, pattern, channel, message):
        # Receive PPack dumpped str

        ppack = PPack.loads(message)
        sck = self.findSck(ppack.receiverSckId)
        if sck:
            sck.processPPack(ppack)

    def findSck(self, sid, sckType=''):
        return Gol().findSck(sid, sckType)

class RedisSubFactory(redis.SubscriberFactory):
    maxDelay = 120
    continueTrying = True
    protocol = RedisSub

    def __init__(self, channel, isLazy=False, handler=redis.ConnectionHandler):
        self.channel = channel
        redis.SubscriberFactory.__init__(self, isLazy, handler)

    def __repr__(self):
        return "[ %s on %s ]"%(self.__class__.__name__, self.channel)

def packLoads(buf):
    # Load TPack or DPack from socket buffer
    #   return remaining buffer and parsed Pack
    #   -*- TODO -*- : Make it into SHProtocol class, global method is not good

    if len(buf) < 4: return buf, None

    idx = buf.find(PackBase._headerSync)
    if idx < 0:
        print "no header_sync, drop", len(buf)-3
        return buf[-3:], None
    elif idx > 0:
        print "some noise before header_sync, drop", idx
        buf = buf[idx:]

    if len(buf) < PackBase._headerLen: return buf, None

    sync, ver, flags, apiRet, packid, sidLen, bodyLen = struct.unpack("!4sccHHc3s", buf[:PackBase._headerLen])
    ver = ord(ver)
    flags = ord(flags)
    sidLen = ord(sidLen)
    bodyLen, = struct.unpack("!I",'\x00'+bodyLen)

    if ver == PackBase._version and (flags & 0xffffff3f) == 0 and (sidLen == 0 or sidLen == 16) : pass
    else:
        print "header check error, drop", 1
        return buf[1:], None

    pkgLen = PackBase._headerLen + sidLen + bodyLen
    if len(buf) < pkgLen: return buf, None
    elif len(buf) > pkgLen:
        if not buf[pkgLen:].startswith(PackBase._headerSync[:len(buf)-pkgLen]):
            print "header_sync after body check error, drop", 1
            return buf[1:], None

    sid = buf[PackBase._headerLen : PackBase._headerLen+sidLen]
    if sidLen == 16: sid = uuid.UUID(bytes=sid).hex
    bodyStr  = buf[PackBase._headerLen+sidLen : pkgLen]

    if len(bodyStr) == 0: body = None
    else:
        try:
            body = msgpack.unpackb(bodyStr, encoding = 'utf-8')
        except Exception, e:
            print "body decode error, drop", pkgLen
            return buf[pkgLen:], None

    pack = TPack(packid, apiRet, sid, body) if flags == 0x00 else DPack(packid, apiRet, sid, body)
    
    return buf[pkgLen:], pack
