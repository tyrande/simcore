from setuptools import setup, find_packages

setup(
    name = "simcore",
    version = "0.1.1",
    author = "Alan Shi",
    author_email = "alan@sinosims.com",

    packages = find_packages() + ['twisted.plugins'],
    include_package_data = True,

    url = "http://www.sinosims.com",
    description = "SimHub Core Engine",
    
    package_data = {"twisted" : ["plugins/simcorePlugins.py"]},

    install_requires = ["twisted", "apns", "msgpack-python"],
)
