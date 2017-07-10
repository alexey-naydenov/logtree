from __future__ import print_function
from setuptools import setup, find_packages
from setuptools.command.test import test as TestCommand
import io
import codecs
import os
import sys

import logtree.logtree as logtree

here = os.path.abspath(os.path.dirname(__file__))

def read(*filenames, **kwargs):
    encoding = kwargs.get('encoding', 'utf-8')
    sep = kwargs.get('sep', '\n')
    buf = []
    for filename in filenames:
        with io.open(filename, encoding=encoding) as f:
            buf.append(f.read())
    return sep.join(buf)

long_description = read('README.md')

class PyTest(TestCommand):
    def finalize_options(self):
        TestCommand.finalize_options(self)
        self.test_args = []
        self.test_suite = True

    def run_tests(self):
        import pytest
        errcode = pytest.main(self.test_args)
        sys.exit(errcode)

setup(
    name='logtree',
    version=logtree.__version__,
    url='https://github.com/alexey-naydenov/logtree/',
    license='GPLv3',
    author='Alexey Naydenov',
    tests_require=['pytest'],
    install_requires=[],
    cmdclass={'test': PyTest},
    author_email='alexey.naydenov@linux.com',
    description='Add tree like structure to text logs',
    long_description=long_description,
    packages=find_packages(),
    scripts=['logtree/logtree.py'],
    include_package_data=True,
    platforms='any',
    test_suite='logtree.test.test_logtree',
    classifiers = [
        'Programming Language :: Python',
        'Development Status :: 4 - Beta',
        'Natural Language :: English',
        'Intended Audience :: Developers',
        'Operating System :: OS Independent',
    ],
    extras_require={
        'testing': ['pytest'],
    }
)
