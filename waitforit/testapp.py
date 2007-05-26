import time

def slow_app(environ, start_response):
    progress = environ.get('waitforit.progress', {})
    start = time.time()
    while time.time() - start < 60:
        progress['time'] = time.time() - start
        time.sleep(1)
    start_response('200 OK', [('Content-type', 'text/plain')])
    return ['I am boring.']

if __name__ == '__main__':
    from paste.httpserver import serve
    from waitforit.middleware import WaitForIt
    app = WaitForIt(slow_app, 1, 1)
    print 'Open on http://localhost:8080'
    serve(app, host='127.0.0.1', port='8080')
    
