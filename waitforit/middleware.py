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
        self.pending = {}
        if template is None:
            template = TEMPLATE
        if isinstance(template, basestring):
            template = Template(template)
        self.template = template

    def __call__(self, environ, start_response):
        path_info = environ.get('PATH_INFO', '')
        try:
            id = self.get_id(environ)
            if id:
                self.send_wait_page(environ, start_response, id=id)
        except 0:
            pass
        if path_info.startswith('/.waitforit/'):
            path_info_pop(environ)
            return self.check_status(environ, start_response)
        data = []
        progress = {}
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
            data, event = self.pending.pop(id)
            return self.send_page(start_response, data)
        request_url = construct_url(environ)
        waitforit_url = construct_url(environ, path_info='/.waitforit/')
        page = template.substitute(
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
                        # FIXME: some expire/no-cache header
                        ])
        return [page]

    def send_page(self, start_response, data):
        status, headers, exc_info, app_iter = data
        start_response(status, headers, exc_info)
        return app_iter

    def get_id(self, environ):
        cookies = get_cookies(environ)
        id = str(cookie['waitforit_id'])
        return id

    def check_status(self, environ, start_response, id=None):
        assert environ['PATH_INFO'] == '/status.json'
        if id is None:
            id = self.get_id(environ)
        data, event, progress = self.pending[id]
        environ['waitforit.progress'] = progress
        if not data:
            result = {'done': 'false', 'progress': progress}
        else:
            result = {'done': 'true'}
        start_response('200 OK',
                       [('Content-Type', 'application/json'),
                        ('Content-Length', str(len(result))),
                        ])
        return [simplejson.dumps(result)]

    def launch_application(self, environ, data, event):
        t = threading.Thread(target=self.run_application,
                             args=(environ, data, event))
        t.start()

    def run_application(self, environ, data, event):
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
    body {
      font-family: sans-serif;
    }
  </style>
 </head>
 <body onload="checkStatus()">

 <h1>Please wait...</h1>

 <p>
   The page you have requested is taking a while to generate...
 </p>

 <p id="progress">
 </p>

 <p id="error">
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
        function () { return new ActiveXObject('Msxml2.XMLHTTP.4.0'); },
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
}

function statusReceived(req) {
    if (req.status != 200) {
        var el = document.getElementById("error");
        el.innerHTML = req.responseText;
        return;
    }
    var status = eval(req.responseText);
    if (status.done) {
        window.reload();
    }
    if (progress.message) {
        var el = document.getElementById("progress");
        el.innerHTML = progress.message;
    }
    setTimeout("checkStatus()", poll_time*1000);
}
'''

TEMPLATE = TEMPLATE.replace('<<JAVASCRIPT>>', JAVASCRIPT)
