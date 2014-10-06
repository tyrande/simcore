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

class ToolsProtocol(LineReceiver):
    def connectionMade(self):
        self.id = uuid.uuid4().hex
        self.mode = 'standby'
        self.tp = None
        self.monList = []
        wel = "Welcome Simcore Tools-%s 1.0.0 (%s)"%(self.factory.channel, time.strftime("%Y-%m-%d %H:%M:%S"))
        self.sendBack(wel)
        self.cmd = {'sockets' : [self.sockets, '["sockets", None]   list all sockets'],
                    'stopcore' : [self.stop, '["stopcore", None]    stop simcore service'],
                    'chip' : [self.chip, '["chip", <cpid>]  return chip model by id'],
                    'user' : [self.user, '["user", <uid>]  return user model by id'],
                    'box' : [self.box, '["box", <bid>]  return box model by id'],
                    # 'boxes' : [self.boxes, '["boxes", None]  return all online boxes'],
                    'cmd' : [self.sendCmdToChip, '["cmd", [<sid>, <apiRet>, <body>]]     send AT command to card'],
                    'mon' : [self.monitor, '["mon", [moid, moid, ..., moid]]      monitor chips or users or both'],
                    'monall' : [self.monitorAll, '["monall"]      monitor socket'],
                    'monstop' : [self.monitorStop, '["monstop"]     stop monitor']}
                    # 'set ([0-9a-f]*)', self.setSession, True, 'set <sid>'],
                    # 'unset', self.unsetSession, False, 'unset'],
                    # 'mon', self.monitor, False, 'mon'],
                    # 'cmd (.*)', self.command, True, 'cmd <routecode> <base64.b64encode(json.dumps(body))>'],
                    # '((user|chip|box|card|session|call|sms) ([0-9a-f]*))', self.showInfo, True, 'user|chip|box|card|session|call|sms <id>']]

    # def lineReceived(self, line):
    #     for c in self.cmd:
    #         m = re.match(c[0], line)
    #         if m:
    #             if c[2]:
    #                 c[1](m.group(1))
    #             else:
    #                 c[1]()
    #             return
    #     hp = ['Commands:'] + [ c[3] for c in self.cmd ]
    #     self.sendBack('\n    '.join(hp))

    def lineReceived(self, line):
        try:
            cmdarr = json.loads(base64.b64decode(line))
            m = self.cmd.get(cmdarr[0], None)
            if m: m[0](cmdarr[1])
        except Exception, e:
            # hp = ['Commands:'] + [ c[3] for c in self.cmd ]
            # self.sendBack('\n    '.join(hp))
            raise e
            print repr(e)

    def chip(self, id):
        d = defer.Deferred()
        d.addCallback(lambda x: Chip.findById(id))
        d.addCallback(lambda c: self.sendBack(json.dumps(c)))
        d.callback('')

    def user(self, id):
        d = defer.Deferred()
        d.addCallback(lambda x: User.findById(id))
        d.addCallback(lambda c: self.sendBack(json.dumps(c)))
        d.callback('')

    def box(self, id):
        d = defer.Deferred()
        d.addCallback(lambda x: Box(id).chips())
        d.addCallback(lambda c: self.sendBack(json.dumps(c)))
        d.callback('')

    def sockets(self, args):
        self.sendBack(json.dumps([ s._session for s in Gol().sckPool.values()]))

    def sendCmdToChip(self, args):
        sck = Gol().sckPool.get(args[0], None)
        if not sck: return self.sendBack('Chip is not online, socket %s is closed'%args[0])
        try:
            self.mode = 'command'
            self.factory.addMonitor(self)
            self.tp = sck.sendTPack(int(args[1]), args[2])
            _fs = Gol()._formatPack_('TO', sck, self.tp)
            self.sendLine(msgpack.packb(_fs[:-1])+'\r\n')
        except Exception, e:
            raise e
            self.sendLine(msgpack.packb('Command Format Error: <routecode> <body>')+'\r\n')

    def monitor(self, args):
        self.factory.addMonitor(self)
        self.monList = args
        self.mode = 'monitor'
        self.sendLine(msgpack.packb('Start Monitor %s ...'%' '.join(args))+'\r\n')
    #     _script = ""
    #     for cid in args[0]:
    #         _script += "redis.call('hset', 'Chip:%s:info', 'mon', 1)\n"%cid
    #     for uid in args[1]:
    #         _script += "redis.call('hset', 'User:%s:info', 'mon', 1)\n"%uid
    #     self.mode = 'monitor'
    #     self.sendBack('Start Monitor ...\n')

    def monitorAll(self, args):
        self.factory.addMonitor(self)
        self.mode = 'monitorall'
        self.sendLine(msgpack.packb('Start Monitor All ...')+'\r\n')

    def monitorStop(self, args):
        self.mode = 'standby'
        self.factory.delMonitor(self)
        self.sendLine('ok\r\n')

    # def monitor(self, sid):
    #     sck = Gol().sckPool.get(sid, None)
    #     if not sck: return self.sendBack('Chip is not online, socket %s is closed'%sid)
    #     self.sck = sck
    #     self.mode = 'monitor'
    #     sck.addMonitor(self)
    #     self.sendBack('Start Monitor %s %s ...\n'%(sck.__class__.__name__, sid))

    def show(self, cnt, moid, pid):
        if self.mode == 'monitorall':
            self.sendLine(cnt+'\r\n')
        if self.mode == 'monitor':
            if moid in self.monList:
                self.sendLine(cnt+'\r\n')
        if self.mode == 'command':
            if self.tp and self.tp.id == pid:
                self.factory.delMonitor(self)
                self.sendLine(cnt+'\r\n')
                self.tp = None
                self.mode = 'standby'
                
    def sendBack(self, str):
        self.sendLine(base64.b64encode(str.encode('utf8'))+'\r\n')

    def connectionLost(self, reason):
        self.factory.delMonitor(self)


