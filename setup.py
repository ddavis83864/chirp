import os

from setuptools import setup
from setuptools import find_packages

# Read chirp/_version.py's source directly (not `import chirp`, which
# would both depend on chirp's own dependencies before this package is
# even built, and require executing chirp/__init__.py's own version
# lookup for no reason -- see that module's docstring). See it for the
# single, shared implementation of "how do we turn `git describe`
# output into a version string" that chirp/__init__.py also uses.
_REPO_ROOT = os.path.dirname(os.path.abspath(__file__))
_version_ns = {}
with open(os.path.join(_REPO_ROOT, 'chirp', '_version.py')) as f:
    exec(f.read(), _version_ns)
_VERSION = _version_ns['derive_version_from_git'](_REPO_ROOT) or '0.0.0.dev0'

setup(name='chirp',
      description='A cross-platform cross-radio programming tool',
      packages=find_packages(include=["chirp*"]),
      include_package_data=True,
      version=_VERSION,
      url='https://chirp.danplanet.com',
      python_requires=">=3.10,<4",
      install_requires=[
          'pyserial',
          'requests',
          'yattag',
          'suds',
          'lark',
      ],
      extras_require={
          'wx': ['wxPython'],
      },
      entry_points={
          'console_scripts': [
              "chirp=chirp.wxui:chirpmain",
              "chirpc=chirp.cli.main:main",
              "experttune=chirp.cli.experttune:main",
          ],
      },
      )
