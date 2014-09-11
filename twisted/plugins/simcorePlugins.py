# -*- coding: utf-8 -*-
# Started by Alan
# MainTained by Alan
# Contact: alan@sinosims.com

from twisted.application import internet
from twisted.application import service
from twisted.plugin import IPlugin
from twisted.python import usage
from twisted.python import log
from zope.interface import implements

from simcore.core.database import Srdb, SrPushdb
from simcore.core.gol import Gol
import ConfigParser, socket

def _emit(self, eventDict):
    text = log.textFromEventDict(eventDict)
    if not text: return

    timeStr = self.formatTime(eventDict['time'])
    log.util.untilConcludes(self.write, "%s %s\n" % (timeStr, text.replace("\n", "\n\t")))
    log.util.untilConcludes(self.flush)

class Options(usage.Options):
    optParameters = [["env", None, "test", "The environment of the running application, should be 'test' or 'productino'"],
                     ["pools", None, "../pools", "The dir contains application configuration"],
                     ["log", None, "./logs", "The dir contains application log"]]

class ServiceMaker(object):
    implements(service.IServiceMaker, IPlugin)
    tapname = "simcore"
    description = "Core of the simhub"
    options = Options

    def makeService(self, options):
        _srvs = service.MultiService()
        _channel = socket.gethostname()

        Gol().init(options["env"])
        application = service.Application("simcore") 

        self.initLog(application, options["env"], options["log"])

        self.initRedis("%s/%s/redis.ini"%(options["pools"], options["env"]))
        self.initTurnServerList("%s/%s/turnServer.ini"%(options["pools"], options["env"]))
        self.initServices(_srvs, _channel)

        _srvs.setServiceParent(application)
        
        Gol().setAPNs("%s/%s/ca/aps_development.pem"%(options["pools"], options["env"]), "%s/%s/ca/simhub_nopass.pem"%(options["pools"], options["env"]))
        return _srvs

    def initLog(self, app, env, logdir):
        if env == "production":
            from twisted.python.log import ILogObserver, FileLogObserver
            from twisted.python.logfile import DailyLogFile
            logfile = DailyLogFile("production.log", logdir)
            app.setComponent(ILogObserver, FileLogObserver(logfile).emit)
        else:
            log.FileLogObserver.emit = _emit

    def initRedis(self, redisini):
        config = ConfigParser.ConfigParser()
        config.read(redisini)
        [ rs.initRedisPool(config.get(rs.__class__.__name__, "host"), config.getint(rs.__class__.__name__, "port"), config.getint(rs.__class__.__name__, "db")) for rs in [Srdb(), SrPushdb()] ]

    def initServices(self, srvs, chn):
        from simcore.core.shp import RedisSubFactory
        from simcore.servers.chipMo import BoxMoFactory, ChipMoFactory
        from simcore.servers.phoneMo import PhoneMoFactory
        from simcore.servers.phoneNoti import PhoneNotiFactory

        _loadServ = [[BoxMoFactory, 8901], [ChipMoFactory, 8902], [PhoneMoFactory, 9901], [PhoneNotiFactory, 9902]]
        [ internet.TCPServer(srv[1], srv[0](chn)).setServiceParent(srvs) for srv in _loadServ ]
        
        internet.TCPClient(SrPushdb().host, SrPushdb().port, RedisSubFactory(chn)).setServiceParent(srvs)

    def initTurnServerList(self, turnini):
        with open(turnini, 'r') as f:
            Gol().setCallTunnels([ s.strip() for s in f.readlines() ])

serviceMaker = ServiceMaker()
