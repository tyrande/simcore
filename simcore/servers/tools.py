# -*- coding: utf-8 -*-
# Started by Alan
# MainTained by Alan
# Contact: alan@sinosims.com

from twisted.internet import defer
from twisted.internet.protocol import Factory
from twisted.protocols.basic import LineReceiver
from simcore.core.models import User, Chip, Box, Card, Session, Call, Sms
from simcore.core.gol import Gol
import re, time, json, base64, uuid, msgpack
import nacl.utils, nacl.secret, nacl.public

class ToolsProtocol(LineReceiver):
    def __init__(self):
        self.id = uuid.uuid4().hex
        self.mode = 'standby'
        self.tp = None
        self.monList = []
        self.cmd = {'wel' : [self.wel, '["wel", None]   request welcome line'],
                    'sockets' : [self.sockets, '["sockets", None]   list all sockets'],
                    'stopcore' : [self.stop, '["stopcore", None]    stop simcore service'],
                    'chip' : [self.chip, '["chip", <cpid>]  return chip model by id'],
                    'user' : [self.user, '["user", <uid>]  return user model by id'],
                    'box' : [self.box, '["box", <bid>]  return box model by id'],
                    # 'boxes' : [self.boxes, '["boxes", None]  return all online boxes'],
                    'cmd' : [self.sendCmdToChip, '["cmd", [<sid>, <apiRet>, <body>]]     send AT command to card'],
                    'mon' : [self.monitor, '["mon", [moid, moid, ..., moid]]      monitor chips or users or both'],
                    'monall' : [self.monitorAll, '["monall"]      monitor socket'],
                    'monstop' : [self.monitorStop, '["monstop"]     stop monitor']}
        self.key = nacl.utils.random(nacl.secret.SecretBox.KEY_SIZE)
        self.box = nacl.secret.SecretBox(self.key)

    def connectionMade(self):
        # wel = "Welcome Simcore Tools-%s 1.0.0 (%s)"%(self.factory.channel, time.strftime("%Y-%m-%d %H:%M:%S"))
        # self.sendOut(wel)
        nonce = nacl.utils.random(nacl.public.Box.NONCE_SIZE)
        self.sendPlan(self.factory.box.encrypt(self.key, nonce))
        # self.sendBack(wel)

    def lineReceived(self, line):
        try:
            # cmdarr = json.loads(base64.b64decode(line))
            cmdarr = msgpack.unpackb(self.box.decrypt(line), encoding = 'utf-8')
            m = self.cmd.get(cmdarr[0], None)
            if m: m[0](cmdarr[1])
        except Exception, e:
            print repr(e)

    def wel(self, args):
        w = "Welcome Simcore Tools-%s 1.0.0 (%s)"%(self.factory.channel, time.strftime("%Y-%m-%d %H:%M:%S"))
        self.sendOut(w)

    def chip(self, id):
        d = defer.Deferred()
        d.addCallback(lambda x: Chip.findById(id))
        d.addCallback(lambda c: self.sendOut(c))
        # d.addCallback(lambda c: self.sendBack(json.dumps(c)))
        d.callback('')

    def user(self, id):
        d = defer.Deferred()
        d.addCallback(lambda x: User.findById(id))
        d.addCallback(lambda c: self.sendOut(c))
        # d.addCallback(lambda c: self.sendBack(json.dumps(c)))
        d.callback('')

    def box(self, id):
        d = defer.Deferred()
        d.addCallback(lambda x: Box(id).chips())
        d.addCallback(lambda c: self.sendOut(c))
        # d.addCallback(lambda c: self.sendBack(json.dumps(c)))
        d.callback('')

    def sockets(self, args):
        self.sendOut([ s._session for s in Gol().sckPool.values()])
        # self.sendBack(json.dumps([ s._session for s in Gol().sckPool.values()]))

    def sendCmdToChip(self, args):
        sck = Gol().sckPool.get(args[0], None)
        if not sck: return self.sendOut('Chip is not online, socket %s is closed'%args[0])
        # if not sck: return self.sendBack('Chip is not online, socket %s is closed'%args[0])
        try:
            self.mode = 'command'
            self.factory.addMonitor(self)
            self.tp = sck.sendTPack(int(args[1]), args[2])
            _fs = Gol()._formatPack_('TO', sck, self.tp)
            self.sendOut(msgpack.packb(_fs[:-1])+'\r\n', True)
            # self.sendLine(msgpack.packb(_fs[:-1])+'\r\n')
        except Exception, e:
            self.sendOut('Command Format Error: <routecode> <body>')
            # self.sendLine(msgpack.packb('Command Format Error: <routecode> <body>')+'\r\n')

    def monitor(self, args):
        self.factory.addMonitor(self)
        self.monList = args
        self.mode = 'monitor'
        self.sendOut('Start Monitor %s ...'%' '.join(args))
        # self.sendLine(msgpack.packb('Start Monitor %s ...'%' '.join(args))+'\r\n')

    def monitorAll(self, args):
        self.factory.addMonitor(self)
        self.mode = 'monitorall'
        self.sendOut('Start Monitor All ...')
        # self.sendLine(msgpack.packb('Start Monitor All ...')+'\r\n')

    def monitorStop(self, args):
        self.mode = 'standby'
        self.factory.delMonitor(self)
        self.sendOut('ok')
        # self.sendLine('ok\r\n')

    def show(self, cnt, moid, pid):
        if self.mode == 'monitorall':
            self.sendOut(cnt, True)
            # self.sendLine(cnt+'\r\n')
        if self.mode == 'monitor':
            if moid in self.monList:
                self.sendOut(cnt, True)
                # self.sendLine(cnt+'\r\n')
        if self.mode == 'command':
            if self.tp and self.tp.id == pid:
                self.factory.delMonitor(self)
                self.sendOut(cnt, True)
                # self.sendLine(cnt+'\r\n')
                self.tp = None
                self.mode = 'standby'

    def sendOut(self, cnt, packed=False):
        nonce = nacl.utils.random(nacl.secret.SecretBox.NONCE_SIZE)
        if packed:
            self.sendLine(self.box.encrypt(cnt, nonce)+'\r\n')
        else:
            self.sendLine(self.box.encrypt(msgpack.packb(cnt), nonce)+'\r\n')
                
    def sendPlan(self, cnt):
        self.sendLine(msgpack.packb(cnt)+'\r\n')

    # def sendBack(self, str):
        # self.sendLine(base64.b64encode(str.encode('utf8'))+'\r\n')

    def connectionLost(self, reason):
        self.factory.delMonitor(self)

###############################################################

    def stop(self):
        Gol().stop = True
        for sck in Gol().sckPool.values():
            sck.closeConnection(True)
        # self.sendBack('Finish Stop')
        self.sendOut('Finish Stop')

class ToolsFactory(Factory):
    protocol = ToolsProtocol

    def __init__(self, channel):
        self.channel = channel
        self.ms = {}
        self.box = nacl.public.Box(nacl.public.PrivateKey('\xd5J\xde\xc9\xd1\x13\x8c`B\xa4\xe7N\x9b]\xdd\x135=S*.\xf3)>\x19:[7)\xa8\xd6{'), nacl.public.PublicKey('\xb9q\xd3w\xb9\xfb@\x1d\xc6N\x84\x8f6bU2\xfa\xc4\x01Z]4g2\x07\xedx\x84\xfe\x82Zk'))

    def addMonitor(self, sck):
        self.ms[sck.id] = sck

    def delMonitor(self, sck):
        if self.ms.has_key(sck.id):
            del self.ms[sck.id]
