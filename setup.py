from __future__ import print_function

import io
import sys
from setuptools import setup, find_packages
from setuptools.command.test import test as TestCommand

import logtree.logtree as logtree


def read(*filenames, **kwargs):
    encoding = kwargs.get('encoding', 'utf-8')
    sep = kwargs.get('sep', '\n')
    buf = []
    for filename in filenames:
        with io.open(filename, encoding=encoding) as fileobj:
            buf.append(fileobj.read())
    return sep.join(buf)


setup(
    name='logtree',
    version=logtree.__VERSION__,
    url='https://github.com/alexey-naydenov/logtree/',
    license='GPLv3',
    author='Alexey Naydenov',
    setup_requires=['pytest-runner'],
    tests_require=['pytest'],
    install_requires=[],
    author_email='alexey.naydenov@linux.com',
    description='Add tree like structure to text logs',
    long_description=read('README.md'),
    packages=find_packages(),
    scripts=['logtree/logtree.py'],
    include_package_data=True,
    platforms='any',
    classifiers=[
        'Programming Language :: Python',
        'Development Status :: 4 - Beta',
        'Natural Language :: English',
        'Intended Audience :: Developers',
    ],
)
