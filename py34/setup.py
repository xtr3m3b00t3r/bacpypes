#!/usr/bin/env python
# -*- coding: utf-8 -*-

from setuptools import setup

setup(
    name="bacpypes",
    version="0.19.0",
    description="BACnet Communications Library",
    long_description="BACpypes provides a BACnet application layer and network layer written in Python for daemons, scripting, and graphical interfaces.",
    author="Joel Bender",
    author_email="joel@carrickbender.com",
    url="https://github.com/JoelBender/bacpypes",
    packages=[
        'bacpypes',
        'bacpypes.local',
        'bacpypes.service',
    ],
    package_dir={
        '': '.',
    },
    include_package_data=True,
    install_requires=[],
    license="MIT",
    zip_safe=False,
    classifiers=[
        'Development Status :: 2 - Pre-Alpha',
        'Intended Audience :: Developers',
        'License :: OSI Approved :: BSD License',
        'Natural Language :: English',
        'Programming Language :: Python :: 3',
        'Programming Language :: Python :: 3.13',
    ],
    python_requires='>=3.13',
)
