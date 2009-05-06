import threading
import urllib
from itertools import count
import time
import md5
from webob import Request, Response
from webob.exc import *
from tempita import HTMLTemplate
import simplejson
import re
import sys
import os

counter = count()

def make_id():
    value = str(time.time()) + str(counter.next())
    h = md5.new(value).hexdigest()
    return h

class WaitForIt(object):

    template_option_defaults = dict(
        css=None,
        extra_css=None,
        message=None,
        css_link=None,
        )

    def __init__(self, app, time_limit=10, poll_time=10,
                 template=None, template_filename=None,
                 template_options=None):
        self.app = app
        self.time_limit = time_limit
        self.poll_time = poll_time
        self.pending = {}
        if template and template_filename:
            raise TypeError(
                "You may not pass both a template and a template_filename argument")
        if not template and not template_filename:
            template_filename = os.path.join(os.path.dirname(__file__), 'response.tmpl')
        if template_filename:
            template = HTMLTemplate.from_filename(template_filename)
        if isinstance(template, basestring):
            template = HTMLTemplate(template)
        self.template = template
        if template_options is None:
            template_options = {}
        self.template_options = template_options

    def __call__(self, environ, start_response):
        assert not environ['wsgi.multiprocess'], (
            "WaitForIt does not work in a multiprocess environment")
        req = Request(environ)
        if req.path_info.startswith('/.waitforit/'):
            req.path_info_pop()
            return self.check_status(req, start_response)
        try:
            id = req.GET.get('waitforit_id')
            if id:
                if id in self.pending:
                    return self.send_wait_page(req, start_response, id=id)
                else:
                    # Bad id, remove it from QS:
                    qs = req.environ['QUERY_STRING']
                    qs = re.sub(r'&?waitforit_id=[a-f0-9]*', '', qs)
                    qs = re.sub(r'&send$', '', qs)
                    req.environ['QUERY_STRING'] = qs
                    # Then redirect:
                    exc = HTTPMovedPermanently(location=req.url)
                    return exc(environ, start_response)
        except KeyError:
            # Fresh request
            pass
        
        if not req.accept.accept_html():
            # Can't catch requests anyway; probably a request for an
            # image or something like that
            return self.app(environ, start_response)
        data = []
        progress = {}
        req.environ['waitforit.progress'] = progress
        event = threading.Event()
        self.launch_application(environ, data, event, progress)
        event.wait(self.time_limit)
        if not data and progress.get('synchronous'):
            # The application has signaled that we should handle this
            # request synchronously
            event.wait()
        if not data:
            # Response hasn't come through in time
            id = make_id()
            self.pending[id] = [data, event, progress]
            return self.start_wait_page(req, start_response, id)
        else:
            # Response came through before time_limit
            return self.send_page(start_response, data)
    
    def send_wait_page(self, req, start_response, id=None):
        if id is None:
            id = req.GET['waitforit_id']
        if self.pending[id][0]:
            # Response has come through
            data, event, progress = self.pending.pop(id)
            return self.send_page(start_response, data)
        url = req.url
        waitforit_url = req.application_url + '/.waitforit/?waitforit_id=%s' % id
        vars = self.template_option_defaults.copy()
        vars.update(self.template_options)
        vars.update(dict(
            request_url=url,
            waitforit_url=waitforit_url,
            poll_time=self.poll_time,
            time_limit=self.time_limit,
            environ=req.environ,
            request=req,
            id=id))
        page = self.template.substitute(vars)
        if isinstance(page, unicode):
            page = page.encode('utf8')
        res = Response()
        res.content_type = 'text/html'
        res.charset = 'utf8'
        res.body = page
        return res(req.environ, start_response)

    def start_wait_page(self, req, start_response, id):
        url = req.url
        if '?' in url:
            url += '&'
        else:
            url += '?'
        url += 'waitforit_id=%s' % urllib.quote(id)
        exc = HTTPTemporaryRedirect(location=url)
        return exc(req.environ, start_response)

    def send_page(self, start_response, data):
        status, headers, app_iter, exc_info = data
        if status is None and exc_info:
            raise exc_info[0], exc_info[1], exc_info[2]
        start_response(status, headers, exc_info)
        return app_iter

    def check_status(self, req, start_response, id=None):
        assert req.path_info == '/status.json', (
            "Bad PATH_INFO=%r for %r" % (req.path_info, req.url))
        if id is None:
            try:
                id = req.GET['waitforit_id']
            except KeyError:
                body = "There is no pending request with the id %s" % (id or '(unknown)')
                start_response('400 Bad Request', [
                    ('Content-type', 'text/plain'),
                    ('Content-length', str(len(body)))])
                return [body]
        try:
            data, event, progress = self.pending[id]
        except KeyError:
            data, event, progress = [True, None, None]
        if not data:
            result = {'done': False, 'progress': progress}
        else:
            result = {'done': True}
        res = Response(
            status='200 OK',
            body=simplejson.dumps(result),
            content_type='application/json')
        return res(req.environ, start_response)

    def launch_application(self, environ, data, event, progress):
        t = threading.Thread(target=self.run_application_caught,
                             args=(environ, data, event, progress))
        t.setDaemon(True)
        t.start()

    def run_application_caught(self, environ, data, event, progress):
        try:
            return self.run_application(environ, data, event, progress)
        except:
            exc_info = sys.exc_info()
            data[:] = [None, None, exc_info, None]
            raise

    def run_application(self, environ, data, event, progress):
        data[:] = Request(environ).call_application(self.app, catch_exc_info=True)
        event.set()

