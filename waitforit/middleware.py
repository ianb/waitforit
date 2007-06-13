import threading
import urllib
from itertools import count
import time
import md5
from paste.request import path_info_pop, construct_url, get_cookies, parse_formvars
from paste import httpexceptions
from paste import httpheaders
from paste.util.template import HTMLTemplate
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
        path_info = environ.get('PATH_INFO', '')
        if path_info.startswith('/.waitforit/'):
            path_info_pop(environ)
            return self.check_status(environ, start_response)
        try:
            id = self.get_id(environ)
            if id:
                if id in self.pending:
                    return self.send_wait_page(environ, start_response, id=id)
                else:
                    # Bad id, remove it from QS:
                    qs = environ['QUERY_STRING']
                    qs = re.sub(r'&?waitforit_id=[a-f0-9]*', '', qs)
                    qs = re.sub(r'&send$', '', qs)
                    environ['QUERY_STRING'] = qs
                    # Then redirect:
                    exc = httpexceptions.HTTPMovedPermanently(
                        headers=[('Location', construct_url(environ))])
                    return exc(environ, start_response)
        except KeyError:
            # Fresh request
            pass
        if not self.accept_html(environ):
            return self.app(environ, start_response)
        data = []
        progress = {}
        environ['waitforit.progress'] = progress
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
            return self.start_wait_page(environ, start_response, id)
        else:
            # Response came through before time_limit
            return self.send_page(start_response, data)

    def accept_html(self, environ):
        accept = httpheaders.ACCEPT.parse(environ)
        if not accept:
            return True
        for arg in accept:
            if ';' in arg:
                arg = arg.split(';', 1)[0]
            if arg in ('*/*', 'text/*', 'text/html', 'application/xhtml+xml',
                       'application/xml', 'text/xml'):
                return True
        return False
    
    def send_wait_page(self, environ, start_response, id=None):
        if id is None:
            id = self.get_id(environ)
        self.get_id(environ)
        if self.pending[id][0]:
            # Response has come through
            # FIXME: delete cookie
            data, event, progress = self.pending.pop(id)
            return self.send_page(start_response, data)
        request_url = construct_url(environ)
        waitforit_url = construct_url(environ, path_info='/.waitforit/')
        vars = self.template_option_defaults.copy()
        vars.update(self.template_options)
        vars.update(dict(
            request_url=request_url,
            waitforit_url=waitforit_url,
            poll_time=self.poll_time,
            time_limit=self.time_limit,
            environ=environ,
            id=id))
        page = self.template.substitute(vars)
        if isinstance(page, unicode):
            page = page.encode('utf8')
        start_response('200 OK',
                       [('Content-Type', 'text/html; charset=utf8'),
                        ('Content-Length', str(len(page))),
                        ('Set-Cookie', 'waitforit_id=%s' % id),
                        ])
        return [page]

    def start_wait_page(self, environ, start_response, id):
        url = construct_url(environ)
        if '?' in url:
            url += '&'
        else:
            url += '?'
        url += 'waitforit_id=%s' % urllib.quote(id)
        exc = httpexceptions.HTTPTemporaryRedirect(
            headers=[('Location', url)])
        return exc(environ, start_response)

    def send_page(self, start_response, data):
        status, headers, exc_info, app_iter = data
        if status is None and exc_info:
            raise exc_info[0], exc_info[1], exc_info[2]
        start_response(status, headers, exc_info)
        return app_iter

    def get_id(self, environ):
        qs = parse_formvars(environ)
        return qs['waitforit_id']

    def check_status(self, environ, start_response, id=None):
        assert environ['PATH_INFO'] == '/status.json', (
            "Bad PATH_INFO=%r for %r" % (environ['PATH_INFO'], construct_url(environ)))
        if id is None:
            try:
                id = self.get_id(environ)
            except KeyError:
                body = "There is no pending request with the id %s" % id
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
        content = simplejson.dumps(result)
        start_response('200 OK',
                       [('Content-Type', 'application/json'),
                        ('Content-Length', str(len(content))),
                        ])
        return [content]

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
        start_response_data = []
        output = []
        def start_response(status, headers, exc_info=None):
            start_response_data[:] = [status, headers, exc_info]
            return output.append
        app_iter = self.app(environ, start_response)
        if output:
            # Stupid start_response writer...
            try:
                output.extend(app_iter)
            finally:
                if hasattr(app_iter, 'close'):
                    app_iter.close()
            app_iter = output
        elif not start_response_data or hasattr(app_iter, 'close'):
            # Stupid out-of-order call...
            # Or we want to make sure that app_iter.close() is called
            # in the thread the app_iter was created in.
            try:
                new_app_iter = list(app_iter)
            finally:
                if hasattr(app_iter, 'close'):
                    app_iter.close()
            app_iter = new_app_iter
            assert start_response_data
        start_response_data.append(app_iter)
        data[:] = start_response_data
        event.set()

