#!/usr/bin/env python3.6

from setuptools import setup

setup(name='auto_usb_attach',
      version='0.9.1',
      packages=['auto_usb_attach'],
      install_requires=['pyxs >= 0.4.1', 'pyudev >= 0.21.0', 'psutil >= 5.0.0', 'pyyaml >= 3.12'],
      entry_points={'console_scripts': ['auto_usb_attach = auto_usb_attach.__main__:main']})
