# -*- coding: utf-8 -*-
# Started by Alan
# MainTained by Alan
# Contact: alan@sinosims.com

from simcore.core.shp import SHProtocol, SHPFactory, routeCode
from simcore.core.models import User, Call
import time

class PhoneNoti(SHProtocol):
    _moClass = User

    @routeCode(401)
    def doNews(self, tpack):
        if not self._mo: raise Exception(401)
        d = self._session.save({ 'chn' : self.factory.channel })
        d.addCallback(lambda x: self._mo.addNewsSession(self._session.id))
        d.addCallback(lambda x: self._mo.chips())
        d.addCallback(lambda cps: Call.findAllByIds([ c.get('cll', '') for c in cps]))
        d.addCallback(lambda cs: self.returnDPack(200, [{'cid' : c['cpid'], 'oth' : c['oth'], 'seq' : c['id'], 'tim' : v['st']} for c in cs if (c.get('uid', '') == 'None' and time.time() - v['st'] < 60) ], tpack.id))
        return d

    @routeCode(402)
    def doPushNews(self, tpack):
        if not self._mo: raise Exception(401)
        d = self._mo.save({ 'atk' : tpack.body[0]})
        d.addCallback(lambda x: self.returnDPack(200, [], tpack.id))
        return d

    @routeCode(4001)
    def recvRing(self, dpack): return None

    @routeCode(4004)
    def recvCalling(self, dpack): return None

    @routeCode(4101)
    def recvTalking(self, dpack): return None

    def connectionLost(self, reason):
        if self._mo: 
            d = self._mo.delNewsSession(self._session.id)
            d.addCallback(lambda x: SHProtocol.connectionLost(self, reason))
        else:
            SHProtocol.connectionLost(self, reason)

class PhoneNotiFactory(SHPFactory):
    protocol = PhoneNoti
    _sckType = 'news'
