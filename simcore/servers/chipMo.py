# -*- coding: utf-8 -*-
# Started by Alan
# MainTained by Alan
# Contact: alan@sinosims.com

from simcore.core.shp import SHProtocol, SHPFactory, routeCode
from simcore.core.models import User, Chip, Box, Call
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

        (mod, imei, imsi, bid) = tpack.body[0].split('\n')
        c = self.setMo(Chip(imei))
        d = c.login(imsi, bid, self._session, self.factory.channel, mod)
        d.addCallback(lambda x: self.returnDPack(200, [tpack.body[0], ''], tpack.id))
        return d

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

        if self._mo == None: raise Exception(401)
        if dpack._TPack.body[1] == 1:
            d = self._mo.startCall(dpack._TPack.body[2], dpack._PPack.senderId)
            d.addCallback(lambda x: self.returnToUser(dpack, dpack.apiRet, { 'stt' : 1 }))
        elif dpack._TPack.body[1] == 2:
            d = self.returnToUser(dpack, dpack.apiRet, { 'stt' : 0 })
        elif dpack._TPack.body[1] == 3:
            d = self._mo.answerCall(dpack._TPack.body[2], dpack._PPack.senderId)
            d.addCallback(lambda x: self.returnToUser(dpack, dpack.apiRet, { 'stt' : 1 }))
        else:
            d = None
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

        # if self._mo.id != tpack.body[0]: raise Exception(603)
        if tpack.body[1] == 200:
            cb = self.parseCLCC(tpack.body[6])
            d = cb(tpack.body[2]) if cb else None
        else:
            d = None
        return d

    @routeCode(2002)
    def recvCardInfo(self, tpack):
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

    def endCall(self, seq):
        d = self._mo.endCall()
        d.addCallback(lambda uc: self.notiToUsers(uc[0], 4004, { 'cid' : self._mo.id, 'seq' : uc[1], 'stt' : -1 } ))
        d.addCallback(lambda x: None)
        return d

    def ringing(self, seq):
        d = self._mo.ringing(seq)
        d.addCallback(lambda uc: self.notiToUsers(uc[0], 4001, { 'cid' : self._mo.id, 'oth' : seq[0:-16], 'seq' : seq, 'tim' : int(time.time()) }, True, u'%s \u6765\u7535'%seq[0:-16] ))
        d.addCallback(lambda x: None)
        return d

    def changeCall(self, seq):
        d = self._mo.callingUser()
        d.addCallback(lambda u: self.notiToUser(u, 4004, { 'cid' : self._mo.id, 'seq' : seq, 'stt' : 0 } ))
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
