#!/usr/bin/env python
# encoding: utf-8

from fabric.api import local, cd, run, put, env

env.hosts = [ '114.215.209.188', '115.29.241.227' ]
# env.hosts = [ '115.29.241.227' ]
env.user = 'sim'
env.key_filename = '~/.ssh/id_rsa.pub'

def deploy():
    local('python setup.py sdist --formats=gztar', capture=False)
    dist = local('python setup.py --fullname', capture=True).strip()
    put('dist/%s.tar.gz'%dist, '/home/sim/tmp/simcore.tar.gz')
    with cd('/home/sim/tmp/'):
        run('tar zxvf /home/sim/tmp/simcore.tar.gz')
        with cd('/home/sim/tmp/%s'%dist):
            run('/home/sim/opt/simenv/bin/python setup.py install --single-version-externally-managed --root=/')
    
    run('rm -rf /home/sim/tmp/%s /home/sim/tmp/simcore.tar.gz'%dist)

def remote_start():
    with cd('/home/sim/opt/simcore'):
        run('/home/sim/opt/simenv/bin/twistd simcore --pools=/home/sim/opt/pools/ --env=production --logfile=/home/sim/opt/simcore/logs/simcore.log')

def remote_stop():
    run('kill `cat /home/sim/opt/simcore/twistd.pid`')

def remote_restart():
    remote_stop()
    remote_start()
