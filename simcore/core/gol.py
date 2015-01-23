# -*- coding: utf-8 -*-
# Started by Alan
# MainTained by Alan
# Contact: alan@sinosims.com

import random, msgpack

def raiseCode(code):
    raise Exception(code)

class Gol(object):
    # Gol is the global Singlone Class maintain global resource
    # @attr env:            Twisted running envirement (test, dev, production)
    # @attr sckPool:        [Session id][Key] -> [Socket] storage, Key should be "news" for phone
    # @attr routePool:      [Route Code] -> [Route api callback] storage, See wiki <Hub API List>http://192.168.6.66/projects/sim/wiki
    # @attr callTunnel:     Call Tunnel server (turnServer) <host>:<port> string list. 
    # @attr apns:          For pushing Apple notice

    def __new__(cls, *args, **kw):  
        if not hasattr(cls, '_instance'):  
            orig = super(Gol, cls)  
            cls._instance = orig.__new__(cls, *args, **kw)
        return cls._instance

    def init(self, env):
        self.env, self.sckPool, self.routePool, self.callTunnels, self.callTok, self.stop = env, {}, {}, [], 1, False

    # Control Route Pool
    #   @param sckCls:          Socket Class Name
    #   @param code:            Route Code

    def addRoute(self, sckCls, code, callback):
        self.routePool["%s%d"%(sckCls.lower(), code)] = callback

    def route(self, sckCls, code):
        return self.routePool.get("%s%d"%(sckCls.lower(), code), self.routeMiss)

    def routeMiss(self, sck, pack):
        self._logPack_('MS', sck, pack)
        raise Exception(404)

    # Control Call Tunnel
    def setCallTunnels(self, ts):
        self.callTunnels = ts

    def addCallTunnel(self, host, port):
        self.callTunnels.append("%s:%d"%(host, port))

    def getCallTunnel(self):
        self.callTok = self.callTok%65000 + 1
        return (self.callTok, random.sample(self.callTunnels, 1)[0])

    # Control Socket Pool
    #   @param sid:         Session id of the Socket
    #   @param sckType:     Socket type: '' for normal socket, 'news' for phone noti socket

    def addSck(self, sck, sid, sckType=''):
        _sckId = "%s%s"%(sid, sckType)
        self.sckPool[_sckId] = sck
        return sck

    def findSck(self, sid, sckType=''):
        return self.sckPool.get("%s%s"%(sid, sckType), None)

    def delSck(self, sid, sckType=''):
        _sckId = "%s%s"%(sid, sckType)
        if _sckId in self.sckPool: del self.sckPool[_sckId]

    def setMonitor(self, mon):
        self.monitor = mon

    def _log_(self, act, socket, pack=None, str=' '):
        # Log simhub action
        #   @param act:     Action Name
        #                       CM : Socket Connection Made
        #                       CL : Socket Connection Lose
        #                       FR : Package From
        #                       To : Package To
        #                       MS : Package Route Miss
        #                       ER : Error
        #   @param socket:  Current Socket of action
        #   @param pack:    Pack to log
        #   @param str:     Extra message to log

        socketName = socket.__class__.__name__
        peer = socket.transport.getPeer()
        
        logsrt = "%s %s:%d"%(act, peer.host, peer.port)
        if pack : 
            logsrt += " %s:%s %s:%s %s"%(pack.apiRet, pack._flags, pack.id, pack.sid, pack.body)
            if socket._mo : logsrt += " %s:%s "%(socket._mo.__class__.__name__, socket._mo.id)
        logsrt += (' ' + str)
        print logsrt

        if self.env == 'test': 
            _fs = self._formatPack_(act, socket, pack, str)
            _fso = msgpack.packb(_fs[:-1])
            moid = socket._mo.id if socket._mo else None
            pid = pack.id if pack else None
            [ m.show(_fso, moid, pid) for m in Gol().monitor.ms.values() ]
        return

    def _formatPack_(self, act, socket, pack=None, str=' '):
        str = ' ' + str
        _formatStr = ''
        socketName = socket.__class__.__name__
        peer = socket.transport.getPeer()
        sktColor = {'PhoneMo' : [41, 37], 'PhoneNoti' : [42, 37], 'CardMo' : [43, 37]}.get(socketName, [44, 37])
        sktOut = "[{0:>15}:{1:<5}]".format(peer.host, peer.port)
        ln = len(sktOut)
        strColor = { 'FR' : [43, 37], 'TO' : [47, 34], 'CM' : [42, 37], 'CL' : [41, 37], 'PT' : [47, 31], 'PP' : [47, 31], 'MS' : [45, 37]}[act]
        out = "\033[%d;%dm%s"%(sktColor[0], sktColor[1], sktOut) + "\033[%d;%dm [%s] "%(strColor[0], strColor[1], act)
        outBlank = "\033[%d;%dm%s"%(sktColor[0], sktColor[1], ' '*ln) + "\033[%d;%dm%s"%(strColor[0], strColor[1], ' '*6)
        lineLen = 100
        
        if pack != None:
            packLen = pack.length()
            packColor = { 0x00 : [49, 34], 0x80 : [49, 32] }[pack._flags]
            if len(str.strip()) > 1: 
                _formatStr += self._formatPackStr_(str[:lineLen], out, [49, strColor[0] - 10], lineLen)
                if len(str[lineLen:]) > 0: _formatStr += self._formatPackStr_(' ' + str[lineLen:], outBlank, [49, strColor[0] - 10], lineLen)
                out = outBlank
            pbOut = " [Body] %s"%repr(pack.body)
            if type(pack).__name__ == 'TPack':
                pkOut = " [TP %s %s:%s %s] route \033[49;31m%s (%s)"%(pack.id, pack.sid, socketName, packLen, repr(self.route(socketName, pack.apiRet).__name__), pack.apiRet)
                _formatStr += self._formatPackStr_(pkOut, out, packColor, lineLen)
            else:
                pkOut = " [DP %s %s:%s %s] return %s"%(pack.id, pack.sid, socketName, packLen, pack.apiRet)
                _formatStr += self._formatPackStr_(pkOut, out, packColor, lineLen)
            if socket._session != None:
                psOut = " [Session] %s"%(repr(socket._session))
                _formatStr += self._formatPackStr_(psOut, outBlank, packColor, lineLen)
            if socket._mo != None:
                pcOut = " [%s %s] %s"%(socket._mo.__class__.__name__, socket._mo.id, repr(socket._mo))
                _formatStr += self._formatPackStr_(pcOut, outBlank, packColor, lineLen)
            if pack._PPack:
                ppOut = " [PP] %s"%repr(pack._PPack)
                _formatStr += self._formatPackStr_(ppOut, outBlank, packColor, lineLen)
            _formatStr += self._formatPackStr_(pbOut, outBlank, packColor, lineLen)
            _formatStr += self._formatPackStr_(' ' + '-'*(len(pkOut)-1), outBlank, packColor, lineLen)
        else:
            _formatStr += self._formatPackStr_(str[:lineLen], out, [49, strColor[0] - 10], lineLen)
            if len(str[lineLen:]) > 0: _formatStr += self._formatPackStr_(' ' + str[lineLen:], outBlank, [49, strColor[0] - 10], lineLen)
        return _formatStr

    def _formatPackStr_(self, str, sob, pkclr, lineMaxLen):
        _fs = ''
        while len(str) != 0:
            _fs += "%s\033[%d;%dm%s\033[0m\n"%(sob, pkclr[0], pkclr[1], str[:lineMaxLen])
            str = str[lineMaxLen:]
            if not len(str) == 0: str = ' '*8 + str
        return _fs
