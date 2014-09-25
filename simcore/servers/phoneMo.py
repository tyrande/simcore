# -*- coding: utf-8 -*-
# Started by Alan
# MainTained by Alan
# Contact: alan@sinosims.com

from simcore.core.shp import SHProtocol, SHPFactory, routeCode
from simcore.core.gol import Gol
from simcore.core.models import User
import time, uuid, random

class PhoneMo(SHProtocol):
    _moClass = User

    @routeCode(3301)
    def doDial(self, tpack):
        if not self._mo: raise Exception(401)
        d = self._mo.chip(tpack.body['cid'])
        d.addCallback(lambda c: c.fineOth(tpack.body['oth']))
        d.addCallback(lambda co: self.sendToChip(co[0], 1001, [tpack.body['cid'], 1, tpack.body['seq'], 0x00, 5, "ATD<6>;\r", co[1]], tpack.id))
        return d

    @routeCode(3302)
    def doHangup(self, tpack):
        self.sendATcmd(tpack, [tpack.body['cid'], 2, tpack.body['seq'], 0x00, 5, "ATH\r"])

    @routeCode(3303)
    def doAnswer(self, tpack):
        self.sendATcmd(tpack, [tpack.body['cid'], 3, tpack.body['seq'], 0x00, 5, "ATA\r"])

    @routeCode(3401)
    def doSendSMS(self, tpack):
        if not self._mo: raise Exception(401)
        d = self._mo.sendSMS(tpack.body['cid'], tpack.body['oth'], tpack.body['msg'])
        d.addCallback(lambda cs: self.sendToChip(cs[0], 1001, [cs[0].id, 4, cs[1][0], 0x00, 5, '', 'AT+CMGS=%d\r'%cs[1][1], '%s\x1a'%cs[1][2]], tpack.id))

    @routeCode(3501)
    def doTalking(self, tpack):
        if not self._mo: raise Exception(401)
        tok = uuid.uuid1().hex
        srv = Gol().getVoiceTunnel()
        d = User.findByLogin(tpack.body["oth"])
        d.addCallback(lambda u: self.notiToUser(u, 4101, { 'oth' : self._mo.info['login'], 'hol' : tpack.body['hol'], 'lnk' : tpack.body['lnk'], 'srv' : srv, 'tok' : '01' + tok } ))
        d.addCallback(lambda x: self.returnDPack(200, { 'srv' : srv, 'tok' : '00' + tok }, tpack.id))
        return d

    @routeCode(3502)
    def doTalkingToChip(self, tpack):
        if not self._mo: raise Exception(401)
        tok = uuid.uuid1().hex
        srv = Gol().getCallTunnel()
        host, port = srv.split(':')
        d = self._mo.chip(tpack.body['oth'])
        d.addCallback(lambda c: self.sendToChip(c, 1003, [ c.id, 1,  host, int(port), '01' + tok ], tpack.id))
        d.addCallback(lambda x: self.returnDPack(200, { 'srv' : srv, 'tok' : '00' + tok }, tpack.id))
        return d

    @routeCode(3503)
    def doDTMF(self, tpack):
        self.sendATcmd(tpack, [tpack.body['cid'], 6, '0', 0x00, 5, "AT+<6>=%s\r"%tpack.body['chr'], "VTS"])

    def sendATcmd(self, tpack, body):
        if not self._mo: raise Exception(401)
        d = self._mo.chip(tpack.body['cid'])
        d.addCallback(lambda c: self.sendToChip(c, 1001, body, tpack.id))
        return d

    def sendToChip(self, c, rc, body, parentTPackId):
        return self.passToSck(c['chn'], c['sid'], parentTPackId, 0x00, rc, body)

class PhoneMoFactory(SHPFactory):
    protocol = PhoneMo

