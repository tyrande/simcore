#!/usr/bin/env python
# encoding: utf-8

from fabric.api import local, cd, run, env

with open('../pools/production/coreServer.ini') as f:
    env.hosts = [ s.strip() for s in f.readlines() ]
env.key_filename = '~/.ssh/id_rsa.pub'

def bootstrap():
    run('mkdir opt')
    cd('opt')
    run('git clone git@deva.sinosims.com:simDCS.git')
    run('git clone git@deva.sinosims.com:pools.git')
    cd('simDCS')
    run('virtualenv --clear env')
    run('twisted -y run/production.tac')

def pack():
    local('python setup.py sdist --formats=gztar', capture=False)

def deploy():
    cd('~/opt/simDCS')
    run('git pull')
    # dist = local('python setup.py --fullname', capture=True).strip()
    
    # put('dist/%s.tar.gz'%dist, '/home/sim/opt/simDCS.tar.gz'%dist)
    # run('mkdir /')

def hello():
    print("Hi!")
    local("ls ~/")
    with cd('~/opt/'):
        run('ls')

