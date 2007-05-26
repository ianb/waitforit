import threading
from itertools import count
import time
import md5
from paste.request import path_info_pop, construct_url, get_cookies
from paste.util.template import Template
import simplejson

counter = count()

def make_id():
    value = str(time.time()) + str(counter.next())
    h = md5.new(value).hexdigest()
    return h

class WaitForIt(object):

    def __init__(self, app, time_limit, poll_time=10,
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
        path_info = environ.get('PATH_INFO', '')
        if path_info.startswith('/.waitforit/'):
            path_info_pop(environ)
            return self.check_status(environ, start_response)
        try:
            id = self.get_id(environ)
            if id:
                return self.send_wait_page(environ, start_response, id=id)
        except KeyError:
            pass
        data = []
        progress = {}
        environ['waitforit.progress'] = progress
        event = threading.Event()
        self.launch_application(environ, data, event, progress)
        event.wait(self.time_limit)
        if not data:
            # Response hasn't come through in time
            id = make_id()
            self.pending[id] = [data, event, progress]
            return self.send_wait_page(environ, start_response, id)
        else:
            # Response came through before time_limit
            return self.send_page(start_response, data)
    
    def send_wait_page(self, environ, start_response, id=None):
        if id is None:
            id = self.get_id(environ)
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

    def send_page(self, start_response, data):
        status, headers, exc_info, app_iter = data
        headers.append(
            ('Set-Cookie', 'waitforit_id=""; expires="Thu, 2 Aug 2001 12:00:00 UTC"'))
        start_response(status, headers, exc_info)
        return app_iter

    def get_id(self, environ):
        cookies = get_cookies(environ)
        id = cookies['waitforit_id'].value
        return id

    def check_status(self, environ, start_response, id=None):
        assert environ['PATH_INFO'] == '/status.json'
        if id is None:
            try:
                id = self.get_id(environ)
            except KeyError:
                body = "There is no pending request with the id %s" % id
                start_response('400 Bad Request', [
                    ('Content-type', 'text/plain'),
                    ('Content-length', str(len(body)))])
                return [body]
        data, event, progress = self.pending[id]
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
        if not start_response_data:
            # Stupid out-of-order call...
            app_iter = list(app_iter)
            assert start_response_data
        start_response_data.append(app_iter)
        data[:] = start_response_data
        event.set()


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
    xhr.open("GET", waitforit_url + "status.json");
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
        window.location.reload();
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
