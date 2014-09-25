# -*- coding: utf-8 -*-
# Started by Alan
# MainTained by Alan
# Contact: alan@sinosims.com

from twisted.internet.protocol import Factory 
from twisted.protocols.basic import LineReceiver
from simcore.core.gol import Gol
import re

class ToolsProtocol(LineReceiver):
    def connectionMade(self):
        wel = """
            Welcome Simcore Tools
            - Started by Alan
            - MainTained by Alan
            - Contact: alan@sinosims.com 
        """
        self.sendBack(wel)

    def lineReceived(self, line):
        m = re.match('AT\+([^ ]*) ([0-9a-f]*)', line)
        if m:
            sck = Gol().sckPool[m.group(2)]
            sck.sendTPack(1001, [sck._mo.id, 6, '0', 0x00, 5, 'AT+<6>\r', m.group(1)])
            self.sendBack('OK')
        elif line == "sock":
            sk = []
            for k, v in Gol().sckPool.items():
                sksrt = "%s %s Waiting TP %d\n"%(v.__class__.__name__, k, len(v._TPackWaitPeer))
                for m, n in v._session.items():
                    sksrt += "    %s\t%s\n"%(m, n)
                sk.append(sksrt)
            self.sendBack('\n'.join(sk))
        elif line == "stop":
            Gol().stop = True
            for sck in Gol().sckPool.values():
                sck.closeConnection(True)
                self.sendLine('.')
            self.sendBack(' Finish Stop\n')
        else:
            self.sendBack('Commands:\n    AT+<CMD> <sid>\n    sock\n    stop\n')

    def sendBack(self, str):
        self.sendLine(str.encode('utf8'))
        self.transport.write('%s:Simcore> '%(self.factory.channel))

class ToolsFactory(Factory):
    protocol = ToolsProtocol

    def __init__(self, channel):
        self.channel = channel
