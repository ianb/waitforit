from setuptools import setup, find_packages
import sys, os

version = '0.3'

index_fn = os.path.join(os.path.dirname(__file__), 'docs', 'index.txt')
f = open(index_fn)
long_description = f.read()
f.close()

setup(name='WaitForIt',
      version=version,
      description="Provide an intermediate response when a WSGI application slow to respond",
      long_description=long_description,
      classifiers=[
        "Development Status :: 4 - Beta",
        "Environment :: Web Environment",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: MIT License",
        "Topic :: Internet :: WWW/HTTP :: WSGI",
        "Topic :: Internet :: WWW/HTTP :: WSGI :: Middleware",
      ],
      keywords='wsgi threads paste',
      author='Ian Bicking',
      author_email='ianb@colorstudy.com',
      url='http://pythonpaste.org/waitforit/',
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
