# -*- coding: utf-8 -*-
# Started by Alan
# MainTained by Alan
# Contact: alan@sinosims.com

import random

def raiseCode(code):
    raise Exception(code)

class Gol(object):
    # Gol is the global Singlone Class maintain global resource
    # @attr env:            Twisted running envirement (test, dev, production)
    # @attr sckPool:        [Session id][Key] -> [Socket] storage, Key should be "news" for phone
    # @attr routePool:      [Route Code] -> [Route api callback] storage, See wiki <Hub API List>http://192.168.6.66/projects/sim/wiki
    # @attr callTunnel:     Call Tunnel server (turnServer) list. 

    def __new__(cls, *args, **kw):  
        if not hasattr(cls, '_instance'):  
            orig = super(Gol, cls)  
            cls._instance = orig.__new__(cls, *args, **kw)
        return cls._instance

    def init(self, env):
        self.env, self.sckPool, self.routePool, self.callTunnels = env, {}, {}, []

    # Control Route Pool
    def addRoute(self, code, callback):
        self.routePool[code] = callback

    def route(self, code):
        return self.routePool.get(code, self.routeMiss)

    def routeMiss(self, sck, pack):
        self._logPack_('MS', sck, pack)
        raise Exception(404)

    # Control Call Tunnel
    def setCallTunnels(self, ts):
        self.callTunnels = ts

    def addCallTunnel(self, host, port):
        self.callTunnels.append("%s:%d"%(host, port))

    def getCallTunnel(self):
        return random.sample(self.callTunnels, 1)[0]

    # Control Socket Pool
    def addSck(self, sck, sid, sckType=''):
        _sckId = "%s%s"%(sid, sckType)
        self.sckPool[_sckId] = sck
        return sck

    def findSck(self, sid, sckType=''):
        return self.sckPool.get("%s%s"%(sid, sckType), None)

    def delSck(self, sid, sckType=''):
        _sckId = "%s%s"%(sid, sckType)
        if _sckId in self.sckPool: del self.sckPool[_sckId]

    # Log for test or dev
    def _logPack_(self, act, socket, pack=None, str=None):
        if not self.env in ['test', 'dev']: return
        socketName = socket.__class__.__name__
        peer = socket.transport.getPeer()
        sktColor = {'PhoneMo' : [41, 37], 'PhoneNoti' : [42, 37], 'CardMo' : [43, 37]}.get(socketName, [44, 37])
        sktOut = "[{0:>15}:{1:<5}]".format(peer.host, peer.port)
        ln = len(sktOut)
        strColor = { 'FR' : [43, 37], 'TO' : [47, 34], 'CM' : [42, 37], 'CL' : [41, 37], 'PT' : [47, 31], 'PP' : [47, 31], 'MS' : [45, 37]}[act]
        out = "\033[%d;%dm%s"%(sktColor[0], sktColor[1], sktOut) + "\033[%d;%dm [%s] "%(strColor[0], strColor[1], act)
        outBlank = "\033[%d;%dm%s"%(sktColor[0], sktColor[1], ' '*ln) + "\033[%d;%dm%s"%(strColor[0], strColor[1], ' '*6)
        lineLen = 100
        str = ' ' + str if str else ' '

        # -*- TODO -*- : Print PPack
        if pack != None:
            packColor = { 0x00 : [49, 34], 0x80 : [49, 32] }[pack._flags]
            if len(str) > 1: 
                self.printStr(str[:lineLen], out, [49, strColor[0] - 10], lineLen)
                if len(str[lineLen:]) > 0: self.printStr(' ' + str[lineLen:], outBlank, [49, strColor[0] - 10], lineLen)
                out = outBlank
            pbOut = " [Body] %s"%repr(pack.body)
            if type(pack).__name__ == 'TPack':
                pkOut = " [TP %s %s:%s] route \033[49;31m%s (%s)"%(pack.id, pack.sid, socketName, repr(self.route(pack.apiRet).__name__), pack.apiRet)
                self.printStr(pkOut, out, packColor, lineLen)
                if pack._TPack != None:
                    prOut = " [Parent TP %s]"%pack._TPack.id
                    self.printStr(prOut, outBlank, packColor, lineLen)
            else:
                pkOut = " [DP %s %s:%s] return %s"%(pack.id, pack.sid, socketName, pack.apiRet)
                self.printStr(pkOut, out, packColor, lineLen)
                if pack._TPack != None and pack._TPack._TPack != None:
                    prOut = " [Parent TP %s]"%pack._TPack._TPack.id
                    self.printStr(prOut, outBlank, packColor, lineLen)
            if socket._session != None:
                psOut = " [Session] %s"%(repr(socket._session))
                self.printStr(psOut, outBlank, packColor, lineLen)
            if socket._mo != None:
                pcOut = " [MO %s] %s"%(socket._mo.id, repr(socket._mo))
                self.printStr(pcOut, outBlank, packColor, lineLen)
            self.printStr(pbOut, outBlank, packColor, lineLen)
            self.printStr(' ' + '-'*(len(pkOut)-1), outBlank, packColor, lineLen)
        else:
            self.printStr(str[:lineLen], out, [49, strColor[0] - 10], lineLen)
            if len(str[lineLen:]) > 0: self.printStr(' ' + str[lineLen:], outBlank, [49, strColor[0] - 10], lineLen)

    def printStr(self, str, sob, pkclr, lineMaxLen):
        while len(str) != 0:
            print sob + "\033[%d;%dm%s\033[0m"%(pkclr[0], pkclr[1], str[:lineMaxLen])
            str = str[lineMaxLen:]
            if not len(str) == 0: str = ' '*8 + str