###############################################################

    # def showInfo(self, mo):
    #     mcls, id = mo.split(' ')
    #     model = { 'user' : User, 'chip' : Chip, 'box' : Box, 'card' : Card, 'session' : Session, 'call' : Call, 'sms' : Sms }.get(mcls, None)
    #     if not model: return self.sendBack('No Model %s'%mcls)
    #     d = defer.Deferred()
    #     d.addCallback(lambda x: model.findById(id))
    #     d.addCallback(lambda m: self.showObj(m, mcls, id))
    #     d.callback('')

    # def showObj(self, obj, mcls, id):
    #     if not obj: return self.sendBack('No %s %s'%(mcls, id))
    #     si = ""
    #     for k, v in obj.items():
    #         si += "    %s\t%s\n"%(k, v)
    #     self.sendBack(si)

    def stop(self):
        Gol().stop = True
        for sck in Gol().sckPool.values():
            sck.closeConnection(True)
        self.sendBack('Finish Stop')

    # def sockets(self, args=None):
    #     sk = []
    #     for k, v in Gol().sckPool.items():
    #         sksrt = "%s %s Waiting TP %d\n"%(v.__class__.__name__, k, len(v._TPackWaitPeer))
    #         for m, n in v._session.items():
    #             sksrt += "    %s\t%s\n"%(m, n)
    #         sk.append(sksrt)
    #     self.sendBack('\n'.join(sk))

    # def setSession(self, sid):
    #     self.sid = sid
    #     sck = Gol().sckPool.get(self.sid, None)
    #     if not sck: return self.sendBack('Socket %s closed'%self.sid)
    #     sck._monitor = self
    #     self.sendBack('Use Socket: %s'%sid)

    # def unsetSession(self):
    #     sck = Gol().sckPool.get(self.sid, None)
    #     if not sck: return self.sendBack('Socket %s closed'%self.sid)
    #     sck._monitor = None
    #     self.sendBack('Leave Socket %s'%self.sid)
    #     self.sid = None

    # def command(self, args):
    #     if not self.sid: return self.sendBack('Set session id first: set <sid>')
    #     sck = Gol().sckPool.get(self.sid, None)
    #     if not sck: return self.sendBack('Socket %s closed'%self.sid)
    #     try:
    #         rb = args.split(' ')
    #         self.tp = sck.sendTPack(int(rb[0]), json.loads(base64.b64decode(rb[1])))
    #         self.mode = 'command'
    #     except:
    #         self.sendBack('Command Format Error: <routecode> <base64.b64encode(json.dumps(body))>')

    # def monitor(self):
    #     if not self.sid: return self.sendBack('Set session id first: set <sid>')
    #     sck = Gol().sckPool.get(self.sid, None)
    #     if not sck: return self.sendBack('Socket %s closed'%self.sid)
    #     self.mode = 'monitor'
    #     self.sendBack('Start Monitor %s %s'%(sck.__class__.__name__, self.sid))

    # def show(self, pack):
    #     if self.mode == 'monitor':
    #         self.sendBack('%s [%s] %s %s %s'%(pack.id, pack.sid, pack._flags, pack.apiRet, pack.body))
    #     if self.mode == 'command':
    #         if self.tp.id == pack.id and pack._flags == 0x80:
    #             cmd = '%s [%s] %s %s %s\n'%(self.tp.id, self.tp.sid, self.tp._flags, self.tp.apiRet, self.tp.body)
    #             cmd += '%s [%s] %s %s %s'%(pack.id, pack.sid, pack._flags, pack.apiRet, pack.body)
    #             self.sendBack(cmd)
    #             self.mode = 'standby'

class ToolsFactory(Factory):
    protocol = ToolsProtocol

    def __init__(self, channel):
        self.channel = channel
        self.ms = {}

    def addMonitor(self, sck):
        self.ms[sck.id] = sck

    def delMonitor(self, sck):
        if self.ms.has_key(sck.id):
            del self.ms[sck.id]
