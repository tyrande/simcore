# -*- coding: utf-8 -*-
# Started by Alan
# MainTained by Alan
# Contact: alan@sinosims.com

from simcore.core.shp import SHProtocol, SHPFactory, routeCode
from simcore.core.gol import Gol
from simcore.core.models import User
import time, uuid

class PhoneMo(SHProtocol):
    _moClass = User

    @routeCode(201)
    def doAuth(self, tpack):
        # -*- TODO -*- : Use RSA encrypt package body

        d = self._session.save({ 'rol' : tpack.body[1] })
        d.addCallback(lambda x: self.returnDPack(200, ['asdf'*4, 'x'*12], tpack.id))
        return d

    @routeCode(202)
    def doLogin(self, tpack):
        # -*- TODO -*- : Use RSA encrypt package body

        (login, pwd, imei) = tpack.body[0].split('\n')
        # d = User.findAndCheckByLogin(login, pwd)
        # d.addCallback(lambda u: self.setUserToSession(u, imei))
        d = self._session.save({ self._moClass.__name__ : '0f9c509afcd711e383b700163e0212e4', 'imei' : imei })
        d.addCallback(lambda x: self.returnDPack(200, None, tpack.id))
        return d

    @routeCode(203)
    def doRegister(self, tpack):
        # -*- TODO -*- : Use RSA encrypt package body

        (login, pwd, imei) = tpack.body[0].split('\n')
        # d = User.create(login, pwd)
        # d.addCallback(lambda u: self.setUserToSession(u, imei))
        d = self._session.save({ self._moClass.__name__ : '0f9c509afcd711e383b700163e0212e4', 'imei' : imei })
        d.addCallback(lambda x: self.returnDPack(200, None, tpack.id))
        return d

    # def setUserToSession(self, u, imei):
    #     # Set User to current Session
    #     #   Use for doLogin and doRegister, accept defer param
    #     #   @param u:       User which pass the password auth
    #     #   @param imei:    User's UDID of the Device

    #     self.setMo(u)
    #     d = u.save({ 'imei' : imei, 'rol' : self._session['rol'], 'sid' : self._session.id, 'chn' : self.factory.channel })
    #     d.addCallback(lambda u: self._session.save({ self._moClass.__name__ : u.id, 'imei' : imei }))
    #     return d

    @routeCode(3001)
    def doListCard(self, tpack):
        if self._mo == None: raise Exception(401)
        d = self._mo.chips()
        d.addCallback(lambda cps: self.returnDPack(200, [ { 'cid' : c.id, 'cno' : c.get('cno', ''), 'sig' : c.get('sig', 0), 'onl' : c.get('onl', 0) } for c in cps], tpack.id))
        return d

    @routeCode(3002)
    def doGetCard(self, tpack): return None
    #     if self._mo == None: raise Exception(401)
    #     d = self._mo.card(tpack.body['cid'])
    #     d.addCallback(lambda c: c.getCard(tpack))
    #     return d

    @routeCode(3003)
    def doAddCard(self, tpack):
        d = self._mo.addCard(tpack)
        d.addCallback(lambda x: tpack.createDPack(200, None))
        return d

    @routeCode(3301)
    def doDial(self, tpack):
        self.sendATcmd(tpack, [tpack.body['cid'], 1, tpack.body['seq'], 0x00, 5, "ATD<6>;\r", tpack.body['oth']])

    @routeCode(3302)
    def doHangup(self, tpack):
        self.sendATcmd(tpack, [tpack.body['cid'], 2, tpack.body['seq'], 0x00, 5, "ATH\r"])

    @routeCode(3303)
    def doAnswer(self, tpack):
        self.sendATcmd(tpack, [tpack.body['cid'], 3, tpack.body['seq'], 0x00, 5, "ATA\r"])

    @routeCode(3501)
    def doTalking(self, tpack):
        if self._mo == None: raise Exception(401)
        tok = uuid.uuid1().hex
        srv = Gol().getVoiceTunnel()
        d = User.findByLogin(tpack.body["oth"])
        d.addCallback(lambda u: self.notiToUser(u, 4101, { 'oth' : self._mo.info['login'], 'hol' : tpack.body['hol'], 'lnk' : tpack.body['lnk'], 'srv' : srv, 'tok' : '01' + tok } ))
        d.addCallback(lambda x: self.returnDPack(200, { 'srv' : srv, 'tok' : '00' + tok }, tpack.id))
        return d

    @routeCode(3502)
    def doTalkingToChip(self, tpack):
        if self._mo == None: raise Exception(401)
        tok = uuid.uuid1().hex
        srv = Gol().getCallTunnel()
        host, port = srv.split(':')
        d = self._mo.chip(tpack.body['oth'])
        d.addCallback(lambda c: self.sendToChip(c, 1003, [ c.id, 1,  host, int(port), '01' + tok ], tpack.id))
        d.addCallback(lambda x: self.returnDPack(200, { 'srv' : srv, 'tok' : '00' + tok }, tpack.id))
        return d

    def sendATcmd(self, tpack, body):
        if self._mo == None: raise Exception(401)
        d = self._mo.chip(tpack.body['cid'])
        d.addCallback(lambda c: self.sendToChip(c, 1001, body, tpack.id))
        return d

    def sendToChip(self, c, rc, body, parentTPackId):
        return self.passToSck(c['chn'], c['sid'], parentTPackId, 0x00, rc, body)

class PhoneMoFactory(SHPFactory):
    protocol = PhoneMo

