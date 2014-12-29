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
        # if tpack.body and tpack.body[0][0] == '1': raise Exception(407)
        d = self._mo.newsHeart(self._session, self.factory.channel, tpack.body)
        d.addCallback(lambda cs: self.returnDPack(200, cs, tpack.id))
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
