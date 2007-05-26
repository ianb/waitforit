from setuptools import setup, find_packages
import sys, os

version = '0.1'

setup(name='WaitForIt',
      version=version,
      description="Provide an intermediate response when a WSGI application slow to respond",
      long_description="""\
""",
      classifiers=[], # Get strings from http://www.python.org/pypi?%3Aaction=list_classifiers
      keywords='wsgi threads paste',
      author='Ian Bicking',
      author_email='ianb@colorstudy.com',
      #url='http://pythonpaste.org/waitforit/',
      license='MIT',
      packages=find_packages(exclude=['ez_setup', 'examples', 'tests']),
      include_package_data=True,
      zip_safe=False,
      install_requires=[
          'PasteDeploy',
          'Paste',
          'simplejson',
      ],
      entry_points="""
      [paste.filter_app_factory]
      main = waitforit.wsgiapp:make_filter
      """,
      )
