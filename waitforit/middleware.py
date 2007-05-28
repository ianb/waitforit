import threading
import urllib
from itertools import count
import time
import md5
from paste.request import path_info_pop, construct_url, get_cookies, parse_formvars
from paste import httpexceptions
from paste import httpheaders
from paste.util.template import Template
import simplejson
import re

counter = count()

def make_id():
    value = str(time.time()) + str(counter.next())
    h = md5.new(value).hexdigest()
    return h

class WaitForIt(object):

    def __init__(self, app, time_limit=10, poll_time=10,
                 template=None):
        self.app = app
        self.time_limit = time_limit
        self.poll_time = poll_time
        self.pending = {}
        if template is None:
            template = TEMPLATE
        if isinstance(template, basestring):
            template = Template(template)
        self.template = template

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
        page = self.template.substitute(
            request_url=request_url,
            waitforit_url=waitforit_url,
            poll_time=self.poll_time,
            time_limit=self.time_limit,
            environ=environ,
            id=id)
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
        start_response('200 OK',
                       [('Content-Type', 'application/json'),
                        ('Content-Length', str(len(result))),
                        ])
        return [simplejson.dumps(result)]

    def launch_application(self, environ, data, event, progress):
        t = threading.Thread(target=self.run_application,
                             args=(environ, data, event, progress))
        t.setDaemon(True)
        t.start()

    def run_application(self, environ, data, event, progress):
        start_response_data = []
        output = []
        def start_response(status, headers, exc_info=None):
            start_response_data[:] = [status, headers, exc_info]
            return output.append
        app_iter = self.app(environ, start_response)
        if output:
            # Stupid start_response writer...
            output.extend(app_iter)
            app_iter = output
        elif not start_response_data:
            # Stupid out-of-order call...
            app_iter = list(app_iter)
            assert start_response_data
        start_response_data.append(app_iter)
        data[:] = start_response_data
        event.set()

# TODO: handle case when there's no Javascript (it'd just refresh)

TEMPLATE = '''\
<html>
 <head>
  <title>Please wait</title>
  <script type="text/javascript">
    waitforit_url = "{{waitforit_url}}";
    poll_time = {{poll_time}};
    <<JAVASCRIPT>>
  </script>
  <style type="text/css">
    <<CSS>>
  </style>
 </head>
 <body onload="checkStatus()">

 <h1>Please wait...</h1>

 <p>
   The page you have requested is taking a while to generate...
 </p>

 <p id="progress-box">
 </p>

 <p id="percent-box">

 <p id="error-box">
 </p>
 
 </body>
</html>
'''

JAVASCRIPT = '''\
function getXMLHttpRequest() {
    var tryThese = [
        function () { return new XMLHttpRequest(); },
        function () { return new ActiveXObject('Msxml2.XMLHTTP'); },
        function () { return new ActiveXObject('Microsoft.XMLHTTP'); },
        function () { return new ActiveXObject('Msxml2.XMLHTTP.4.0'); }
        ];
    for (var i = 0; i < tryThese.length; i++) {
        var func = tryThese[i];
        try {
            return func();
        } catch (e) {
            // pass
        }
    }
}

function checkStatus() {
    var xhr = getXMLHttpRequest();
    xhr.onreadystatechange = function () {
        if (xhr.readyState == 4) {
            statusReceived(xhr);
        }
    };
    if (waitforit_url.indexOf("?") != -1) {
        var parts = waitforit_url.split("?");
        var base = parts[0];
        var qs = "?" + parts[1];
    } else {
        var base = waitforit_url;
        var qs = '';
    }
    var status_url = base + "status.json" + qs;
    xhr.open("GET", status_url);
    xhr.send(null);
}

var percent_inner = null;

function statusReceived(req) {
    if (req.status != 200) {
        var el = document.getElementById("error-box");
        el.innerHTML = req.responseText;
        return;
    }
    var status = eval("dummy="+req.responseText);
    if (typeof status.done == "undefined") {
        // Something went wrong
        var el = document.getElementById("error-box");
        el.innerHTML = req.responseText;
        return;
    }
    if (status.done) {
        window.location.href = window.location.href + "&send";
        return;
    }
    if (status.progress.message) {
        var el = document.getElementById("progress-box");
        el.innerHTML = status.progress.message;
    }
    if (status.progress.percent) {
        if (! percent_inner) {
            var outer = document.createElement("div");
            outer.setAttribute("id", "percent-container");
            percent_inner = document.createElement("div");
            percent_inner.setAttribute("id", "percent-inner");
            //percent_inner.innerHTML = "&nbsp;";
            outer.appendChild(percent_inner);
            var parent = document.getElementById("percent-box");
            parent.appendChild(outer);
        }
        percent_inner.style.width = ""+Math.round(status.progress.percent) + "%";
    }
    setTimeout("checkStatus()", poll_time*1000);
}
'''

CSS = '''\
body {
  font-family: sans-serif;
}
div#percent-container {
  border: 1px solid #000;
  width: 100%;
  height: 20px;
}
div#percent-inner {
  background-color: #999;
  height: 100%;
}
'''

TEMPLATE = TEMPLATE.replace('<<JAVASCRIPT>>', JAVASCRIPT);
TEMPLATE = TEMPLATE.replace('<<CSS>>', CSS);
