# -*- coding: utf-8 -*-
# Started by Alan
# MainTained by Alan
# Contact: alan@sinosims.com

from simcore.core.shp import SHProtocol, SHPFactory, routeCode
from simcore.core.models import User, Chip, Box, Call, Sms
import time, re

class BoxMo(SHProtocol):
    _moClass = Box

    @routeCode(5000)
    def recvAllCard(self, dpack):
        pass

class BoxMoFactory(SHPFactory):
    protocol = BoxMo

class ChipMo(SHProtocol):
    _moClass = Chip

    @routeCode(101)
    def doAuth(self, tpack):
        # -*- TODO -*- : Use RSA encrypt package body
        d = self._session.save({ 'bid' : tpack.body[1], 'rol' :  '10' })
        d.addCallback(lambda x: self.returnDPack(200, [tpack.body[0], ''], tpack.id))
        return d

    @routeCode(102)
    def doLogin(self, tpack):
        # -*- TODO -*- : Use RSA encrypt package body

        (mod, imei, imsi, iccid, bid, lvl) = tpack.body
        lvl = lvl.replace('/dev/', '').replace('/', '_')
        c = self.setMo(Chip(imei))
        d = c.login(imsi, bid, self._session, self.factory.channel, mod, iccid, lvl)
        # d.addCallback(lambda x: self.returnDPack(200, [tpack.body[0], ''], tpack.id))
        d.addCallback(lambda at: self.cnum(tpack, at))
        return d

    def cnum(self, tpack, at):
        self.returnDPack(200, [tpack.body[0], ''], tpack.id)
        if at == 0 and self._mo['mod'] != 'SI3050':
            self.sendTPack(1001, [self._mo.id, 6, '0', 0x00, 5, 'AT+<6>\r', 'CNUM'])

    @routeCode(1001)
    def recvATcmd(self, dpack):
        # Deal with ATcmd Respond from box
        #   dpack._TPack.body[1] contains AT command id
        #       cmd 1 :     Dial
        #       cmd 2 :     Hangup
        #       cmd 3 :     Answer
        #       cmd 4 :     Send sms
        #       cmd 5 :     Read and Del sms
        #       cmd 6 :     Singel line command
        #       cmd 7 :     OK/ERROR return command
        #       cmd 8 :     Number return command
        #       cmd 9 :     Calling status return command
        #   see Wiki for more: http://192.168.6.66/projects/sim/wiki/AT%E5%91%BD%E4%BB%A4%E5%8D%8F%E8%AE%AE

        if not self._mo: raise Exception(401)
        d = None
        if dpack._TPack.body[1] == 1:
            if dpack.body[1] == 0:
                d = self._mo.startCall(dpack._TPack.body[2], dpack._PPack.senderId)
                d.addCallback(lambda x: self.returnToUser(dpack, dpack.apiRet, { 'stt' : 1 }))
            else:
                self.returnToUser(dpack, dpack.apiRet, { 'stt' : -1 })
        elif dpack._TPack.body[1] == 2:
            d = self.returnToUser(dpack, dpack.apiRet, { 'stt' : 0 })
        elif dpack._TPack.body[1] == 3:
            d = self._mo.answerCall(dpack._TPack.body[2], dpack._PPack.senderId)
            d.addCallback(lambda x: self.returnToUser(dpack, dpack.apiRet, { 'stt' : 1 }))
        elif dpack._TPack.body[1] == 4:
            d = self._mo.sendSMSOver(dpack._TPack.body[2])
            d.addCallback(lambda x: self.returnToUser(dpack, dpack.apiRet, None))
        elif dpack._TPack.body[1] == 6:
            d = None
            if dpack._TPack.body[6] == 'CNUM':
                match = re.search('\+CNUM: ".*","([^"]+)"', dpack.body[2])
                if match:
                    d = self._mo.setNum(match.group(1))
            elif dpack._TPack.body[6] == 'VTS':
                self.returnToUser(dpack, dpack.apiRet, None)
        return d

    @routeCode(1003)
    def recvOpenAudio(self, dpack): return None

    @routeCode(2001)
    def recvATresult(self, tpack):
        # Receive AT command broadcast from Box
        #   tpack.body[1] contains AT command id
        #       cmd 100 :   Calling status
        #       cmd 101 :   New sms
        #       cmd 200 :   Calling status changed, return '+CLCC' 
        #       cmd 201 :   sms Notice
        #   see Wiki for more: http://192.168.6.66/projects/sim/wiki/AT%E5%91%BD%E4%BB%A4%E5%8D%8F%E8%AE%AE
        #
        #   Under cmd 200, tpack.body[6] contains '+CLCC' information
        #       'OK'                                          :   Call closed
        #       '+CLCC: 1,0,3,0,0,"18682000169",129/r/nOK'    :   Dialing
        #       '+CLCC: 1,1,4,0,0,"13902658325",129/r/nOK'    :   Ringing
        #       '+CLCC: 1,1,0,0,0,"13902658325",129/r/nOK'    :   Answer connected
        #   see Wiki for more: http://192.168.6.66/projects/sim/wiki/CLCC%E5%91%BD%E4%BB%A4%E8%BF%94%E5%9B%9E
        #
        #   tpack.body[2] Calling Sequence id

        if not self._mo: raise Exception(401)
        if self._mo.id != tpack.body[0]: raise Exception(603)
        if tpack.body[1] == 200:
            cb = self.parseCLCC(tpack.body[6])
            d = cb(tpack.body[2]) if cb else None
        elif tpack.body[1] == 201:
            match = re.match('\+CMGL:.*\s+([0-9A-F]*)\s+', tpack.body[6])
            if not match: return None
            d = self._mo.smsing(match.group(1))
            d.addCallback(lambda sa: self.sendNews(sa[0], 4002, { 'cid' : self._mo.id, 'oth' : sa[1][0], 'msg' : sa[1][1], 'tim' : sa[1][2] }))
        else:
            d = None
        return d

    @routeCode(2002)
    def recvCardInfo(self, tpack):
        if not self._mo: raise Exception(401)
        d = self._mo.onl()
        d.addCallback(lambda x: self.returnDPack(200, None, tpack.id))
        return d

    def parseCLCC(self, clcc):
        typ = 0 if self._mo.get('mod', 'MG2639') == 'MG2639' else 1
        clccPair = [['^(OK)', '\+CLCC:0,9,(0)', self.endCall],
                   ['\+CLCC:.,.,4,.,.,"([^"]*)"', '\+CLCC:3,0,0(.*)', self.ringing],
                   ['\+CLCC:1,.,0,.,.,"([^"]*)"', '\+CLCC:1,0,0(.*)', self.changeCall]]
        for pr in clccPair:
            match = re.match(pr[typ], re.sub('\s', '', clcc))
            if match: return pr[2]
        return None

    def ringing(self, seq):
        d = self._mo.ringing(seq)
        if not d: return None
        d.addCallback(lambda sa: self.sendNews(sa[0], 4001, { 'cid' : self._mo.id, 'oth' : seq[0:-16], 'seq' : seq, 'tim' : int(time.time()) } ))
        d.addCallback(lambda x: None)
        return d

    def changeCall(self, seq):
        d = self._mo.changeCall()
        if not d: return None
        d.addCallback(lambda sa: self.sendNews(sa[0], 4004, { 'cid' : self._mo.id, 'seq' : seq, 'stt' : 0 } ))
        d.addCallback(lambda x: None)
        return d

    def endCall(self, seq):
        d = self._mo.endCall()
        if not d: return None
        d.addCallback(lambda sa: self.sendNews(sa[0], 4004, { 'cid' : self._mo.id, 'seq' : sa[1], 'stt' : -1 } ))
        d.addCallback(lambda x: None)
        return d

    def returnToUser(self, dpack, rt, body):
        self.passToSck(dpack._PPack.senderChannel, dpack._PPack.senderSid, dpack._PPack.packId, 0x80, rt, body)

    def connectionLost(self, reason):
        if self._mo:
            d = Box(self._mo['bid']).delChip(self._mo.id)
            d.addCallback(lambda x: SHProtocol.connectionLost(self, reason))
        else:
            d = SHProtocol.connectionLost(self, reason)
        return d

    # def errorRoutePack(self, failure, tpack):
    #     raise failure
    #     print 'error Route', failure
    #     if type(pack) == TPack: eDPack = pack.createDPack(int(failure.getErrorMessage()), None)
    #     elif pack.parentTPack() != None: eDPack = pack.parentTPack().createDPack(int(failure.getErrorMessage()), None)
    #     self.sendPack(eDPack)    

class ChipMoFactory(SHPFactory):
    protocol = ChipMo
