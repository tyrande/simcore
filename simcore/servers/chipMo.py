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
        d = c.save({ 'cdid' : imsi, 'bid' : bid, 'sid' : self._session.id, 'chn' : self.factory.channel, 'mod' : mod })
        d.addCallback(lambda c: Box(bid).addChip(c.id))
        d.addCallback(lambda x: self._session.update({ self._moClass.__name__ : c.id }))
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
        d = User.findById(dpack._PPack.senderId)
        if dpack._TPack.body[1] == 1:
            d.addCallback(lambda u: self._mo.startCall(dpack._TPack.body[2], u.id, dpack._TPack.body[6], 0))
        elif dpack._TPack.body[1] == 2:
            # d.addCallback(lambda u: self._mo.endCall(dpack._TPack.body[2]))
            pass
        elif dpack._TPack.body[1] == 3:
            d.addCallback(lambda u: self._mo.answerCall(dpack._TPack.body[2], u.id))
        else:
            d = None
        if d: d.addCallback(lambda cl: self.returnToUser(dpack, dpack.apiRet, { 'stt' : cl.get('stt', 0) }))
        return d

    @routeCode(1002)
    def recvQueryCard(self, dpack): return None
    #     if dpack.apiRet != 200: raise Exception(dpack.apiRet)
    #     if self._mo.id != dpack.body[0]: raise Exception(603)
    #     info = { 'sig' : dpack.body[1], 'onl' : dpack.body[2], 'stt' : dpack.body[3], 'set' : dpack.body[4]}
    #     d = self._mo.update(info)
    #     d.addCallback(lambda x: [dpack.parentTPack().createDPack(dpack.apiRet, info.update({'cid' : self._mo.id}))])
    #     return d

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

        # if self._mo.id != tpack.body[0]: raise Exception(603)
        if tpack.body[1] == 200:
            cb, oth = self.parseCLCC(tpack.body[6])
            d = cb(tpack, oth) if cb else None
        else:
            d = None
        return d

    @routeCode(2002)
    def recvCardInfo(self, tpack):
        d = self._session.expire()
        d.addCallback(lambda x: self.returnDPack(200, None, tpack.id))
        return d

    def parseCLCC(self, clcc):
        typ = 0 if self._mo.get('typ', 'MG2639') == 'MG2639' else 1
        clccPair = [['^(OK)', '+CLCC:0,9,(0)', self.endCall],
                   ['\+CLCC:.,.,4,.,.,"([^"]+)"', '+CLCC:3,0,0,(.*)', self.ringing],
                   ['\+CLCC:1,.,0,.,.,"([^"]+)"', '+CLCC:1,0,0,(.*)', self.changeCall]]
        for pr in clccPair:
            match = re.match(pr[typ], re.sub('\s', '', clcc))
            if match: return pr[2], match.group(1)
        return None, None

    def endCall(self, tpack, oth):
        # d = self._mo.endCall(tpack.body[2])
        clid = self._mo.get('cll', None)
        d = self._mo.endCall(clid)
        d.addCallback(lambda cl: cl.reload())
        d.addCallback(lambda cl: User.findById(cl['uid']))
        d.addCallback(lambda u: self.notiToUser(u, 4004, { 'cid' : self._mo.id, 'seq' : clid, 'stt' : -1 } ))
        d.addCallback(lambda x: None)
        return d

    def ringing(self, tpack, oth):
        d = self._mo.startCall(tpack.body[2], '', oth, 1)
        d.addCallback(lambda x: self._mo.users())
        d.addCallback(lambda us: self.notiToUsers(us, 4001, { 'cid' : self._mo.id, 'oth' : oth, 'seq' : tpack.body[2], 'tim' : int(time.time()) } ))
        d.addCallback(lambda x: None)
        return d

    def changeCall(self, tpack, oth):
        d = Call(tpack.body[2]).reload()
        # d = Call(self._mo.get('cll', None)).reload()
        d.addCallback(lambda cl: User.findById(cl['uid']))
        d.addCallback(lambda u: self.notiToUser(u, 4004, { 'cid' : self._mo.id, 'seq' : tpack.body[2], 'stt' : 0 } ))
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
